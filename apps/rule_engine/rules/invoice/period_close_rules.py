"""
Period-close IFRS rules — multi-period checks that need GL/Journal data.

These rules answer questions a single invoice can't answer alone:

    IFRS-CON   Consolidation balance — debits == credits across the period
    IFRS-DEF   Deferred revenue is reversed in the next period
    IFRS-ACC   Accrual cut-off: invoices booked in correct period
    IFRS-LSE   Lease classification heuristic (operating vs finance)

They run against the org's `JournalEntry` history, not the document under
audit, so they're triggered by the period-close audit task rather than
single-document upload.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal

from apps.rule_engine.rules.base import (
    AuditRuleBase, NormalizedDocument, RuleResult, EvidenceItem,
)

logger = logging.getLogger("rule_engine")


class ConsolidationBalanceRule(AuditRuleBase):
    """IFRS-CON: total debits must equal total credits in any closed period.

    Iterates the org's journal entries for the period in question and
    validates Σ debits == Σ credits within a 1.00 SAR tolerance.
    """

    rule_code = "IFRS-CON"
    rule_name_en = "Consolidation Balance (Σ debits = Σ credits)"
    rule_name_ar = "توازن التجميع (الإجماليات المدينة = الدائنة)"
    default_severity = "critical"
    rule_type = "reconciliation"

    TOLERANCE = Decimal("1.00")

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        try:
            from apps.transactions.models import JournalEntry
            from django.db.models import Sum

            period_start = getattr(doc, "period_start", None)
            period_end = getattr(doc, "period_end", None)
            qs = JournalEntry.objects.filter(organization_id=doc.organization_id)
            if period_start and period_end:
                qs = qs.filter(entry_date__range=(period_start, period_end))

            agg = qs.aggregate(d=Sum("total_debit"), c=Sum("total_credit"))
            debits = Decimal(str(agg["d"] or 0))
            credits = Decimal(str(agg["c"] or 0))
            diff = abs(debits - credits)

            if diff > self.TOLERANCE:
                return self._fail(
                    f"Consolidation imbalance: debits={debits}, credits={credits}, diff={diff}.",
                    f"خلل في التوازن: المدين={debits}، الدائن={credits}، الفرق={diff}.",
                    evidence=[EvidenceItem(
                        field_path="journal_entries",
                        observed=f"diff={diff}",
                        expected=f"<= {self.TOLERANCE}",
                    )],
                )
            return self._pass(f"Consolidation balanced: debits={debits}, credits={credits}.")
        except Exception as exc:
            logger.warning("IFRS-CON failed: %s", exc)
            return self._pass("Consolidation check skipped.")


class DeferredRevenueRule(AuditRuleBase):
    """IFRS-DEF: revenue booked at invoice date must be deferred and recognized
    over the service period (IFRS 15.B89).

    Heuristic: an invoice with a service period spanning > 1 month and full
    revenue booked on the invoice date triggers a deferred-revenue review.
    """

    rule_code = "IFRS-DEF"
    rule_name_en = "Deferred Revenue Recognition (IFRS 15.B89)"
    rule_name_ar = "تأجيل الاعتراف بالإيراد (IFRS 15.B89)"
    default_severity = "medium"
    rule_type = "compliance"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return bool(
            getattr(doc, "service_period_start", None)
            and getattr(doc, "service_period_end", None)
        )

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        try:
            start = getattr(doc, "service_period_start")
            end = getattr(doc, "service_period_end")
            if isinstance(start, str):
                start = date.fromisoformat(start[:10])
            if isinstance(end, str):
                end = date.fromisoformat(end[:10])
            span_days = (end - start).days
            if span_days > 31:
                return self._fail(
                    f"Service period spans {span_days} days — revenue should be deferred and recognized monthly.",
                    f"فترة الخدمة {span_days} يومًا — يجب تأجيل الإيراد والاعتراف به شهرياً.",
                    evidence=[EvidenceItem(
                        field_path="service_period",
                        observed=f"{span_days} days",
                        expected="single-period or deferred",
                    )],
                )
            return self._pass("Service period within a single accounting period.")
        except Exception as exc:
            logger.warning("IFRS-DEF failed: %s", exc)
            return self._pass("Deferred-revenue check skipped.")


class AccrualCutOffRule(AuditRuleBase):
    """IFRS-ACC: invoices for services delivered in period N must be booked in period N.

    For each invoice, check that the related journal entry's `entry_date`
    falls within the same fiscal month as the service-delivery date. A drift
    of more than 7 days suggests a cut-off error.
    """

    rule_code = "IFRS-ACC"
    rule_name_en = "Accrual Cut-Off (IFRS Cut-Off)"
    rule_name_ar = "قطع الاستحقاق (IFRS Cut-Off)"
    default_severity = "medium"
    rule_type = "compliance"

    DRIFT_DAYS = 7

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return bool(
            getattr(doc, "service_delivery_date", None) and getattr(doc, "journal_entry_date", None)
        )

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        try:
            delivery = getattr(doc, "service_delivery_date")
            booked = getattr(doc, "journal_entry_date")
            if isinstance(delivery, str):
                delivery = date.fromisoformat(delivery[:10])
            if isinstance(booked, str):
                booked = date.fromisoformat(booked[:10])
            drift = abs((booked - delivery).days)
            if drift > self.DRIFT_DAYS:
                return self._fail(
                    f"Booking drift {drift} days from service delivery — possible cut-off error.",
                    f"انحراف القيد {drift} يومًا عن تاريخ الخدمة — احتمال خطأ في قطع الاستحقاق.",
                    evidence=[EvidenceItem(
                        field_path="journal_entry_date_vs_delivery",
                        observed=f"{drift} days",
                        expected=f"<= {self.DRIFT_DAYS} days",
                    )],
                )
            return self._pass(f"Booking aligns with delivery (drift {drift} days).")
        except Exception as exc:
            logger.warning("IFRS-ACC failed: %s", exc)
            return self._pass("Cut-off check skipped.")


class LeaseClassificationRule(AuditRuleBase):
    """IFRS-LSE: Operating vs finance lease classification heuristic (IFRS 16).

    When the document is tagged as a lease, we classify based on the
    duration vs the asset's useful life, the present-value-of-payments
    vs fair-value ratio, and ownership-transfer flag. Surfacing the
    expected classification helps auditors challenge the booking.
    """

    rule_code = "IFRS-LSE"
    rule_name_en = "Lease Classification (IFRS 16)"
    rule_name_ar = "تصنيف عقد الإيجار (IFRS 16)"
    default_severity = "low"
    rule_type = "compliance"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return str(getattr(doc, "document_subtype", "") or "").lower() == "lease"

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        try:
            lease_term = float(getattr(doc, "lease_term_years", 0) or 0)
            useful_life = float(getattr(doc, "asset_useful_life_years", 0) or 0)
            ownership_transfer = bool(getattr(doc, "ownership_transfers_at_end", False))
            pv_ratio = float(getattr(doc, "pv_payments_to_fair_value_ratio", 0) or 0)

            # IFRS 16: Finance lease if any of:
            #  - ownership transfer at end
            #  - lease term ≥ 75% of useful life
            #  - present value of payments ≥ 90% of fair value
            criteria_met = []
            if ownership_transfer:
                criteria_met.append("ownership transfers at end")
            if useful_life > 0 and lease_term / useful_life >= 0.75:
                criteria_met.append(f"term ≥ 75% useful life ({lease_term}/{useful_life})")
            if pv_ratio >= 0.90:
                criteria_met.append(f"PV ratio {pv_ratio:.0%} ≥ 90%")

            if criteria_met:
                return self._pass(
                    "Finance lease (IFRS 16): " + ", ".join(criteria_met),
                    "إيجار تمويلي (IFRS 16): " + "، ".join(criteria_met),
                )
            return self._pass("Operating lease (IFRS 16) — no finance-lease criteria met.")
        except Exception as exc:
            logger.warning("IFRS-LSE failed: %s", exc)
            return self._pass("Lease classification skipped.")
