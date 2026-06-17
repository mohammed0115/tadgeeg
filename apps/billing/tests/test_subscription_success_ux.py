"""PAYMENT-SUCCESS-UX-A — post-payment confirmation on /billing/subscription/.

The success banner is gated on the subscription being genuinely ACTIVE — a bare
?payment=success can never fake it. No raw provider JSON / card data is rendered.
Rendered in English (Accept-Language: en) to stay locale-safe.
"""
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from apps.billing.choices import PlanCode
from apps.billing.models import Plan
from apps.billing.services.subscription_service import SubscriptionService
from apps.billing.tests._factories import make_org, make_user

_URL = "/billing/subscription/"
_SUCCESS = "your subscription is now active"
_FAILED = "Your subscription was not activated"
_PENDING = "Verifying your payment"


class SubscriptionSuccessUXTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_billing_plans", stdout=StringIO())

    def setUp(self):
        self.org = make_org()
        self.user = make_user(organization=self.org)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _activate(self):
        plan = Plan.objects.get(code=PlanCode.STARTER)
        sub = SubscriptionService().create_pending_paid_subscription(self.org, plan)
        return SubscriptionService().activate_subscription(sub)

    def _get(self, qs=""):
        # Mirror a browser Accept (includes */*) so DRF content negotiation
        # passes while the view still renders HTML (Accept contains text/html).
        return self.client.get(
            _URL + qs,
            HTTP_ACCEPT="text/html,application/xhtml+xml,*/*",
            HTTP_ACCEPT_LANGUAGE="en",
        )

    def test_success_banner_when_active(self):
        self._activate()
        r = self._get("?payment=success")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, _SUCCESS)

    def test_no_success_banner_when_not_active(self):
        # No active subscription → success must NOT render (no false success).
        r = self._get("?payment=success")
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, _SUCCESS)
        # It downgrades to an honest 'verifying' state.
        self.assertContains(r, _PENDING)

    def test_failed_banner(self):
        self._activate()
        r = self._get("?payment=failed")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, _FAILED)
        self.assertNotContains(r, _SUCCESS)

    def test_pending_banner(self):
        self._activate()
        r = self._get("?payment=pending")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, _PENDING)
        self.assertNotContains(r, _SUCCESS)

    def test_no_query_param_renders_ok_without_banner(self):
        self._activate()
        r = self._get()
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, _SUCCESS)
        self.assertNotContains(r, _FAILED)

    def test_no_raw_provider_json_or_card_fields_in_page(self):
        self._activate()
        body = self._get("?payment=success").content.decode("utf-8", "ignore")
        for forbidden in ("raw_request", "raw_response", "raw_webhook",
                          "checkout_url", "idempotency_key"):
            self.assertNotIn(forbidden, body)
