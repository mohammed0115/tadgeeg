from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from rest_framework.test import APITestCase

from apps.authentication.models import User
from apps.billing.choices import PlanCode
from apps.billing.models import Plan
from apps.billing.services.subscription_service import SubscriptionService
from apps.billing.tests._factories import make_org


class ReportPackageTierTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_billing_plans", stdout=StringIO())

    def _authenticate_for(self, code):
        org = make_org(f"Report {code}")
        user = User.objects.create_user(
            email=f"{code}@reports.test", password="StrongPass123!",
            full_name="Report Auditor", organization=org,
            role=User.Role.SENIOR_AUDITOR,
        )
        subscription = SubscriptionService().create_pending_paid_subscription(
            org, Plan.objects.get(code=code)
        )
        SubscriptionService().activate_subscription(subscription)
        self.client.force_authenticate(user)
        return org

    @patch("apps.reports.views.generate_audit_narrative")
    def test_starter_cannot_generate_advanced_report(self, narrative):
        self._authenticate_for(PlanCode.STARTER)
        response = self.client.post(
            "/api/v1/reports/generate/", {"report_type": "invoice_audit"}, format="json"
        )
        assert response.status_code == 403
        assert response.data["code"] == "report_tier_required"
        narrative.assert_not_called()

    @patch("apps.reports.views.generate_audit_narrative", return_value="summary")
    def test_starter_can_generate_basic_executive_summary(self, narrative):
        self._authenticate_for(PlanCode.STARTER)
        response = self.client.post(
            "/api/v1/reports/generate/", {"report_type": "executive_summary"}, format="json"
        )
        assert response.status_code == 200
        narrative.assert_called_once()
