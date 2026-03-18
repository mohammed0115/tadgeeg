from decimal import Decimal

from django.test import SimpleTestCase

from core.services.normalization import NormalizationService


class NormalizationServiceTests(SimpleTestCase):
    def setUp(self):
        self.service = NormalizationService()

    def test_normalizes_aliases_dates_amounts_and_currency(self):
        result = self.service.normalize(
            {
                "supplier": "شركة المورد",
                "tax_id": "300000000000003",
                "invoice_no": "INV-2026-15",
                "invoice_date": "١٢ مارس ٢٠٢٦",
                "currency": "ريال سعودي",
                "amount_before_tax": "1,000.50 SAR",
                "vat": "150.07",
                "grand_total": "١,١٥٠.٥٧",
                "qr_code_presence": "نعم",
            }
        )

        self.assertEqual(result.normalized_data["vendor_name"], "شركة المورد")
        self.assertEqual(result.normalized_data["vendor_vat_number"], "300000000000003")
        self.assertEqual(result.normalized_data["invoice_number"], "INV-2026-15")
        self.assertEqual(result.normalized_data["invoice_date"], "2026-03-12")
        self.assertEqual(result.normalized_data["currency"], "SAR")
        self.assertEqual(result.normalized_data["subtotal"], Decimal("1000.50"))
        self.assertEqual(result.normalized_data["vat_amount"], Decimal("150.07"))
        self.assertEqual(result.normalized_data["total_amount"], Decimal("1150.57"))
        self.assertTrue(result.normalized_data["has_qr_code"])

    def test_ambiguous_date_adds_warning(self):
        result = self.service.normalize({"invoice_date": "03/04/24"})
        self.assertEqual(result.normalized_data["invoice_date"], "2024-04-03")
        self.assertTrue(any("Ambiguous date format" in warning for warning in result.warnings))
