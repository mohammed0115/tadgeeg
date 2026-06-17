"""PLAN-ACTION-MATRIX-A — plans page actions + backend enforcement for active
subscribers. Gateway is mocked; no real Moyasar calls.
"""
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.billing.choices import PlanCode
from apps.billing.models import Plan
from apps.billing.services.subscription_service import SubscriptionService
from apps.billing.tests._factories import make_org, make_user
from apps.payments.choices import PaymentStatus
from apps.payments.gateways.base import GatewayResponse

_CHECKOUT = GatewayResponse(
    provider="moyasar", provider_payment_id="inv_x", provider_reference="",
    checkout_url="https://moyasar.test/inv_x",
    status=PaymentStatus.REDIRECT_REQUIRED, raw_response={},
)


def _mock_gateway():
    return mock.patch(
        "apps.payments.gateways.moyasar.MoyasarGateway.create_payment",
        return_value=_CHECKOUT,
    )


class _Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_billing_plans", stdout=StringIO())

    def setUp(self):
        self.org = make_org()
        self.user = make_user(organization=self.org)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.svc = SubscriptionService()

    def _activate(self, code):
        plan = Plan.objects.get(code=code)
        sub = self.svc.create_pending_paid_subscription(self.org, plan)
        return self.svc.activate_subscription(sub)

    def _plans_html(self):
        return self.client.get("/billing/plans/",
                               HTTP_ACCEPT="text/html,*/*",
                               HTTP_ACCEPT_LANGUAGE="en").content.decode("utf-8")

    def _select(self, code):
        return self.client.post("/billing/select-plan/",
                                {"plan_code": code}, format="json")


class PlansPageMatrixTests(_Base):
    def test_no_active_shows_subscribe_and_trial(self):
        html = self._plans_html()
        assert "Subscribe" in html
        assert "Start free trial" in html

    def test_active_starter_actions(self):
        self._activate(PlanCode.STARTER)
        html = self._plans_html()
        assert "Current plan" in html          # badge on Starter
        assert "Manage subscription" in html    # Starter button
        assert "Upgrade" in html                # Business/Professional
        assert "Subscribe" not in html          # never bare Subscribe when active
        assert "Start free trial" not in html
        assert "Not available" in html          # trial

    def test_active_business_actions(self):
        self._activate(PlanCode.BUSINESS)
        html = self._plans_html()
        assert "Downgrade unavailable" in html   # Starter
        assert "Manage subscription" in html     # Business (current)
        assert "Upgrade" in html                 # Professional

    def test_active_professional_actions_no_upgrade(self):
        self._activate(PlanCode.PROFESSIONAL)
        html = self._plans_html()
        assert "Manage subscription" in html     # Professional current
        assert "Downgrade unavailable" in html   # Starter + Business
        assert "Upgrade" not in html             # top plan → nothing higher


class SelectPlanBackendGuardTests(_Base):
    def test_same_plan_rejected_when_not_renewal(self):
        self._activate(PlanCode.STARTER)  # fresh, far from expiry
        r = self._select(PlanCode.STARTER.value)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.data["code"], "already_subscribed")

    def test_downgrade_rejected_during_active_period(self):
        self._activate(PlanCode.BUSINESS)
        r = self._select(PlanCode.STARTER.value)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.data["code"], "downgrade_unavailable")

    def test_free_trial_rejected_while_active(self):
        self._activate(PlanCode.STARTER)
        r = self._select(PlanCode.FREE_TRIAL.value)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.data["code"], "trial_unavailable")

    def test_upgrade_allowed(self):
        self._activate(PlanCode.STARTER)
        with _mock_gateway():
            r = self._select(PlanCode.BUSINESS.value)
        self.assertIn(r.status_code, (200, 201))
        self.assertIn("next", r.data)

    def test_subscribe_allowed_when_no_active(self):
        with _mock_gateway():
            r = self._select(PlanCode.STARTER.value)
        self.assertIn(r.status_code, (200, 201))
        self.assertIn("next", r.data)

    def test_renew_same_plan_allowed_near_expiry(self):
        sub = self._activate(PlanCode.STARTER)
        sub.ends_at = timezone.now() + timedelta(days=3)
        sub.save(update_fields=["ends_at"])
        with _mock_gateway():
            r = self._select(PlanCode.STARTER.value)
        self.assertIn(r.status_code, (200, 201))  # renewal window → allowed
