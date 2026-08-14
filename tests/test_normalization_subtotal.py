from decimal import Decimal

from core.services.normalization import NormalizationService


def test_normalize_inferrs_missing_subtotal_from_total_and_vat():
    result = NormalizationService().normalize(
        {
            "invoice_number": "CSV-001",
            "total_amount": "1150.00",
            "vat_amount": "150.00",
            "vat_rate": "15",
        }
    )

    assert result.normalized_data["subtotal"] == Decimal("1000.00")
    assert "Subtotal inferred from total amount, VAT amount, and discount." in result.warnings


def test_normalize_never_replaces_an_explicit_subtotal():
    result = NormalizationService().normalize(
        {
            "invoice_number": "CSV-002",
            "subtotal": "900.00",
            "total_amount": "1150.00",
            "vat_amount": "150.00",
        }
    )

    assert result.normalized_data["subtotal"] == Decimal("900.00")
    assert not any("Subtotal inferred" in warning for warning in result.warnings)
