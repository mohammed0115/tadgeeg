from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from apps.authentication.models import Organization
from apps.reports.models import Report


class ReportPDFViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.organization = Organization.objects.create(
            name="PDF Org",
            name_ar="مؤسسة التقارير",
            country=Organization.Country.SAUDI_ARABIA,
            currency=Organization.Currency.SAR,
            vat_number="300000000000003",
        )
        self.user = get_user_model().objects.create_user(
            email="pdf@test.finai",
            password="StrongPass123!",
            full_name="PDF User",
            organization=self.organization,
        )
        self.report = Report.objects.create(
            organization=self.organization,
            generated_by=self.user,
            title="Invoice Audit Report - 2026-03-18",
            report_type="invoice_audit",
            language="ar",
            period_from="2026-03-01",
            period_to="2026-03-18",
            data={
                "invoice_audit": {
                    "overall_stats": {
                        "total_invoices": 1,
                        "flagged_count": 0,
                        "duplicate_count": 0,
                        "critical_count": 0,
                        "high_count": 0,
                        "total_amount": 1150,
                        "avg_risk_score": 12.5,
                    },
                    "validation_summary": {"avg_score": 98.5},
                    "top_risk_invoices": [],
                    "vendor_analysis": [],
                    "top_failed_rules": [],
                }
            },
            narrative={"summary": "تقرير اختباري"},
        )
        self.client.force_login(self.user)

    def test_report_pdf_returns_pdf_when_renderer_succeeds(self):
        with patch("apps.reports.views._render_report_pdf_bytes", return_value=b"%PDF-test"):
            response = self.client.get(f"/api/v1/reports/{self.report.id}/pdf/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertEqual(response.content, b"%PDF-test")

    def test_report_pdf_returns_503_when_renderer_dependency_is_missing(self):
        with patch("apps.reports.views._render_report_pdf_bytes", side_effect=ModuleNotFoundError("weasyprint")):
            response = self.client.get(f"/api/v1/reports/{self.report.id}/pdf/")

        self.assertEqual(response.status_code, 503)
        self.assertJSONEqual(
            response.content,
            {"error": "خدمة PDF غير مهيأة على الخادم حاليًا. أعد نشر الخدمة بعد تثبيت مكتبة PDF."},
        )

    def test_document_report_pdf_returns_503_when_system_pdf_libs_are_missing(self):
        with patch("apps.reports.views._render_report_pdf_bytes", side_effect=OSError("missing cairo")):
            response = self.client.get(f"/api/v1/reports/document/{self.report.id}/pdf/")

        self.assertEqual(response.status_code, 503)
        payload = response.json()
        self.assertIn("/html/", payload.get("error", ""))
        self.assertIn("PDF", payload.get("error", ""))

    def test_executive_report_pdf_returns_500_on_generation_failure(self):
        with patch("apps.reports.views._render_report_pdf_bytes", side_effect=RuntimeError("renderer failed")):
            response = self.client.get(f"/api/v1/reports/executive/{self.report.id}/pdf/")

        self.assertEqual(response.status_code, 500)
        payload = response.json()
        self.assertIn("/html/", payload.get("error", ""))
        self.assertIn("PDF", payload.get("error", ""))

    def test_invoice_audit_v2_pdf_returns_500_on_generation_failure(self):
        with patch("apps.reports.views._render_report_pdf_bytes", side_effect=RuntimeError("renderer failed")):
            response = self.client.get(f"/api/v1/reports/invoice-audit/{self.report.id}/pdf/")

        self.assertEqual(response.status_code, 500)
        payload = response.json()
        self.assertIn("/html/", payload.get("error", ""))
        self.assertIn("PDF", payload.get("error", ""))
