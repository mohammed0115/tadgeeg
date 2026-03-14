"""
VAT Compliance Validator

Validates financial documents against GCC tax regulations,
with a focus on Saudi Arabia ZATCA e-invoicing requirements.

Validation checks:
  C01 — VAT rate is correct (15% SA / per-country)
  C02 — VAT calculation accuracy (subtotal × rate = tax_amount)
  C03 — Subtotal + VAT = total_amount
  C04 — Vendor VAT registration number format
  C05 — ZATCA QR code presence (mandatory for B2C invoices)
  C06 — Invoice number completeness
  C07 — Invoice date is not missing
  C08 — Currency is an ISO 4217 code
  C09 — All line item VAT rates match header rate
  C10 — Customer VAT number (required for B2B invoices above threshold)

Output:
  {
    compliance_score: float (0–1),
    vat_valid: bool,
    missing_fields: list[str],
    issues: list[str],
    checks: dict[str, bool]
  }
"""

import logging
import re
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

logger = logging.getLogger("finai")

# ── Country VAT rates (default) ───────────────────────────────────────────────
COUNTRY_VAT_RATES: dict[str, Decimal] = {
    "SA": Decimal("15.0"),
    "AE": Decimal("5.0"),
    "BH": Decimal("10.0"),
    "KW": Decimal("0.0"),
    "OM": Decimal("5.0"),
    "QA": Decimal("0.0"),
    "EG": Decimal("14.0"),
    "GB": Decimal("20.0"),
    "DE": Decimal("19.0"),
}
DEFAULT_VAT_RATE = Decimal("15.0")

# Saudi VAT number: 15 digits, starts and ends with 3
SAUDI_VAT_REGEX = re.compile(r"^3\d{13}3$")

# Amount tolerance: 0.02 SAR absolute OR 0.5% relative
AMOUNT_TOLERANCE_ABSOLUTE = Decimal("0.02")
AMOUNT_TOLERANCE_RELATIVE = Decimal("0.005")

ISO_CURRENCIES = {
    "SAR", "USD", "EUR", "GBP", "AED", "QAR", "KWD",
    "BHD", "OMR", "EGP", "JPY", "CHF", "CAD", "AUD",
}

# B2B threshold above which customer VAT number is required (SAR)
B2B_THRESHOLD = Decimal("1000.0")


class VATValidator:
    """
    GCC-focused VAT compliance validator.

    Usage:
        validator = VATValidator(country_code="SA")
        result = validator.validate(document)
    """

    def __init__(self, country_code: str = "SA", vat_rate: float = None):
        self.country_code = country_code.upper()
        self.expected_vat_rate = (
            Decimal(str(vat_rate))
            if vat_rate is not None
            else COUNTRY_VAT_RATES.get(self.country_code, DEFAULT_VAT_RATE)
        )

    def validate(self, document: dict) -> dict:
        """
        Run all compliance checks on a normalised document.

        Returns:
            {
              compliance_score: float (0–1),
              vat_valid: bool,
              missing_fields: list[str],
              issues: list[str],
              checks: dict[str, bool]
            }
        """
        checks: dict[str, bool] = {}
        issues: list[str] = []
        missing_fields: list[str] = []

        # ── C01: VAT rate ─────────────────────────────────────────────────────
        declared_rate = self._to_decimal(document.get("vat_rate", 0))
        rate_ok = self._check_vat_rate(declared_rate)
        checks["C01_vat_rate"] = rate_ok
        if not rate_ok:
            issues.append(
                f"VAT rate {declared_rate}% does not match expected "
                f"{self.expected_vat_rate}% for {self.country_code}"
            )

        # ── C02: VAT calculation ──────────────────────────────────────────────
        subtotal = self._to_decimal(document.get("subtotal", 0))
        tax_amount = self._to_decimal(document.get("tax_amount", 0))
        total_amount = self._to_decimal(document.get("total_amount", 0))

        calc_ok = self._check_vat_calculation(subtotal, declared_rate, tax_amount)
        checks["C02_vat_calculation"] = calc_ok
        if not calc_ok and subtotal > 0:
            expected_tax = (subtotal * declared_rate / 100).quantize(Decimal("0.01"))
            issues.append(
                f"VAT calculation error: subtotal {subtotal} × "
                f"{declared_rate}% = {expected_tax}, declared {tax_amount}"
            )

        # ── C03: Subtotal + VAT = total ───────────────────────────────────────
        total_ok = self._check_total_consistency(subtotal, tax_amount, total_amount)
        checks["C03_total_consistency"] = total_ok
        if not total_ok and total_amount > 0:
            issues.append(
                f"Total inconsistency: {subtotal} + {tax_amount} ≠ {total_amount}"
            )

        # ── C04: Vendor VAT number format ─────────────────────────────────────
        vat_num = document.get("vendor_vat_number", "")
        vat_num_ok = self._check_vat_number(vat_num)
        checks["C04_vat_number_format"] = vat_num_ok
        if not vat_num_ok:
            if not vat_num:
                missing_fields.append("vendor_vat_number")
                issues.append("Vendor VAT registration number is missing")
            else:
                issues.append(
                    f"Vendor VAT number '{vat_num}' does not match "
                    f"{self.country_code} format"
                )

        # ── C05: ZATCA QR code ────────────────────────────────────────────────
        has_qr = document.get("has_qr_code", False)
        qr_ok = bool(has_qr) if self.country_code == "SA" else True
        checks["C05_qr_code"] = qr_ok
        if not qr_ok:
            issues.append("ZATCA QR code is missing (required for Saudi e-invoices)")

        # ── C06: Invoice number ───────────────────────────────────────────────
        inv_num = document.get("document_number", "")
        inv_ok = bool(inv_num and inv_num.strip())
        checks["C06_invoice_number"] = inv_ok
        if not inv_ok:
            missing_fields.append("document_number")
            issues.append("Invoice number is missing")

        # ── C07: Invoice date ─────────────────────────────────────────────────
        inv_date = document.get("date")
        date_ok = bool(inv_date)
        checks["C07_invoice_date"] = date_ok
        if not date_ok:
            missing_fields.append("date")
            issues.append("Invoice date is missing")

        # ── C08: Currency code ────────────────────────────────────────────────
        currency = (document.get("currency") or "").upper()
        currency_ok = currency in ISO_CURRENCIES
        checks["C08_currency"] = currency_ok
        if not currency_ok:
            issues.append(f"Currency '{currency}' is not a recognised ISO 4217 code")

        # ── C09: Line item VAT consistency ────────────────────────────────────
        line_items = document.get("line_items", [])
        line_ok = self._check_line_item_vat(line_items, declared_rate)
        checks["C09_line_item_vat"] = line_ok
        if not line_ok:
            issues.append("Line item VAT rates are inconsistent with header VAT rate")

        # ── C10: Customer VAT number for B2B ─────────────────────────────────
        customer_vat = document.get("customer_vat_number", "")
        customer_ok = True
        if total_amount > B2B_THRESHOLD and self.country_code == "SA":
            customer_ok = bool(customer_vat)
            if not customer_ok:
                issues.append(
                    "Customer VAT number required for B2B invoices above "
                    f"{B2B_THRESHOLD} SAR"
                )
        checks["C10_customer_vat"] = customer_ok

        # ── Compliance score ──────────────────────────────────────────────────
        total_checks = len(checks)
        passed_checks = sum(1 for v in checks.values() if v)
        compliance_score = round(passed_checks / max(total_checks, 1), 4)
        vat_valid = checks.get("C02_vat_calculation", False) and checks.get("C03_total_consistency", False)

        return {
            "compliance_score": compliance_score,
            "vat_valid": vat_valid,
            "missing_fields": missing_fields,
            "issues": issues,
            "checks": checks,
            "passed_checks": passed_checks,
            "total_checks": total_checks,
            "country_code": self.country_code,
            "expected_vat_rate": float(self.expected_vat_rate),
        }

    # ── Check implementations ─────────────────────────────────────────────────

    def _check_vat_rate(self, declared: Decimal) -> bool:
        if declared == 0:
            return True  # Exempt / zero-rated
        return abs(declared - self.expected_vat_rate) <= Decimal("0.01")

    def _check_vat_calculation(
        self, subtotal: Decimal, rate: Decimal, declared_tax: Decimal
    ) -> bool:
        if subtotal <= 0 or rate <= 0:
            return True  # Cannot verify without subtotal
        expected = (subtotal * rate / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        diff = abs(expected - declared_tax)
        tolerance = max(AMOUNT_TOLERANCE_ABSOLUTE, expected * AMOUNT_TOLERANCE_RELATIVE)
        return diff <= tolerance

    def _check_total_consistency(
        self, subtotal: Decimal, tax: Decimal, total: Decimal
    ) -> bool:
        if total <= 0:
            return True  # Cannot check empty invoice
        if subtotal <= 0:
            return True  # Cannot check without subtotal
        expected_total = subtotal + tax
        diff = abs(expected_total - total)
        tolerance = max(AMOUNT_TOLERANCE_ABSOLUTE, expected_total * AMOUNT_TOLERANCE_RELATIVE)
        return diff <= tolerance

    def _check_vat_number(self, vat_num: str) -> bool:
        if not vat_num:
            return False
        cleaned = re.sub(r"[\s\-]", "", vat_num)
        if self.country_code == "SA":
            return bool(SAUDI_VAT_REGEX.match(cleaned))
        # Generic: at least 8 alphanumeric chars
        return len(cleaned) >= 8 and cleaned.isalnum()

    def _check_line_item_vat(self, line_items: list, header_rate: Decimal) -> bool:
        if not line_items:
            return True
        for item in line_items:
            item_rate = self._to_decimal(item.get("vat_rate", header_rate))
            if item_rate > 0 and abs(item_rate - header_rate) > Decimal("0.01"):
                return False
        return True

    # ── Utility ───────────────────────────────────────────────────────────────

    @staticmethod
    def _to_decimal(value) -> Decimal:
        if value is None:
            return Decimal("0")
        try:
            return Decimal(str(value).replace(",", "").strip())
        except Exception:
            return Decimal("0")
