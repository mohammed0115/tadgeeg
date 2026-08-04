"""Tests for VAT rules: VAT-01, VAT-02, VAT-04, VAT-05"""
import pytest
from apps.rule_engine.rules.base import NormalizedDocument, RuleStatus
from apps.rule_engine.rules.invoice.vat_calculation_rule import (
    VATCalculationRule,
    VATRateRule,
    VATNumberFormatRule,
    ZATCAQRCodeRule,
)


def make_doc(**kwargs) -> NormalizedDocument:
    defaults = dict(
        document_id="test-vat-001",
        document_type="sales_invoice",
        organization_id="org-001",
    )
    typed = kwargs.pop("typed_data", {})
    defaults.update(kwargs)
    return NormalizedDocument(**defaults, typed_data=typed)


# ─── VAT-02: VATCalculationRule ──────────────────────────────────────────────

class TestVATCalculationRule:
    def setup_method(self):
        self.rule = VATCalculationRule()

    def _doc(self, subtotal, vat_amount, total):
        return make_doc(
            total_amount=total,
            typed_data={"subtotal": subtotal, "vat_amount": vat_amount},
        )

    def test_pass_correct_calculation(self):
        doc = self._doc(1000.00, 150.00, 1150.00)
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.PASS

    def test_fail_wrong_total(self):
        doc = self._doc(1000.00, 150.00, 1200.00)  # discrepancy = 50
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.FAIL
        assert "discrepancy" in result.explanation_en.lower()

    def test_pass_within_default_tolerance(self):
        # Default tolerance = 1.00 SAR; discrepancy of 0.50 should PASS
        doc = self._doc(1000.00, 150.00, 1150.50)
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.PASS

    def test_fail_just_over_tolerance(self):
        # Discrepancy of 1.01 should FAIL
        doc = self._doc(1000.00, 150.00, 1151.01)
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.FAIL

    def test_precondition_missing_subtotal(self):
        doc = make_doc(total_amount=1150.00, typed_data={"vat_amount": 150.00})
        met = self.rule.check_preconditions(doc)
        assert not met

    def test_precondition_missing_vat(self):
        doc = make_doc(total_amount=1150.00, typed_data={"subtotal": 1000.00})
        met = self.rule.check_preconditions(doc)
        assert not met

    def test_precondition_all_present(self):
        doc = self._doc(1000.00, 150.00, 1150.00)
        assert self.rule.check_preconditions(doc)

    def test_arabic_output_on_fail(self):
        doc = self._doc(1000.00, 150.00, 1200.00)
        result = self.rule.execute(doc)
        assert result.explanation_ar != ""

    def test_evidence_on_fail(self):
        doc = self._doc(1000.00, 150.00, 1200.00)
        result = self.rule.execute(doc)
        assert len(result.evidence) == 1
        ev = result.evidence[0]
        assert ev.field_name == "total_amount"

    def test_custom_tolerance_config(self):
        rule = VATCalculationRule(config={"tolerance": "50.00"})
        # discrepancy = 30, tolerance = 50 → should PASS
        doc = self._doc(1000.00, 150.00, 1180.00)
        result = rule.execute(doc)
        assert result.status == RuleStatus.PASS


# ─── VAT-01: VATRateRule ─────────────────────────────────────────────────────

class TestVATRateRule:
    def setup_method(self):
        self.rule = VATRateRule()

    def test_pass_correct_15_percent(self):
        doc = make_doc(typed_data={"vat_rate": 15.0})
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.PASS

    def test_pass_within_tolerance(self):
        doc = make_doc(typed_data={"vat_rate": 15.4})  # within ±0.5
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.PASS

    def test_fail_wrong_rate(self):
        doc = make_doc(typed_data={"vat_rate": 5.0})
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.FAIL

    def test_precondition_missing_rate(self):
        doc = make_doc(typed_data={})
        assert not self.rule.check_preconditions(doc)

    def test_precondition_rate_present(self):
        doc = make_doc(typed_data={"vat_rate": 15.0})
        assert self.rule.check_preconditions(doc)

    def test_arabic_output_on_fail(self):
        doc = make_doc(typed_data={"vat_rate": 5.0})
        result = self.rule.execute(doc)
        assert result.explanation_ar != ""

    def test_evidence_on_fail(self):
        doc = make_doc(typed_data={"vat_rate": 5.0})
        result = self.rule.execute(doc)
        assert result.evidence[0].field_name == "vat_rate"


# ─── VAT-04: VATNumberFormatRule ─────────────────────────────────────────────

class TestVATNumberFormatRule:
    def setup_method(self):
        self.rule = VATNumberFormatRule()

    def test_pass_valid_sa_vat_number(self):
        # ZATCA TRN: 15 digits that must start AND end with 3.
        doc = make_doc(tax_id="300012345678903")  # 15 digits, starts+ends with 3
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.PASS

    def test_fail_wrong_start_digit(self):
        doc = make_doc(tax_id="100012345678901")  # starts with 1
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.FAIL

    def test_fail_too_short(self):
        doc = make_doc(tax_id="30001234567890")  # 14 digits
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.FAIL

    def test_fail_too_long(self):
        doc = make_doc(tax_id="3000123456789012")  # 16 digits
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.FAIL

    def test_fail_non_numeric(self):
        doc = make_doc(tax_id="3ABCD45678901X0")
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.FAIL

    def test_fail_missing_vat_number(self):
        doc = make_doc()  # no tax_id, no typed_data vat number
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.FAIL

    def test_precondition_uses_typed_data_vendor_vat(self):
        doc = make_doc(typed_data={"vendor_vat_number": "300012345678901"})
        assert self.rule.check_preconditions(doc)

    def test_arabic_output(self):
        doc = make_doc(tax_id="12345")
        result = self.rule.execute(doc)
        assert result.explanation_ar != ""


# ─── VAT-05: ZATCAQRCodeRule ──────────────────────────────────────────────────

class TestZATCAQRCodeRule:
    def setup_method(self):
        self.rule = ZATCAQRCodeRule()

    def test_pass_qr_present_and_valid(self):
        doc = make_doc(typed_data={"has_qr_code": True, "qr_code_valid": True})
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.PASS

    def test_warning_qr_missing(self):
        doc = make_doc(typed_data={"has_qr_code": False})
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.WARNING

    def test_fail_qr_present_but_invalid(self):
        doc = make_doc(typed_data={"has_qr_code": True, "qr_code_valid": False})
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.FAIL

    def test_precondition_only_for_invoice_and_receipt(self):
        invoice_doc = make_doc(document_type="sales_invoice")
        receipt_doc = make_doc(document_type="sales_receipt")
        po_doc = make_doc(document_type="purchase_order")
        assert self.rule.check_preconditions(invoice_doc)
        assert self.rule.check_preconditions(receipt_doc)
        assert not self.rule.check_preconditions(po_doc)

    def test_arabic_on_warning(self):
        doc = make_doc(typed_data={"has_qr_code": False})
        result = self.rule.execute(doc)
        assert result.explanation_ar != ""
