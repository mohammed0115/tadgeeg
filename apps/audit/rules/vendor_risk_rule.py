"""
R006 — Vendor Risk Rule

Detects suspicious or high-risk vendor patterns:
  V01 — Vendor name matches known suspicious patterns (test, temp, dummy, …)
  V02 — Vendor is blocked in the VendorProfile risk tier
  V03 — Vendor has a high proportion of flagged/duplicate invoices
  V04 — Vendor spend dominates more than 50% of organisation total
  V05 — Vendor VAT number used by multiple vendor names (identity mismatch)

Severity: LOW (pattern match) → HIGH (blocked vendor / VAT mismatch)
Applies to: invoice, purchase_order, receipt, expense_report
"""

import logging
import re

from .base_rule import AuditRule, RuleResult, Severity

logger = logging.getLogger("finai")

SUSPICIOUS_PATTERNS = re.compile(
    r"\b(test|temp|temporary|dummy|sample|demo|fake|n/a|na|unknown|"
    r"no name|anonymous|vendor\s*\d+|supplier\s*\d+|misc|miscellaneous)\b",
    re.IGNORECASE,
)

DOMINANCE_THRESHOLD = 0.50    # Flag if vendor > 50% of total spend
HIGH_FLAG_RATIO_THRESHOLD = 0.30  # Flag if >30% of vendor invoices were flagged


class VendorRiskRule(AuditRule):
    """
    Vendor risk and suspicious activity detector.
    """

    rule_id = "R006"
    rule_name = "Vendor Risk Assessment"
    severity = Severity.LOW
    applies_to = {"invoice", "purchase_order", "receipt", "expense_report"}
    description = (
        "Checks for suspicious vendor names, blocked vendors, "
        "abnormal spend dominance, and VAT number mismatches."
    )

    def evaluate(
        self,
        document: dict,
        organisation_id: int = None,
        context: dict = None,
    ) -> RuleResult:
        context = context or {}

        if not self.is_applicable(document):
            return self._skip()

        vendor = (document.get("vendor_name") or "").strip()
        vendor_vat = (document.get("vendor_vat_number") or "").strip()

        if not vendor:
            return self._skip("No vendor name in document")

        issues: list[str] = []
        details: dict = {"vendor": vendor, "vendor_vat": vendor_vat}

        # ── V01: Suspicious name pattern ──────────────────────────────────────
        if SUSPICIOUS_PATTERNS.search(vendor):
            self.severity = Severity.MEDIUM
            issues.append(f"Vendor name '{vendor}' matches suspicious pattern")
            details["suspicious_name"] = True

        # ── V02: Blocked vendor ────────────────────────────────────────────────
        profile = self._get_vendor_profile(vendor, organisation_id)
        if profile:
            risk_tier = getattr(profile, "risk_tier", "low")
            if risk_tier == "blocked":
                self.severity = Severity.CRITICAL
                issues.append(f"Vendor '{vendor}' is on the BLOCKED list")
                details["risk_tier"] = "blocked"
            elif risk_tier == "high":
                self.severity = Severity.HIGH
                issues.append(f"Vendor '{vendor}' has HIGH risk tier")
                details["risk_tier"] = "high"

            # ── V03: High flag ratio ──────────────────────────────────────────
            total = getattr(profile, "invoice_count", 0) or 0
            flagged = getattr(profile, "flagged_count", 0) or 0
            if total >= 3 and flagged / total >= HIGH_FLAG_RATIO_THRESHOLD:
                self.severity = max(self.severity, Severity.MEDIUM)
                ratio = flagged / total
                issues.append(
                    f"Vendor '{vendor}' has {ratio:.0%} flagged invoice rate "
                    f"({flagged}/{total})"
                )
                details["flag_ratio"] = round(ratio, 3)

        # ── V04: Spend dominance ──────────────────────────────────────────────
        total_amount = float(document.get("total_amount") or 0)
        if total_amount > 0:
            dominance = self._check_spend_dominance(vendor, total_amount, organisation_id)
            if dominance:
                self.severity = max(self.severity, Severity.MEDIUM)
                issues.append(dominance)
                details["spend_dominance"] = True

        # ── V05: VAT number used by multiple vendors ───────────────────────────
        if vendor_vat:
            mismatch = self._check_vat_identity_mismatch(vendor, vendor_vat, organisation_id)
            if mismatch:
                self.severity = Severity.HIGH
                issues.append(mismatch)
                details["vat_mismatch"] = True

        if issues:
            return self._fail(
                explanation="; ".join(issues),
                details=details,
            )

        return self._pass(details=details)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_vendor_profile(self, vendor: str, organisation_id: int):
        try:
            from apps.invoices.models import VendorProfile

            qs = VendorProfile.objects.filter(vendor_name__iexact=vendor)
            if organisation_id:
                qs = qs.filter(organisation_id=organisation_id)
            return qs.first()
        except Exception as exc:
            logger.debug("[VendorRiskRule] profile lookup error: %s", exc)
        return None

    def _check_spend_dominance(
        self, vendor: str, amount: float, organisation_id: int
    ) -> str:
        try:
            from django.db.models import Sum
            from apps.invoices.models import Invoice

            total_qs = Invoice.objects.filter(total_amount__gt=0)
            vendor_qs = Invoice.objects.filter(
                vendor_name__iexact=vendor, total_amount__gt=0
            )
            if organisation_id:
                total_qs = total_qs.filter(organisation_id=organisation_id)
                vendor_qs = vendor_qs.filter(organisation_id=organisation_id)

            org_total = total_qs.aggregate(t=Sum("total_amount"))["t"] or 0
            vendor_total = vendor_qs.aggregate(t=Sum("total_amount"))["t"] or 0

            if org_total > 0 and vendor_total / org_total >= DOMINANCE_THRESHOLD:
                pct = vendor_total / org_total
                return (
                    f"Vendor '{vendor}' accounts for {pct:.0%} of total organisation "
                    f"spend ({vendor_total:,.2f} of {org_total:,.2f})"
                )
        except Exception as exc:
            logger.debug("[VendorRiskRule] dominance check error: %s", exc)
        return ""

    def _check_vat_identity_mismatch(
        self, vendor: str, vat_number: str, organisation_id: int
    ) -> str:
        try:
            from apps.invoices.models import Invoice

            # Find all distinct vendor names using this VAT number
            qs = Invoice.objects.filter(
                vendor_vat_number=vat_number
            ).exclude(
                vendor_name__iexact=vendor
            )
            if organisation_id:
                qs = qs.filter(organisation_id=organisation_id)

            other_vendors = (
                qs.values_list("vendor_name", flat=True)
                .distinct()[:5]
            )
            if other_vendors:
                others = ", ".join(f"'{v}'" for v in other_vendors if v)
                return (
                    f"VAT number {vat_number} previously used by different "
                    f"vendor(s): {others}"
                )
        except Exception as exc:
            logger.debug("[VendorRiskRule] VAT identity check error: %s", exc)
        return ""
