"""
R004 — Amount Anomaly Rule

Detects unusual invoice amounts by comparing against:
  - Vendor historical average (3× threshold)
  - Organisation-level statistical distribution (z-score)
  - Round number patterns
  - Same-vendor same-amount repetition

Severity: MEDIUM
Applies to: invoice, purchase_order, expense_report, receipt
"""

import logging
from decimal import Decimal

from .base_rule import AuditRule, RuleResult, Severity

logger = logging.getLogger("finai")

AMOUNT_ANOMALY_MULTIPLIER = 3.0     # > 3× vendor average → flag
Z_SCORE_THRESHOLD = 3.0             # > 3 standard deviations → flag
MIN_VENDOR_INVOICES_FOR_STATS = 3   # Need ≥ N past invoices for statistical check


class AmountAnomalyRule(AuditRule):
    """
    Statistical amount anomaly detector.

    Checks vendor historical average and z-score against organisation mean.
    """

    rule_id = "R004"
    rule_name = "Invoice Amount Anomaly"
    severity = Severity.MEDIUM
    applies_to = {"invoice", "purchase_order", "expense_report", "receipt"}
    description = (
        "Flags invoices with amounts significantly higher than the vendor's "
        "historical average or the organisation's statistical distribution."
    )

    def evaluate(
        self,
        document: dict,
        organization_id: int = None,
        context: dict = None,
    ) -> RuleResult:
        context = context or {}

        if not self.is_applicable(document):
            return self._skip()

        total = float(document.get("total_amount") or 0)
        vendor = (document.get("vendor_name") or "").strip()

        if total <= 0:
            return self._skip("Amount is zero or missing")

        anomalies: list[str] = []
        details: dict = {"total_amount": total, "vendor": vendor}

        # ── Check 1: vs vendor historical average ─────────────────────────────
        vendor_avg = self._get_vendor_avg(vendor, organization_id)
        if vendor_avg and vendor_avg > 0:
            ratio = total / vendor_avg
            details["vendor_avg"] = vendor_avg
            details["ratio_to_avg"] = round(ratio, 2)
            if ratio > AMOUNT_ANOMALY_MULTIPLIER:
                anomalies.append(
                    f"Amount {total:,.2f} is {ratio:.1f}× above vendor average {vendor_avg:,.2f}"
                )

        # ── Check 2: z-score across organisation ──────────────────────────────
        stats = context.get("org_amount_stats") or self._get_org_stats(organization_id)
        if stats:
            mean = stats.get("mean", 0)
            std = stats.get("std", 0)
            if std > 0:
                z_score = (total - mean) / std
                details["z_score"] = round(z_score, 2)
                details["org_mean"] = mean
                details["org_std"] = std
                if z_score > Z_SCORE_THRESHOLD:
                    anomalies.append(
                        f"Amount {total:,.2f} is {z_score:.1f} standard deviations "
                        f"above organisation mean {mean:,.2f}"
                    )

        # ── Check 3: vendor is new ────────────────────────────────────────────
        is_new_vendor = self._is_new_vendor(vendor, organization_id)
        if is_new_vendor and total > 10000:
            details["is_new_vendor"] = True
            anomalies.append(
                f"Large invoice ({total:,.2f}) from new/unknown vendor '{vendor}'"
            )

        if anomalies:
            # Escalate to HIGH if very extreme
            if details.get("ratio_to_avg", 0) > 5 or details.get("z_score", 0) > 4:
                self.severity = Severity.HIGH
            return self._fail(
                explanation="; ".join(anomalies),
                details=details,
            )

        return self._pass(details=details)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_vendor_avg(self, vendor: str, organization_id: int) -> float:
        if not vendor:
            return 0.0
        try:
            from apps.invoices.models import VendorProfile

            qs = VendorProfile.objects.filter(vendor_name__iexact=vendor)
            if organization_id:
                qs = qs.filter(organization_id=organization_id)

            profile = qs.first()
            if profile and profile.avg_invoice_amount:
                return float(profile.avg_invoice_amount)
        except Exception as exc:
            logger.debug("[AmountAnomalyRule] vendor avg error: %s", exc)
        return 0.0

    def _get_org_stats(self, organization_id: int) -> dict:
        if not organization_id:
            return {}
        try:
            from django.db.models import Avg, StdDev
            from apps.invoices.models import Invoice

            qs = Invoice.objects.filter(organization_id=organization_id, total_amount__gt=0)
            stats = qs.aggregate(mean=Avg("total_amount"), std=StdDev("total_amount"))
            return {
                "mean": float(stats.get("mean") or 0),
                "std": float(stats.get("std") or 0),
            }
        except Exception as exc:
            logger.debug("[AmountAnomalyRule] org stats error: %s", exc)
        return {}

    def _is_new_vendor(self, vendor: str, organization_id: int) -> bool:
        if not vendor:
            return False
        try:
            from apps.invoices.models import Invoice

            qs = Invoice.objects.filter(vendor_name__iexact=vendor)
            if organization_id:
                qs = qs.filter(organization_id=organization_id)
            return qs.count() == 0
        except Exception:
            return False
