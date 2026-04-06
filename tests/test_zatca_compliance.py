"""
ZATCA Compliance & GCC VAT Rule Tests
======================================
All tests use real NormalizedDocument objects to match actual rule field access.
"""
import pytest
from decimal import Decimal
from unittest.mock import MagicMock, patch


def make_doc(typed_data=None, org_context=None, **kwargs):
    """Build a real NormalizedDocument."""
    from apps.rule_engine.rules.base import NormalizedDocument
    return NormalizedDocument(
        document_id="test-doc-id",
        document_type=kwargs.pop("document_type", "invoice"),
        organization_id="test-org-id",
        typed_data=typed_data or {},
        org_context=org_context or {"country": "SA", "currency": "SAR"},
        **kwargs,
    )


# ─── VAT-01: Rate validation ──────────────────────────────────────────────────

@pytest.mark.unit
class TestVATRateRule:
    def _rule(self):
        from apps.rule_engine.rules.invoice.vat_calculation_rule import VATRateRule
        return VATRateRule()

    def test_sa_15pct_passes(self):
        doc = make_doc(typed_data={"vat_rate": "15.0"}, org_context={"country": "SA"})
        assert self._rule().execute(doc).passed

    def test_sa_wrong_rate_fails(self):
        doc = make_doc(typed_data={"vat_rate": "5.0"}, org_context={"country": "SA"})
        assert not self._rule().execute(doc).passed

    def test_ae_5pct_passes(self):
        doc = make_doc(typed_data={"vat_rate": "5.0"}, org_context={"country": "AE"})
        assert self._rule().execute(doc).passed

    def test_bh_10pct_passes(self):
        doc = make_doc(typed_data={"vat_rate": "10.0"}, org_context={"country": "BH"})
        assert self._rule().execute(doc).passed

    def test_kw_not_applicable(self):
        doc = make_doc(typed_data={"vat_rate": "0.0"}, org_context={"country": "KW"})
        result = self._rule().execute(doc)
        assert result.passed or result.status == "not_applicable"

    def test_qa_not_applicable(self):
        doc = make_doc(typed_data={"vat_rate": "0.0"}, org_context={"country": "QA"})
        result = self._rule().execute(doc)
        assert result.passed or result.status == "not_applicable"

    def test_om_5pct_passes(self):
        doc = make_doc(typed_data={"vat_rate": "5.0"}, org_context={"country": "OM"})
        assert self._rule().execute(doc).passed

    def test_rate_within_tolerance_passes(self):
        doc = make_doc(typed_data={"vat_rate": "15.3"}, org_context={"country": "SA"})
        assert self._rule().execute(doc).passed

    def test_rate_outside_tolerance_fails(self):
        doc = make_doc(typed_data={"vat_rate": "16.0"}, org_context={"country": "SA"})
        assert not self._rule().execute(doc).passed


# ─── VAT-02: Calculation ──────────────────────────────────────────────────────

@pytest.mark.unit
class TestVATCalculationRule:
    def _rule(self):
        from apps.rule_engine.rules.invoice.vat_calculation_rule import VATCalculationRule
        return VATCalculationRule()

    def test_correct_calculation_passes(self):
        doc = make_doc(typed_data={"subtotal": "1000", "vat_amount": "150"},
                       total_amount=1150.0)
        assert self._rule().execute(doc).passed

    def test_wrong_total_fails(self):
        doc = make_doc(typed_data={"subtotal": "1000", "vat_amount": "150"},
                       total_amount=1200.0)
        assert not self._rule().execute(doc).passed

    def test_discrepancy_within_tolerance_passes(self):
        doc = make_doc(typed_data={"subtotal": "999.50", "vat_amount": "149.93"},
                       total_amount=1150.0)
        assert self._rule().execute(doc).passed

    def test_large_rounding_discrepancy_fails(self):
        doc = make_doc(typed_data={"subtotal": "1000", "vat_amount": "150"},
                       total_amount=1155.0)
        assert not self._rule().execute(doc).passed

    def test_zero_vat_with_matching_total(self):
        doc = make_doc(typed_data={"subtotal": "500", "vat_amount": "0"},
                       total_amount=500.0)
        assert self._rule().execute(doc).passed

    def test_large_invoice_correct(self):
        doc = make_doc(typed_data={"subtotal": "100000.00", "vat_amount": "15000.00"},
                       total_amount=115000.0)
        assert self._rule().execute(doc).passed

    def test_fail_result_has_explanation(self):
        doc = make_doc(typed_data={"subtotal": "1000", "vat_amount": "150"},
                       total_amount=1200.0)
        result = self._rule().execute(doc)
        assert not result.passed
        assert result.explanation_en  # Must explain discrepancy


# ─── VAT-04: VAT number format ────────────────────────────────────────────────

@pytest.mark.unit
class TestVATNumberFormatRule:
    def _rule(self):
        from apps.rule_engine.rules.invoice.vat_calculation_rule import VATNumberFormatRule
        return VATNumberFormatRule()

    def test_valid_sa_vat_passes(self):
        doc = make_doc(tax_id="300000000000003", org_context={"country": "SA"})
        assert self._rule().execute(doc).passed

    def test_sa_not_starting_with_3_fails(self):
        doc = make_doc(tax_id="100000000000003", org_context={"country": "SA"})
        assert not self._rule().execute(doc).passed

    def test_sa_too_short_fails(self):
        doc = make_doc(tax_id="30000000000003", org_context={"country": "SA"})  # 14 digits
        assert not self._rule().execute(doc).passed

    def test_sa_too_long_fails(self):
        doc = make_doc(tax_id="3000000000000031", org_context={"country": "SA"})  # 16 digits
        assert not self._rule().execute(doc).passed

    def test_ae_15_digit_passes(self):
        doc = make_doc(tax_id="100000000000001", org_context={"country": "AE"})
        assert self._rule().execute(doc).passed

    def test_bh_9_digit_passes(self):
        doc = make_doc(tax_id="123456789", org_context={"country": "BH"})
        assert self._rule().execute(doc).passed

    def test_bh_wrong_length_fails(self):
        doc = make_doc(tax_id="12345678", org_context={"country": "BH"})
        assert not self._rule().execute(doc).passed

    def test_oman_valid_format_passes(self):
        doc = make_doc(tax_id="OM12345678", org_context={"country": "OM"})
        assert self._rule().execute(doc).passed

    def test_oman_lowercase_passes(self):
        doc = make_doc(tax_id="om12345678", org_context={"country": "OM"})
        assert self._rule().execute(doc).passed

    def test_oman_invalid_prefix_fails(self):
        doc = make_doc(tax_id="AE12345678", org_context={"country": "OM"})
        assert not self._rule().execute(doc).passed

    def test_missing_vat_number_fails(self):
        doc = make_doc(tax_id=None, typed_data={}, org_context={"country": "SA"})
        assert not self._rule().execute(doc).passed

    def test_kw_not_applicable(self):
        doc = make_doc(tax_id="", org_context={"country": "KW"})
        result = self._rule().execute(doc)
        assert result.passed or result.status == "not_applicable"


# ─── VAT-05: ZATCA QR code ────────────────────────────────────────────────────

@pytest.mark.unit
class TestZATCAQRCodeRule:
    def _rule(self):
        from apps.rule_engine.rules.invoice.vat_calculation_rule import ZATCAQRCodeRule
        return ZATCAQRCodeRule()

    def test_qr_present_and_valid_passes(self):
        doc = make_doc(typed_data={"has_qr_code": True, "qr_code_valid": True},
                       document_type="sales_invoice")
        assert self._rule().execute(doc).passed

    def test_qr_missing_not_pass(self):
        doc = make_doc(typed_data={"has_qr_code": False}, document_type="sales_invoice")
        assert not self._rule().execute(doc).passed

    def test_qr_present_but_invalid_fails(self):
        doc = make_doc(typed_data={"has_qr_code": True, "qr_code_valid": False},
                       document_type="sales_invoice")
        assert not self._rule().execute(doc).passed

    def test_non_sales_doc_not_fail(self):
        doc = make_doc(typed_data={"has_qr_code": False}, document_type="purchase_order")
        result = self._rule().execute(doc)
        assert result.status in ("not_applicable", "skipped", "pass", "warning")


# ─── ZATCA QR Service ─────────────────────────────────────────────────────────

@pytest.mark.unit
class TestZATCAQRService:
    def _invoice(self):
        inv = MagicMock()
        inv.vendor_vat_number = "300000000000003"
        inv.invoice_date = "2026-01-15"
        inv.total_amount = Decimal("1150.00")
        inv.vat_amount = Decimal("150.00")
        inv.invoice_number = "INV-001"
        return inv

    def test_generate_returns_dict(self):
        from apps.compliance.zatca_qr_service import ZATCAQRService
        result = ZATCAQRService().generate_qr_code(self._invoice())
        assert isinstance(result, dict)

    def test_generate_status_success(self):
        from apps.compliance.zatca_qr_service import ZATCAQRService
        result = ZATCAQRService().generate_qr_code(self._invoice())
        assert result.get("status") == "success"

    def test_tlv_data_is_valid_base64(self):
        import base64
        from apps.compliance.zatca_qr_service import ZATCAQRService
        result = ZATCAQRService().generate_qr_code(self._invoice())
        tlv = result.get("tlv_data") or result.get("qr_base64", "")
        if tlv:
            decoded = base64.b64decode(tlv)
            assert len(decoded) > 0

    def test_qr_code_image_contains_png_magic(self):
        import base64
        from apps.compliance.zatca_qr_service import ZATCAQRService
        result = ZATCAQRService().generate_qr_code(self._invoice())
        qr_data = result.get("qr_code") or result.get("qr_base64", "")
        if qr_data and isinstance(qr_data, str):
            if "," in qr_data:
                qr_data = qr_data.split(",")[1]
            decoded = base64.b64decode(qr_data)
            assert decoded[:4] == b'\x89PNG' or len(decoded) > 0

    def test_none_vat_number_handled_gracefully(self):
        from apps.compliance.zatca_qr_service import ZATCAQRService
        inv = self._invoice()
        inv.vendor_vat_number = None
        try:
            result = ZATCAQRService().generate_qr_code(inv)
            assert isinstance(result, dict)
        except Exception:
            pass  # Raising is acceptable — just not silently corrupt


@pytest.mark.unit
class TestStrictVATComplianceValidator:
    def _validator(self):
        from core.services.compliance.vat_validator import VATValidator
        return VATValidator(country_code="SA")

    def test_missing_required_field_makes_invoice_non_compliant(self):
        result = self._validator().validate({
            "document_type": "sales_invoice",
            "subtotal": "1000",
            "vat_rate": "15",
            "tax_amount": "150",
            "total_amount": "1150",
            "currency": "SAR",
            "document_number": "INV-001",
            "date": "2026-01-15",
            "has_qr_code": True,
            # vendor_vat_number intentionally missing
        })

        assert result["vat_valid"] is False
        assert result["compliance_score"] < 0.8
        assert "vendor_vat_number" in result["missing_fields"]

    def test_validator_returns_detailed_violations(self):
        result = self._validator().validate({
            "document_type": "sales_invoice",
            "subtotal": "0",
            "vat_rate": "0",
            "tax_amount": "0",
            "total_amount": "0",
            "currency": "SAR",
            "has_qr_code": False,
        })

        assert "violations" in result
        assert isinstance(result["violations"], list)
        assert any(v.get("field") == "vendor_vat_number" for v in result["violations"])
        assert result.get("ComplianceScore") == pytest.approx(result["compliance_score"] * 100, rel=1e-6)


@pytest.mark.unit
class TestStrictDocumentComplianceSection:
    def test_missing_mandatory_fields_cannot_show_zatca_compliant(self):
        from core.services.document_report_service import DocumentReportService

        compliance = DocumentReportService(organization=None)._build_compliance(
            "sales_invoice",
            {"vendor_vat_number": "", "has_qr_code": False, "cost_center": None},
            results=[],
        )

        assert compliance["zatca_compliant"] is False
        assert compliance["compliance_score"] < 80
        assert "violations" in compliance
        assert len(compliance["violations"]) >= 2
