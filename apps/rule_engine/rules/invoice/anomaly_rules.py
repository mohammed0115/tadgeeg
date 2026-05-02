"""
Anomaly rules complementing the existing risk engine:
- ANO-002: New / unknown vendor flagged as elevated-risk by default.
- ANO-003: Round-number amounts (101% multiples of 1000) flagged as suspicious.
"""
from __future__ import annotations

import logging
from decimal import Decimal

from apps.rule_engine.rules.base import (
    AuditRuleBase, NormalizedDocument, RuleResult, EvidenceItem,
)

logger = logging.getLogger("rule_engine")


class NewVendorRule(AuditRuleBase):
    """ANO-002: First-time vendor — flag as elevated risk until reviewed.

    A vendor who has never appeared in the org's invoice history is a known
    fraud vector (shell companies, fake invoices). We don't fail the document
    but raise a medium-severity flag so the auditor reviews vendor onboarding.
    """

    rule_code = "ANO-002"
    rule_name_en = "First-Time Vendor"
    rule_name_ar = "مورّد جديد لم يسبق التعامل معه"
    default_severity = "medium"
    rule_type = "anomaly"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return bool(doc.vendor_name)

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        try:
            from apps.invoices.models import Invoice
            prior = Invoice.objects.filter(
                organization_id=doc.organization_id,
                vendor_name__iexact=doc.vendor_name,
            ).exclude(id=doc.document_id).count()

            if prior == 0:
                return self._fail(
                    f"Vendor '{doc.vendor_name}' has no prior invoices — verify legitimacy.",
                    f"المورّد '{doc.vendor_name}' لم يسبق التعامل معه — يجب التحقق من شرعيته.",
                    evidence=[EvidenceItem(
                        field_path="vendor_name",
                        observed=doc.vendor_name,
                        expected="known vendor",
                    )],
                )
            return self._pass(
                f"Vendor known ({prior} prior invoices).",
                f"المورّد معروف ({prior} فاتورة سابقة).",
            )
        except Exception as exc:
            logger.warning("ANO-002 failed: %s", exc)
            return self._pass("Vendor history check skipped.")


class RoundNumberRule(AuditRuleBase):
    """ANO-003: Suspicious round-number amounts (multiples of 1000 with no fractions).

    Round numbers in real invoices are unusual once VAT is involved — most
    legit invoices end in non-trivial decimal amounts. Flag invoices that are
    suspiciously round (e.g., exactly 50,000 or 100,000) as worth a second look.
    """

    rule_code = "ANO-003"
    rule_name_en = "Round-Number Amount"
    rule_name_ar = "مبلغ مدوّر بشكل مريب"
    default_severity = "low"
    rule_type = "anomaly"

    THRESHOLD = Decimal("1000")  # only flag amounts >= 1000 SAR

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return bool(doc.total_amount)

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        try:
            amount = Decimal(str(doc.total_amount or 0))
            if amount < self.THRESHOLD:
                return self._pass("Amount too small to flag.")
            # Round = exactly divisible by 1000 with no fractional part.
            if amount % Decimal("1000") == 0:
                return self._fail(
                    f"Amount {amount} is suspiciously round.",
                    f"المبلغ {amount} مدوّر بشكل غير اعتيادي.",
                    evidence=[EvidenceItem(
                        field_path="total_amount",
                        observed=str(amount),
                        expected="non-round (with VAT decimals)",
                    )],
                )
            return self._pass("Amount has expected non-round structure.")
        except Exception as exc:
            logger.warning("ANO-003 failed: %s", exc)
            return self._pass("Round-number check skipped.")
