"""
Extended audit rules — R007..R018

These complement the original R001-R006 with checks that an external auditor
would expect on every invoice / financial document. Each rule is intentionally
small and self-contained so a missing field or anomaly produces a clear
explanation that maps to a finding in the report.

Severity guide:
  CRITICAL → blocks approval
  HIGH     → must be reviewed before approval
  MEDIUM   → flag for senior auditor
  LOW      → informational
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional

from .base_rule import AuditRule, RuleResult, Severity


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _decimal(val) -> Optional[Decimal]:
    if val is None or val == "":
        return None
    try:
        return Decimal(str(val))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _date(val) -> Optional[date]:
    if not val:
        return None
    try:
        return date.fromisoformat(str(val))
    except (ValueError, TypeError):
        return None


# ─────────────────────────────────────────────────────────────────────────────
# R007 — Three-way matching (PO ↔ GRN ↔ Invoice)
# ─────────────────────────────────────────────────────────────────────────────
class ThreeWayMatchRule(AuditRule):
    rule_id = "R007"
    rule_name = "Three-Way Match (PO ↔ GRN ↔ Invoice)"
    severity = Severity.HIGH
    # The match is performed ON the invoice, against its PO and GRN. Nothing
    # else in the vocabulary is the third leg of a three-way match.
    applies_to = {"invoice"}
    description = "Verify the invoice matches its purchase order and goods-receipt note."

    def evaluate(self, document, organization_id=None, context=None):
        po_number = (document.get("po_number") or document.get("purchase_order_no") or "").strip()
        if not po_number:
            return self._skip("No PO referenced — three-way match not applicable")

        if not organization_id:
            return self._skip("Organisation context required")

        try:
            from apps.documents.typed_models import PurchaseOrder, GoodsReceiptNote
        except ImportError:
            return self._skip("Typed models unavailable")

        po = PurchaseOrder.objects.filter(
            organization_id=organization_id, po_number__iexact=po_number,
        ).first()
        if not po:
            return self._fail(
                explanation=f"Purchase order {po_number} not found in system",
                details={"po_number": po_number},
            )

        grn = GoodsReceiptNote.objects.filter(
            organization_id=organization_id, po_number__iexact=po_number,
        ).first()
        if not grn:
            return self._fail(
                explanation=f"No goods-receipt note found for PO {po_number} — receipt missing",
                details={"po_number": po_number, "po_id": str(po.id)},
            )

        # Compare totals
        inv_total = _decimal(document.get("total_amount"))
        po_total = _decimal(getattr(po, "total_amount", None))
        if inv_total and po_total and abs(inv_total - po_total) > Decimal("1.00"):
            return self._fail(
                explanation=(
                    f"Invoice total {inv_total} differs from PO total {po_total} by "
                    f"{abs(inv_total - po_total)}"
                ),
                details={"invoice_total": float(inv_total), "po_total": float(po_total)},
            )

        return self._pass(details={"po_number": po_number, "grn_id": str(grn.id)})


# ─────────────────────────────────────────────────────────────────────────────
# R008 — Currency consistency
# ─────────────────────────────────────────────────────────────────────────────
class CurrencyConsistencyRule(AuditRule):
    rule_id = "R008"
    rule_name = "Currency Consistency"
    severity = Severity.MEDIUM
    description = "Currency must be set and use a recognised ISO-4217 code."

    KNOWN_CURRENCIES = {
        "SAR", "USD", "EUR", "GBP", "AED", "KWD", "BHD", "OMR", "QAR", "JOD",
        "EGP", "JPY", "CNY", "INR", "TRY",
    }

    def evaluate(self, document, organization_id=None, context=None):
        currency = (document.get("currency") or "").strip().upper()
        if not currency:
            return self._fail(
                explanation="No currency specified on the document",
                details={"currency": None},
            )
        if currency not in self.KNOWN_CURRENCIES:
            return self._fail(
                explanation=f"Currency '{currency}' is not a recognised ISO-4217 code",
                details={"currency": currency},
            )
        return self._pass(details={"currency": currency})


# ─────────────────────────────────────────────────────────────────────────────
# R009 — VAT rate validity (KSA)
# ─────────────────────────────────────────────────────────────────────────────
class VATRateValidityRule(AuditRule):
    rule_id = "R009"
    rule_name = "VAT Rate Validity"
    severity = Severity.HIGH
    description = "VAT rate must be a valid Saudi rate (0%, 5%, or 15%) when applied."

    VALID_RATES = {Decimal("0"), Decimal("5"), Decimal("15")}

    def evaluate(self, document, organization_id=None, context=None):
        rate = _decimal(document.get("vat_rate"))
        if rate is None:
            return self._skip("No VAT rate specified")

        # Some inputs encode 0.15 as 15% — accept both forms.
        normalised = rate * 100 if rate < 1 else rate

        if normalised not in self.VALID_RATES:
            return self._fail(
                explanation=(
                    f"VAT rate {normalised}% is not a valid Saudi rate "
                    f"(expected 0%, 5%, or 15%)"
                ),
                details={"vat_rate": float(rate), "normalised_pct": float(normalised)},
            )
        return self._pass(details={"vat_rate_pct": float(normalised)})


# ─────────────────────────────────────────────────────────────────────────────
# R010 — Round-number anomaly (Benford-style)
# ─────────────────────────────────────────────────────────────────────────────
class RoundNumberAnomalyRule(AuditRule):
    rule_id = "R010"
    rule_name = "Round-Number Anomaly"
    severity = Severity.LOW
    # "real invoices usually have decimals" is the whole premise, and it is
    # false for the others: a contract worth 50,000 or a payroll run of
    # 120,000 is round because round is what it is, not because someone
    # typed it.
    applies_to = {"invoice", "receipt", "expense_report"}
    description = "Detects unusually round invoice totals that bypass typical rounding."

    def evaluate(self, document, organization_id=None, context=None):
        total = _decimal(document.get("total_amount"))
        if total is None or total <= 0:
            return self._skip("No total amount")

        # Suspicious if total ends in three zeros AND >= 1000.
        if total >= 1000 and total % 1000 == 0:
            return self._fail(
                explanation=(
                    f"Total {total} is suspiciously round (multiple of 1000) — "
                    "manual entries often round, real invoices usually have decimals"
                ),
                details={"total_amount": float(total)},
            )
        return self._pass()


# ─────────────────────────────────────────────────────────────────────────────
# R011 — Line-item math reconciliation
# ─────────────────────────────────────────────────────────────────────────────
class LineItemReconciliationRule(AuditRule):
    rule_id = "R011"
    rule_name = "Line-Item Reconciliation"
    severity = Severity.HIGH
    description = "Sum of line items must equal the declared subtotal."

    def evaluate(self, document, organization_id=None, context=None):
        items = document.get("line_items") or []
        if not items:
            return self._skip("No line items present")

        subtotal = _decimal(document.get("subtotal"))
        if subtotal is None:
            return self._skip("No subtotal declared")

        line_sum = Decimal("0")
        valid_lines = 0
        for li in items:
            if not isinstance(li, dict):
                continue
            amt = _decimal(li.get("total") or li.get("line_total") or li.get("amount"))
            if amt is None:
                qty = _decimal(li.get("quantity")) or Decimal("1")
                price = _decimal(li.get("unit_price") or li.get("price"))
                if price is None:
                    continue
                amt = qty * price
            line_sum += amt
            valid_lines += 1

        if not valid_lines:
            return self._skip("Line items missing amounts")

        diff = abs(line_sum - subtotal)
        if diff > Decimal("0.50"):
            return self._fail(
                explanation=(
                    f"Sum of line items ({line_sum}) does not match subtotal "
                    f"({subtotal}) — difference {diff}"
                ),
                details={
                    "line_sum": float(line_sum),
                    "subtotal": float(subtotal),
                    "difference": float(diff),
                    "valid_lines": valid_lines,
                },
            )
        return self._pass(details={"line_sum": float(line_sum), "lines": valid_lines})


# ─────────────────────────────────────────────────────────────────────────────
# R012 — Negative amount detection
# ─────────────────────────────────────────────────────────────────────────────
class NegativeAmountRule(AuditRule):
    rule_id = "R012"
    rule_name = "Negative Amount Detection"
    severity = Severity.HIGH
    # Its own description says "credit notes are a separate document type".
    # A bank statement is the counter-example: debits are negative by
    # definition, and flagging them is flagging arithmetic.
    applies_to = {"invoice", "purchase_order", "receipt", "expense_report"}
    description = "Invoice amounts should be positive — credit notes are a separate document type."

    def evaluate(self, document, organization_id=None, context=None):
        problems = []
        for field in ("subtotal", "total_amount", "vat_amount"):
            amt = _decimal(document.get(field))
            if amt is not None and amt < 0:
                problems.append(f"{field}={amt}")

        if problems:
            return self._fail(
                explanation=f"Negative amount(s) detected: {', '.join(problems)}",
                details={"negative_fields": problems},
            )
        return self._pass()


# ─────────────────────────────────────────────────────────────────────────────
# R013 — Due-date validity
# ─────────────────────────────────────────────────────────────────────────────
class DueDateValidityRule(AuditRule):
    rule_id = "R013"
    rule_name = "Due-Date Validity"
    severity = Severity.MEDIUM
    # "Net 365" is payment-terms language. A due date on a bank statement or
    # a VAT return is a different concept and should not be judged by it.
    applies_to = {"invoice", "purchase_order"}
    description = "Due date should be after the invoice date and within reasonable terms (Net 365)."

    def evaluate(self, document, organization_id=None, context=None):
        inv_date = _date(document.get("date") or document.get("invoice_date"))
        due_date = _date(document.get("due_date"))
        if not inv_date or not due_date:
            return self._skip("Invoice or due date missing")

        if due_date < inv_date:
            return self._fail(
                explanation=f"Due date {due_date} is before invoice date {inv_date}",
                details={"invoice_date": str(inv_date), "due_date": str(due_date)},
            )

        days = (due_date - inv_date).days
        if days > 365:
            return self._fail(
                explanation=(
                    f"Payment terms exceed 365 days ({days} days) — verify with vendor agreement"
                ),
                details={"days": days},
            )
        return self._pass(details={"payment_terms_days": days})


# ─────────────────────────────────────────────────────────────────────────────
# R014 — VAT number format (KSA — 15 digits, starts/ends with 3)
# ─────────────────────────────────────────────────────────────────────────────
class VATNumberFormatRule(AuditRule):
    rule_id = "R014"
    rule_name = "VAT Number Format"
    severity = Severity.MEDIUM
    description = "Saudi VAT numbers (TRN) must be 15 digits starting and ending with 3."

    def evaluate(self, document, organization_id=None, context=None):
        vat = (document.get("vendor_vat_number") or document.get("seller_vat_number") or "").strip()
        if not vat:
            return self._skip("No VAT number specified")

        # Strip any non-digit characters
        digits = re.sub(r"\D", "", vat)

        if len(digits) != 15:
            return self._fail(
                explanation=f"VAT number '{vat}' has {len(digits)} digits — KSA TRN must be 15",
                details={"vat_number": vat, "digit_count": len(digits)},
            )
        if not (digits.startswith("3") and digits.endswith("3")):
            return self._fail(
                explanation=f"VAT number '{vat}' does not start AND end with 3 (KSA TRN format)",
                details={"vat_number": vat},
            )
        return self._pass(details={"vat_number": digits})


# ─────────────────────────────────────────────────────────────────────────────
# R015 — Vendor approval status
# ─────────────────────────────────────────────────────────────────────────────
class VendorApprovalRule(AuditRule):
    rule_id = "R015"
    rule_name = "Vendor Approval Status"
    severity = Severity.HIGH
    # Same scope VendorRiskRule (R006) already declares for the same reason:
    # these are the types where a counterparty is a vendor being paid.
    applies_to = {"invoice", "purchase_order", "receipt", "expense_report"}
    description = "Invoices from vendors flagged 'blocked' or 'unapproved' must not be processed."

    def evaluate(self, document, organization_id=None, context=None):
        vendor_name = (document.get("vendor_name") or "").strip()
        if not vendor_name or not organization_id:
            return self._skip("No vendor or organisation context")

        try:
            from apps.invoices.models import VendorProfile
        except ImportError:
            return self._skip("VendorProfile unavailable")

        vp = VendorProfile.objects.filter(
            organization_id=organization_id, vendor_name__iexact=vendor_name,
        ).first()
        if not vp:
            return self._pass(details={"vendor": vendor_name, "note": "first_invoice"})

        status = (getattr(vp, "status", "") or "").lower()
        if status in {"blocked", "suspended"}:
            self.severity = Severity.CRITICAL
            return self._fail(
                explanation=f"Vendor '{vendor_name}' is currently {status} — invoice cannot be processed",
                details={"vendor": vendor_name, "vendor_status": status},
            )
        if status == "unapproved":
            return self._fail(
                explanation=f"Vendor '{vendor_name}' has not been approved for transactions",
                details={"vendor": vendor_name, "vendor_status": status},
            )
        return self._pass(details={"vendor": vendor_name, "vendor_status": status})


# ─────────────────────────────────────────────────────────────────────────────
# R016 — Decimal precision (more than 2 dp on amounts is suspicious)
# ─────────────────────────────────────────────────────────────────────────────
class DecimalPrecisionRule(AuditRule):
    rule_id = "R016"
    rule_name = "Decimal Precision"
    severity = Severity.LOW
    description = "Monetary amounts should not have more than 2 decimal places."

    def evaluate(self, document, organization_id=None, context=None):
        problems = []
        for field in ("subtotal", "total_amount", "vat_amount"):
            raw = document.get(field)
            if raw is None or raw == "":
                continue
            s = str(raw)
            if "." in s and len(s.split(".")[-1]) > 2:
                problems.append(f"{field}={raw}")
        if problems:
            return self._fail(
                explanation=(
                    "Amounts with more than 2 decimal places: "
                    + ", ".join(problems)
                    + " — typical of untrimmed system exports"
                ),
                details={"high_precision_fields": problems},
            )
        return self._pass()


# ─────────────────────────────────────────────────────────────────────────────
# R017 — QR code presence (ZATCA Phase 2)
# ─────────────────────────────────────────────────────────────────────────────
class ZatcaQRPresenceRule(AuditRule):
    rule_id = "R017"
    rule_name = "ZATCA QR Code Presence"
    severity = Severity.HIGH
    # ZATCA Phase 2 mandates the TLV QR on tax invoices and on simplified
    # tax invoices — which is what `receipt` is here. It mandates nothing
    # about contracts or bank statements, and this rule was failing those 26
    # times in 34 documents.
    # The SAR/SA default logic below is NOT touched by this shipment.
    applies_to = {"invoice", "receipt"}
    description = "ZATCA Phase 2 simplified-tax invoices must carry a TLV-encoded QR code."

    # ZATCA Phase 2 (e-invoicing integration) mandate enforcement began on
    # 2023-01-01 for the first wave of taxpayers; pre-2023 historical invoices
    # were not required to carry a TLV-encoded QR.
    PHASE2_EFFECTIVE = date(2023, 1, 1)

    def evaluate(self, document, organization_id=None, context=None):
        currency = (document.get("currency") or "SAR").upper()
        country = (document.get("country") or "SA").upper()

        # Only enforce for Saudi-issued tax invoices.
        if currency != "SAR" and country != "SA":
            return self._skip("Not a Saudi tax invoice")

        # Skip historical imports — pre-Phase-2 invoices never had QR.
        inv_date = _date(document.get("date") or document.get("invoice_date"))
        if inv_date and inv_date < self.PHASE2_EFFECTIVE:
            return self._skip(
                f"Historical invoice ({inv_date}) — pre-dates ZATCA Phase 2 mandate"
            )

        has_qr = bool(document.get("has_qr_code") or document.get("qr_code_data"))
        if not has_qr:
            return self._fail(
                explanation="Saudi tax invoice missing ZATCA Phase 2 QR code",
                details={"has_qr_code": False, "country": country, "currency": currency},
            )
        if document.get("qr_code_valid") is False:
            self.severity = Severity.CRITICAL
            return self._fail(
                explanation="ZATCA QR code present but failed TLV validation",
                details={"qr_code_valid": False},
            )
        return self._pass(details={"qr_code": True})


# ─────────────────────────────────────────────────────────────────────────────
# R018 — Mandatory tax-invoice fields (ZATCA + ISA 500)
# ─────────────────────────────────────────────────────────────────────────────
class MandatoryFieldsRule(AuditRule):
    rule_id = "R018"
    rule_name = "Mandatory Tax-Invoice Fields"
    severity = Severity.HIGH
    # REQUIRED_ALIASES below is a list of invoice fields — invoice_number,
    # invoice_date, vendor_name, total, currency. Demanding them from a
    # customer statement is demanding it be an invoice. Same scope as R017:
    # both derive from the ZATCA tax-invoice definition.
    applies_to = {"invoice", "receipt"}
    description = (
        "ZATCA + ISA 500 require: invoice number, invoice date, vendor name, "
        "vendor TRN (for taxable supplies), totals, currency."
    )

    # Each canonical field name → list of aliases the FinancialAIEngine pipeline
    # may use. We accept any of them as evidence the field is present.
    REQUIRED_ALIASES = {
        "invoice_number": ["invoice_number", "document_number", "number", "reference_number"],
        "invoice_date":   ["invoice_date", "date", "doc_date"],
        "vendor_name":    ["vendor_name", "supplier_name", "seller_name"],
        "total_amount":   ["total_amount", "total", "grand_total"],
        "currency":       ["currency", "currency_code"],
    }

    def evaluate(self, document, organization_id=None, context=None):
        missing = []
        for canonical, aliases in self.REQUIRED_ALIASES.items():
            value = next((document.get(a) for a in aliases if document.get(a)), None)
            if not value:
                missing.append(canonical)
        if missing:
            return self._fail(
                explanation=f"Missing mandatory invoice fields: {', '.join(missing)}",
                details={"missing": missing},
            )
        return self._pass(details={"checked_fields": list(self.REQUIRED_ALIASES.keys())})
