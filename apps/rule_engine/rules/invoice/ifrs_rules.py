"""
IFRS rules pack — meaningful subset.

These rules cover the everyday IFRS principles that apply to a single
financial document being audited. Heavy IFRS topics (consolidation, lease
amortization, deferred tax) need cross-period data and are out of scope for
this single-document rule layer; they belong in a separate "period close"
audit module. What we cover here:

    IFRS-15  Revenue recognition timing
    IFRS-2   Expense matching to the correct period
    IFRS-1   Going-concern indicators
    IFRS-MAT Materiality threshold (rule defaults: 5% of revenue or 100k SAR)
    IFRS-FX  Currency consistency (foreign-currency invoice w/o FX disclosure)
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal

from apps.rule_engine.rules.base import (
    AuditRuleBase, NormalizedDocument, RuleResult, EvidenceItem,
)

logger = logging.getLogger("rule_engine")


class RevenueRecognitionTimingRule(AuditRuleBase):
    """IFRS-15: Revenue recognized when control transfers, not at invoice date.

    For invoices in the *current* period, we accept the issue date as proxy
    for control transfer. For invoices issued near year-end (last 7 days),
    we flag for manual review of the delivery / control-transfer date,
    which is the most common cut-off-error scenario auditors look for.
    """

    rule_code = "IFRS-15"
    rule_name_en = "Revenue Recognition Timing (IFRS 15)"
    rule_name_ar = "توقيت الاعتراف بالإيرادات (IFRS 15)"
    default_severity = "medium"
    rule_type = "compliance"

    YEAR_END_WINDOW_DAYS = 7

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return bool(getattr(doc, "issue_date", None) or getattr(doc, "invoice_date", None))

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        issue_date = getattr(doc, "issue_date", None) or getattr(doc, "invoice_date", None)
        if not issue_date:
            return self._pass("No issue date.")
        if isinstance(issue_date, str):
            try:
                issue_date = date.fromisoformat(issue_date[:10])
            except Exception:
                return self._pass("Issue date unparseable.")

        # Year-end cut-off window: Dec 25 → Jan 7 of next year.
        days_to_year_end = (date(issue_date.year, 12, 31) - issue_date).days
        days_from_year_start = (issue_date - date(issue_date.year, 1, 1)).days

        in_window = (
            days_to_year_end <= self.YEAR_END_WINDOW_DAYS
            or days_from_year_start <= self.YEAR_END_WINDOW_DAYS
        )
        if in_window:
            return self._fail(
                "Invoice is within the year-end cut-off window — verify revenue is recognized in the correct period (IFRS 15).",
                "الفاتورة ضمن نافذة نهاية السنة — يجب التحقق من اعتراف الإيراد في الفترة الصحيحة (IFRS 15).",
                evidence=[EvidenceItem(
                    field_path="issue_date",
                    observed=str(issue_date),
                    expected="confirm delivery / control-transfer date matches the period",
                )],
            )
        return self._pass("Issue date outside year-end cut-off window.")


class ExpenseMatchingRule(AuditRuleBase):
    """IFRS-2 (matching principle): expenses must be recorded in the same
    period as the revenue they relate to.

    Heuristic: an invoice issued > 90 days after the related period end
    suggests late accrual / period mis-match. We can't confirm matching
    without GL data, but we surface the timing as a warning.
    """

    rule_code = "IFRS-2"
    rule_name_en = "Expense Matching / Cut-off (IFRS 2)"
    rule_name_ar = "مبدأ المقابلة وتوقيت المصروفات (IFRS 2)"
    default_severity = "low"
    rule_type = "compliance"

    LATE_THRESHOLD_DAYS = 90

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return bool(
            getattr(doc, "issue_date", None) and getattr(doc, "service_period_end", None)
        )

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        issue = getattr(doc, "issue_date", None) or getattr(doc, "invoice_date", None)
        period_end = getattr(doc, "service_period_end", None)
        if not (issue and period_end):
            return self._pass("Service period unknown — matching check skipped.")
        try:
            if isinstance(issue, str):
                issue = date.fromisoformat(issue[:10])
            if isinstance(period_end, str):
                period_end = date.fromisoformat(period_end[:10])
            delta = (issue - period_end).days
        except Exception:
            return self._pass("Date parse error.")

        if delta > self.LATE_THRESHOLD_DAYS:
            return self._fail(
                f"Invoice issued {delta} days after the service period — possible matching violation.",
                f"الفاتورة صدرت بعد {delta} يومًا من نهاية فترة الخدمة — احتمال إخلال بمبدأ المقابلة.",
                evidence=[EvidenceItem(
                    field_path="issue_date_vs_period",
                    observed=f"{delta} days late",
                    expected=f"<= {self.LATE_THRESHOLD_DAYS} days",
                )],
            )
        return self._pass("Invoice timing aligns with the service period.")


class GoingConcernIndicatorRule(AuditRuleBase):
    """IFRS-1 (going-concern): flag patterns that auditors use as red flags.

    Single-document indicator: amount above an absolute threshold combined
    with a high-risk vendor or a flagged status. Multiple flags = surface
    going-concern review item.
    """

    rule_code = "IFRS-1"
    rule_name_en = "Going-Concern Indicator (IFRS 1)"
    rule_name_ar = "مؤشرات استمرارية المنشأة (IFRS 1)"
    default_severity = "low"
    rule_type = "anomaly"

    LARGE_AMOUNT_THRESHOLD = Decimal("1000000")  # 1M SAR

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        try:
            indicators = []
            amount = Decimal(str(doc.total_amount or 0))
            if amount >= self.LARGE_AMOUNT_THRESHOLD:
                indicators.append(f"large amount ({amount:.0f} SAR)")
            if str(getattr(doc, "approval_status", "") or "").lower() == "rejected":
                indicators.append("rejected status")
            if getattr(doc, "is_duplicate", False):
                indicators.append("duplicate flag")
            if len(indicators) >= 2:
                return self._fail(
                    "Going-concern indicators present: " + ", ".join(indicators),
                    "مؤشرات استمرارية المنشأة موجودة: " + "، ".join(indicators),
                    evidence=[EvidenceItem(
                        field_path="going_concern",
                        observed=", ".join(indicators),
                        expected="≤1 indicator",
                    )],
                )
            return self._pass("No going-concern indicators clustered.")
        except Exception as exc:
            logger.warning("IFRS-1 rule failed: %s", exc)
            return self._pass("Going-concern check skipped.")


class MaterialityThresholdRule(AuditRuleBase):
    """IFRS-MAT: invoices above the materiality threshold must be reviewed.

    Default materiality: max(5% of org revenue, 100,000 SAR). Org revenue is
    pulled from the prior 12-month invoice total when available.
    """

    rule_code = "IFRS-MAT"
    rule_name_en = "Materiality Review Required (IFRS Materiality)"
    rule_name_ar = "مطلوب مراجعة الأهمية النسبية (IFRS)"
    default_severity = "medium"
    rule_type = "compliance"

    DEFAULT_FLOOR = Decimal("100000")
    DEFAULT_PCT = Decimal("0.05")

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return bool(doc.total_amount)

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        try:
            from apps.invoices.models import Invoice
            from django.db.models import Sum
            from datetime import datetime

            cutoff = datetime.now() - timedelta(days=365)
            prior_total = Invoice.objects.filter(
                organization_id=doc.organization_id,
                created_at__gte=cutoff,
            ).aggregate(s=Sum("total_amount"))["s"] or Decimal("0")
            threshold = max(
                self.DEFAULT_FLOOR,
                Decimal(str(prior_total)) * self.DEFAULT_PCT,
            )
            amount = Decimal(str(doc.total_amount or 0))

            if amount >= threshold:
                return self._fail(
                    f"Amount {amount:.0f} meets the materiality threshold ({threshold:.0f}) — auditor review required.",
                    f"المبلغ {amount:.0f} يصل إلى حد الأهمية النسبية ({threshold:.0f}) — مطلوب مراجعة المدقق.",
                    evidence=[EvidenceItem(
                        field_path="total_amount",
                        observed=f"{amount:.0f} SAR",
                        expected=f"< {threshold:.0f} SAR (materiality)",
                    )],
                )
            return self._pass(f"Amount {amount:.0f} below materiality {threshold:.0f}.")
        except Exception as exc:
            logger.warning("IFRS-MAT rule failed: %s", exc)
            return self._pass("Materiality check skipped.")


class CurrencyConsistencyRule(AuditRuleBase):
    """IFRS-FX: foreign-currency invoices must disclose the exchange rate.

    For organizations whose functional currency is SAR, a non-SAR invoice
    without an exchange-rate field is non-conformant.
    """

    rule_code = "IFRS-FX"
    rule_name_en = "Foreign Currency Disclosure (IAS 21)"
    rule_name_ar = "الإفصاح عن العملة الأجنبية (IAS 21)"
    default_severity = "medium"
    rule_type = "compliance"

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        currency = (doc.currency or "SAR").upper()
        if currency == "SAR":
            return self._pass("Local currency (SAR).")
        fx_rate = getattr(doc, "exchange_rate", None) or getattr(doc, "fx_rate", None)
        if not fx_rate:
            return self._fail(
                f"Invoice in {currency} but no exchange rate disclosed (IAS 21).",
                f"الفاتورة بعملة {currency} ولا يوجد سعر صرف معلن (IAS 21).",
                evidence=[EvidenceItem(
                    field_path="exchange_rate",
                    observed="(missing)",
                    expected="exchange_rate present for non-SAR invoices",
                )],
            )
        return self._pass(f"Foreign currency {currency} with disclosed FX rate.")
