from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase

from apps.authentication.models import Organization
from apps.billing.services.subscription_service import SubscriptionService
from apps.reports.models import Report


class ReportPDFViewTests(TestCase):
    """PDF rendering, not billing.

    Every test here returned 402 once the quota gate was applied to the report
    endpoints: the org had no subscription, so the request never reached the
    renderer and the assertions were measuring the billing gate instead. The
    subscription below is set up through the real service rather than by
    inserting a row, so the fixture cannot drift away from what activation
    actually produces.
    """

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
        call_command("seed_billing_plans", stdout=StringIO())
        SubscriptionService().create_free_trial(self.organization)
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

    def test_report_pdf_falls_back_to_html_when_the_renderer_is_missing(self):
        """The endpoint stopped returning 503 and now serves the HTML instead.

        That is a deliberate choice — the report exists, and a browser can
        Ctrl+P it — but a 200 is what an API client checks, so the response has
        to be impossible to mistake for a PDF. Three things must hold together:
        the content type, the .html filename, and the fallback header. Any one
        of them alone can be missed by a caller.
        """
        with patch("apps.reports.views._render_report_pdf_bytes", side_effect=ModuleNotFoundError("weasyprint")):
            response = self.client.get(f"/api/v1/reports/{self.report.id}/pdf/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response["Content-Type"])
        self.assertNotIn("application/pdf", response["Content-Type"])
        self.assertIn(".html", response["Content-Disposition"])
        self.assertNotIn(".pdf", response["Content-Disposition"])
        self.assertEqual(response["X-Report-PDF-Fallback"], "html")

    def test_a_successful_pdf_carries_no_fallback_header(self):
        """Otherwise the header means nothing — every response would have it."""
        with patch("apps.reports.views._render_report_pdf_bytes", return_value=b"%PDF-test"):
            response = self.client.get(f"/api/v1/reports/{self.report.id}/pdf/")

        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertNotIn("X-Report-PDF-Fallback", response)

    def test_document_report_pdf_falls_back_to_html_like_the_other_two(self):
        """The 503/200 split across the three PDF endpoints is closed.

        This endpoint answered a missing renderer with 503 + JSON while the
        other two served the HTML with 200, so no client could handle all three
        with one branch. They now agree, and the fallback stays unmistakable:
        text/html, a .html filename, and the header.
        """
        with patch("apps.reports.views._render_report_pdf_bytes", side_effect=OSError("missing cairo")):
            response = self.client.get(f"/api/v1/reports/document/{self.report.id}/pdf/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response["Content-Type"])
        self.assertIn(".html", response["Content-Disposition"])
        self.assertEqual(response["X-Report-PDF-Fallback"], "html")

    def test_executive_report_pdf_returns_500_on_generation_failure(self):
        with patch("apps.reports.views._render_report_pdf_bytes", side_effect=RuntimeError("renderer failed")):
            response = self.client.get(f"/api/v1/reports/executive/{self.report.id}/pdf/")

        self.assertEqual(response.status_code, 500)
        payload = response.json()
        self.assertIn("/html/", payload.get("error", ""))
        self.assertIn("PDF", payload.get("error", ""))

    def test_invoice_audit_v2_pdf_falls_back_to_html_on_generation_failure(self):
        with patch("apps.reports.views._render_report_pdf_bytes", side_effect=RuntimeError("renderer failed")):
            response = self.client.get(f"/api/v1/reports/invoice-audit/{self.report.id}/pdf/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response["Content-Type"])
        self.assertEqual(response["X-Report-PDF-Fallback"], "html")

    def test_the_pdf_endpoints_agree_on_how_they_signal_a_fallback(self):
        """Three PDF endpoints, and they did not answer the same failure alike.

        They used to disagree: two served HTML with 200, the third returned 503
        with a JSON error, so a caller could not write one branch for all three.
        Resolved in favour of the HTML fallback — the report exists and a
        browser can print it — with the header carrying the signal for clients
        that only look at the status code.
        """
        with patch("apps.reports.views._render_report_pdf_bytes", side_effect=ModuleNotFoundError("weasyprint")):
            plain = self.client.get(f"/api/v1/reports/{self.report.id}/pdf/")
            audit = self.client.get(f"/api/v1/reports/invoice-audit/{self.report.id}/pdf/")

            document = self.client.get(f"/api/v1/reports/document/{self.report.id}/pdf/")

        self.assertEqual(plain["X-Report-PDF-Fallback"],
                         audit["X-Report-PDF-Fallback"])
        self.assertEqual(plain["X-Report-PDF-Fallback"],
                         document["X-Report-PDF-Fallback"])
        for response in (plain, audit, document):
            self.assertEqual(response.status_code, 200)
