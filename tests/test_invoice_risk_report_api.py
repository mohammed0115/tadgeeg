from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.authentication.models import Organization
from apps.invoices.models import Invoice

User = get_user_model()


class InvoiceRiskReportViewTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Risk Report Org")
        self.user = User.objects.create_user(
            email="risk-report@example.com",
            password="Pass123!",
            full_name="Risk Reporter",
            organization=self.organization,
            role="admin",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_risk_report_returns_results_alias_and_includes_flagged_high_score_invoice(self):
        Invoice.objects.create(
            organization=self.organization,
            uploaded_by=self.user,
            original_filename="high-score.pdf",
            invoice_number="INV-HIGH-001",
            invoice_date=date(2026, 4, 1),
            vendor_name="Flagged Vendor",
            currency=Invoice.Currency.SAR,
            subtotal=Decimal("1000.00"),
            vat_amount=Decimal("150.00"),
            total_amount=Decimal("1150.00"),
            risk_score=88,
            risk_level=Invoice.Severity.LOW if hasattr(Invoice, 'Severity') else 'low',
            status=Invoice.Status.FLAGGED,
            ai_summary="Potential duplicate and unusual amount pattern.",
        )
        Invoice.objects.create(
            organization=self.organization,
            uploaded_by=self.user,
            original_filename="low-score.pdf",
            invoice_number="INV-LOW-001",
            invoice_date=date(2026, 4, 2),
            vendor_name="Safe Vendor",
            currency=Invoice.Currency.SAR,
            subtotal=Decimal("200.00"),
            vat_amount=Decimal("30.00"),
            total_amount=Decimal("230.00"),
            risk_score=12,
            risk_level="low",
            status=Invoice.Status.APPROVED,
            ai_summary="Looks normal.",
        )

        response = self.client.get("/api/v1/invoices/reports/risk/?page_size=20")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("results", payload)
        self.assertIn("count", payload)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(len(payload["results"]), 1)
        self.assertEqual(payload["results"][0]["invoice_number"], "INV-HIGH-001")
        self.assertEqual(payload["results"], payload["invoices"])
