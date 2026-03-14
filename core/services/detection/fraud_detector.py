"""
Fraud Detector

Analyses a financial document for suspicious patterns and assigns a
fraud_score (0.0–1.0).

Signals detected:
  F01 — Amount far above vendor historical average (3× threshold)
  F02 — Multiple invoices with the same round amount from same vendor
  F03 — Invoice issued outside business hours (before 7am / after 10pm)
  F04 — Suspicious vendor name patterns (test, temp, generic)
  F05 — Date anomalies (future date, date before org registration)
  F06 — Missing vendor VAT number (ZATCA non-compliance indicator)
  F07 — Abnormally high VAT discrepancy
  F08 — Rapid invoice sequence (many invoices same day from same vendor)
  F09 — Round number bias (all amounts suspiciously round)
  F10 — Vendor name/number mismatch vs historical profile
"""

import logging
import re
from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import Optional

logger = logging.getLogger("finai")

# ── Configuration ─────────────────────────────────────────────────────────────
AMOUNT_ANOMALY_MULTIPLIER = 3.0       # Flag if > N× vendor average
SAME_DAY_INVOICE_LIMIT = 5            # Flag if vendor has > N invoices same day
ROUND_NUMBER_THRESHOLD = 0.80         # Flag if ≥ 80% of amount is round
BUSINESS_HOURS_START = 7              # 07:00
BUSINESS_HOURS_END = 22              # 22:00

SUSPICIOUS_VENDOR_PATTERNS = re.compile(
    r"\b(test|temp|temporary|dummy|sample|demo|fake|na|n/a|unknown|vendor\s*\d+|supplier\s*\d+)\b",
    re.IGNORECASE,
)

SIGNAL_WEIGHTS: dict[str, float] = {
    "F01_amount_anomaly":         0.25,
    "F02_same_amount_repeat":     0.20,
    "F03_outside_hours":          0.10,
    "F04_suspicious_vendor":      0.20,
    "F05_date_anomaly":           0.25,
    "F06_missing_vat_number":     0.10,
    "F07_vat_discrepancy":        0.20,
    "F08_rapid_sequence":         0.15,
    "F09_round_number_bias":      0.10,
    "F10_profile_mismatch":       0.15,
}


class FraudDetector:
    """
    Statistical and rule-based fraud signal detector.

    Usage:
        detector = FraudDetector(organisation_id=org.id)
        result = detector.detect(document)
        print(result['fraud_score'], result['fraud_patterns'])
    """

    def __init__(self, organisation_id: int = None):
        self.organisation_id = organisation_id

    def detect(self, document: dict) -> dict:
        """
        Run all fraud detection signals.

        Returns:
            {
              fraud_score: float (0–1),
              fraud_patterns: list[str],
              risk_indicators: dict,
              requires_review: bool
            }
        """
        patterns: list[str] = []
        active_signals: dict[str, float] = {}

        # ── Run each signal ───────────────────────────────────────────────────
        for signal_id, checker in [
            ("F01_amount_anomaly",     self._check_amount_anomaly),
            ("F02_same_amount_repeat", self._check_same_amount_repeat),
            ("F03_outside_hours",      self._check_outside_hours),
            ("F04_suspicious_vendor",  self._check_suspicious_vendor),
            ("F05_date_anomaly",       self._check_date_anomaly),
            ("F06_missing_vat_number", self._check_missing_vat_number),
            ("F07_vat_discrepancy",    self._check_vat_discrepancy),
            ("F08_rapid_sequence",     self._check_rapid_sequence),
            ("F09_round_number_bias",  self._check_round_number_bias),
            ("F10_profile_mismatch",   self._check_profile_mismatch),
        ]:
            try:
                triggered, pattern = checker(document)
                if triggered:
                    weight = SIGNAL_WEIGHTS.get(signal_id, 0.10)
                    active_signals[signal_id] = weight
                    if pattern:
                        patterns.append(pattern)
            except Exception as exc:
                logger.warning("[FraudDetector] Signal %s error: %s", signal_id, exc)

        # ── Aggregate score ───────────────────────────────────────────────────
        fraud_score = self._aggregate(active_signals)
        requires_review = fraud_score >= 0.40

        return {
            "fraud_score": round(fraud_score, 4),
            "fraud_patterns": patterns,
            "risk_indicators": active_signals,
            "requires_review": requires_review,
        }

    # ── Signal implementations ────────────────────────────────────────────────

    def _check_amount_anomaly(self, doc: dict) -> tuple[bool, str]:
        """Invoice amount > 3× vendor historical average."""
        total = float(doc.get("total_amount") or 0)
        vendor = doc.get("vendor_name", "")
        if not total or not vendor:
            return False, ""

        avg = self._get_vendor_avg(vendor)
        if avg and avg > 0 and total > avg * AMOUNT_ANOMALY_MULTIPLIER:
            return True, (
                f"Invoice amount {total:,.2f} is {total / avg:.1f}× above "
                f"vendor '{vendor}' average of {avg:,.2f}"
            )
        return False, ""

    def _check_same_amount_repeat(self, doc: dict) -> tuple[bool, str]:
        """Multiple invoices from same vendor with exact same amount."""
        total = float(doc.get("total_amount") or 0)
        vendor = doc.get("vendor_name", "")
        if not total or not vendor:
            return False, ""

        try:
            from apps.invoices.models import Invoice

            qs = Invoice.objects.filter(total_amount=total, vendor_name__iexact=vendor)
            if self.organisation_id:
                qs = qs.filter(organisation_id=self.organisation_id)

            count = qs.count()
            if count >= 2:
                return True, (
                    f"Vendor '{vendor}' has {count} invoices with identical amount {total:,.2f}"
                )
        except Exception as exc:
            logger.debug("[FraudDetector] same_amount_repeat DB error: %s", exc)

        return False, ""

    def _check_outside_hours(self, doc: dict) -> tuple[bool, str]:
        """Invoice timestamp outside business hours."""
        created_at = doc.get("metadata", {}).get("created_at")
        if not created_at:
            return False, ""

        try:
            if isinstance(created_at, str):
                created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            hour = created_at.hour
            if hour < BUSINESS_HOURS_START or hour >= BUSINESS_HOURS_END:
                return True, (
                    f"Document uploaded at {hour:02d}:00, outside business hours "
                    f"({BUSINESS_HOURS_START}:00–{BUSINESS_HOURS_END}:00)"
                )
        except Exception:
            pass

        return False, ""

    def _check_suspicious_vendor(self, doc: dict) -> tuple[bool, str]:
        """Vendor name matches known suspicious patterns."""
        vendor = doc.get("vendor_name", "")
        if SUSPICIOUS_VENDOR_PATTERNS.search(vendor):
            return True, f"Vendor name '{vendor}' matches suspicious pattern"
        return False, ""

    def _check_date_anomaly(self, doc: dict) -> tuple[bool, str]:
        """Invoice date in future or before organisation registration."""
        date_str = doc.get("date")
        if not date_str:
            return False, ""

        try:
            doc_date = date.fromisoformat(date_str)
            today = date.today()

            if doc_date > today:
                return True, f"Invoice date {doc_date} is in the future"

            # Check against org registration date if available
            if self.organisation_id:
                try:
                    from apps.authentication.models import Organization

                    org = Organization.objects.get(pk=self.organisation_id)
                    reg_date = getattr(org, "created_at", None)
                    if reg_date:
                        reg_date = reg_date.date() if hasattr(reg_date, "date") else reg_date
                        if doc_date < reg_date - timedelta(days=30):
                            return True, (
                                f"Invoice date {doc_date} is before organisation "
                                f"registration date {reg_date}"
                            )
                except Exception:
                    pass
        except (ValueError, TypeError):
            pass

        return False, ""

    def _check_missing_vat_number(self, doc: dict) -> tuple[bool, str]:
        """Vendor VAT number is missing (required for ZATCA compliance)."""
        vat_num = doc.get("vendor_vat_number", "")
        total = float(doc.get("total_amount") or 0)
        if total > 1000 and not vat_num:
            return True, "Vendor VAT number missing on invoice above 1,000 SAR"
        return False, ""

    def _check_vat_discrepancy(self, doc: dict) -> tuple[bool, str]:
        """Computed VAT != declared tax_amount (tolerance 0.01)."""
        total = float(doc.get("total_amount") or 0)
        tax = float(doc.get("tax_amount") or 0)
        subtotal = float(doc.get("subtotal") or 0)
        vat_rate = float(doc.get("vat_rate") or 15.0)

        if total <= 0:
            return False, ""

        # Recompute from subtotal if available
        if subtotal > 0:
            expected_vat = round(subtotal * vat_rate / 100, 2)
            if abs(expected_vat - tax) > 0.01 and abs(expected_vat - tax) / max(expected_vat, 0.01) > 0.02:
                return True, (
                    f"VAT discrepancy: declared {tax:.2f}, expected {expected_vat:.2f} "
                    f"(rate {vat_rate}%)"
                )

        return False, ""

    def _check_rapid_sequence(self, doc: dict) -> tuple[bool, str]:
        """Too many invoices from the same vendor on the same day."""
        vendor = doc.get("vendor_name", "")
        date_str = doc.get("date")
        if not vendor or not date_str:
            return False, ""

        try:
            from apps.invoices.models import Invoice

            qs = Invoice.objects.filter(
                vendor_name__iexact=vendor,
                invoice_date=date_str,
            )
            if self.organisation_id:
                qs = qs.filter(organisation_id=self.organisation_id)

            count = qs.count()
            if count >= SAME_DAY_INVOICE_LIMIT:
                return True, (
                    f"Vendor '{vendor}' has {count} invoices on {date_str} "
                    f"(limit: {SAME_DAY_INVOICE_LIMIT})"
                )
        except Exception as exc:
            logger.debug("[FraudDetector] rapid_sequence DB error: %s", exc)

        return False, ""

    def _check_round_number_bias(self, doc: dict) -> tuple[bool, str]:
        """Total amount is suspiciously round (no cents)."""
        total = float(doc.get("total_amount") or 0)
        if total <= 0:
            return False, ""

        # Check if amount is a whole number or divisible by 100
        if total == int(total) and total >= 500:
            # Check if all line items are also round
            items = doc.get("line_items", [])
            if not items:
                return True, f"Invoice total {total:,.0f} is a suspiciously round number"
            round_items = sum(1 for i in items if float(i.get("total", 0)) == int(float(i.get("total", 0))))
            if round_items == len(items):
                return True, "All line item amounts are suspiciously round"

        return False, ""

    def _check_profile_mismatch(self, doc: dict) -> tuple[bool, str]:
        """Vendor VAT number doesn't match historical profile for this vendor name."""
        vendor = doc.get("vendor_name", "")
        vat_num = doc.get("vendor_vat_number", "")
        if not vendor or not vat_num:
            return False, ""

        try:
            from apps.invoices.models import VendorProfile

            profile = VendorProfile.objects.filter(
                vendor_name__iexact=vendor,
            )
            if self.organisation_id:
                profile = profile.filter(organisation_id=self.organisation_id)

            profile = profile.first()
            if profile:
                historical_vat = getattr(profile, "vendor_vat_number", None)
                if historical_vat and historical_vat != vat_num:
                    return True, (
                        f"Vendor '{vendor}' VAT number changed from "
                        f"{historical_vat} to {vat_num}"
                    )
        except Exception as exc:
            logger.debug("[FraudDetector] profile_mismatch DB error: %s", exc)

        return False, ""

    # ── Aggregation ───────────────────────────────────────────────────────────

    @staticmethod
    def _aggregate(active_signals: dict[str, float]) -> float:
        """
        Combine active signal weights.

        Each additional signal adds diminishing contribution to prevent
        a single category of false positives from dominating the score.
        """
        if not active_signals:
            return 0.0

        weights = sorted(active_signals.values(), reverse=True)
        score = weights[0]
        for i, w in enumerate(weights[1:], start=1):
            score += w * (0.5 ** i)

        return min(score, 1.0)

    # ── Vendor profile helpers ────────────────────────────────────────────────

    def _get_vendor_avg(self, vendor_name: str) -> Optional[float]:
        """Look up average invoice amount for a vendor from VendorProfile."""
        try:
            from apps.invoices.models import VendorProfile

            profile = VendorProfile.objects.filter(vendor_name__iexact=vendor_name)
            if self.organisation_id:
                profile = profile.filter(organisation_id=self.organisation_id)

            p = profile.first()
            if p and p.average_amount:
                return float(p.average_amount)
        except Exception as exc:
            logger.debug("[FraudDetector] vendor avg lookup error: %s", exc)
        return None
