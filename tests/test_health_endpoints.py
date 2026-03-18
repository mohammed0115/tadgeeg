from unittest.mock import patch

from django.test import TestCase


class HealthEndpointTests(TestCase):
    @patch("core.utils.health_urls.get_health_check_report")
    def test_lightweight_health_endpoint_uses_monitoring_report(self, mock_report):
        mock_report.return_value = {
            "status": "healthy",
            "components": {
                "database": {"status": "healthy"},
                "redis": {"status": "healthy"},
                "tesseract": {"status": "healthy"},
            },
        }

        response = self.client.get("/health/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "healthy")
        self.assertEqual(response.json()["database"], "healthy")

    @patch("core.health_check_views.get_health_check_report")
    def test_api_status_endpoint_is_available(self, mock_report):
        mock_report.return_value = {
            "status": "degraded",
            "timestamp": "2026-03-17T00:00:00Z",
            "components": {
                "redis": {"status": "healthy"},
                "database": {"status": "healthy"},
                "tesseract": {"status": "degraded"},
            },
        }

        response = self.client.get("/api/v1/status/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "degraded")
        self.assertIn("critical_components", response.json())
