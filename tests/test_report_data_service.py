from datetime import date
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.authentication.models import Organization

User = get_user_model()


class ReportDataServiceTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Report Data Org")
        self.user = User.objects.create_user(
            email="report-data@example.com",
            password="Pass123!",
            full_name="Report Data User",
            organization=self.org,
            role="admin",
        )

    def test_collect_invoice_data_returns_expected_sections(self):
        from apps.reports.services.report_data_service import ReportDataService

        service = ReportDataService()
        payload = service.collect_invoice_data(self.org, date_from=date(2026, 1, 1), date_to=date(2026, 12, 31))

        self.assertIn("overall_stats", payload)
        self.assertIn("validation_summary", payload)
        self.assertIn("top_risk_invoices", payload)
        self.assertIn("big_four", payload)
        self.assertIn("benchmark", payload)

    @patch("apps.reports.services.report_data_service.ReportDataService.collect_invoice_data")
    def test_legacy_view_helper_delegates_to_service(self, mock_collect):
        from apps.reports import views

        mock_collect.return_value = {"overall_stats": {"total_invoices": 0}}
        result = views._collect_invoice_data(self.org)

        self.assertEqual(result, {"overall_stats": {"total_invoices": 0}})
        mock_collect.assert_called_once()
