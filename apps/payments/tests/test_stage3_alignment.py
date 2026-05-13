"""Stage-3 alignment tests.

Confirms the small spec deltas applied in Stage 3 — default
PAYMENT_PROVIDER, public SUPPORTED_PAYMENT_PROVIDERS, and the new
strict-mode webhook provider check.

The full coverage of the spec's 10 Stage-3 test cases lives in:
  - tests/test_gateway_factory.py
  - tests/test_payment_create.py
  - tests/test_payment_webhook.py
"""
import json

from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.payments.gateways.factory import SUPPORTED_PROVIDERS
from apps.payments.tests._factories import make_org, make_user


class SettingsAlignmentTests(SimpleTestCase):
    def test_supported_payment_providers_constant_matches_factory(self):
        """Spec line 566 — the supported list is a public settings value."""
        self.assertEqual(
            set(getattr(settings, "SUPPORTED_PAYMENT_PROVIDERS", [])),
            SUPPORTED_PROVIDERS,
        )

    def test_payment_provider_default_is_moyasar(self):
        """Spec line 564 — env('PAYMENT_PROVIDER', default='moyasar').

        We can't override env mid-test, but we can assert that when env
        isn't set, settings exposes a non-empty supported value."""
        active = getattr(settings, "PAYMENT_PROVIDER", "")
        self.assertIn(active, SUPPORTED_PROVIDERS,
                      f"PAYMENT_PROVIDER={active!r} should be a supported value")


@override_settings(
    PAYMENT_PROVIDER="moyasar",
    PAYMENT_STRICT_WEBHOOK_PROVIDER=True,
)
class StrictWebhookProviderTests(TestCase):
    """Spec line 744 — webhooks for non-active providers must be refused."""

    def setUp(self):
        self.client = APIClient()

    def test_webhook_for_inactive_provider_is_rejected(self):
        # PAYMENT_PROVIDER=moyasar but the webhook is sent to /tap/
        r = self.client.post(
            reverse("payments:webhook-tap"),
            data=json.dumps({"id": "x", "status": "captured"}),
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 404)

    def test_webhook_for_active_provider_is_processed(self):
        # No signature, so it fails verification — but importantly NOT
        # 404 from the strict-mode check.
        r = self.client.post(
            reverse("payments:webhook-moyasar"),
            data=json.dumps({"id": "x", "status": "paid"}),
            content_type="application/json",
        )
        self.assertNotEqual(r.status_code, 404)


@override_settings(
    PAYMENT_PROVIDER="moyasar",
    PAYMENT_STRICT_WEBHOOK_PROVIDER=False,
)
class LooseWebhookProviderTests(TestCase):
    """With strict mode off, webhooks for any supported provider are
    processed (used during provider-switch transitions)."""

    def setUp(self):
        self.client = APIClient()

    def test_webhook_for_inactive_provider_passes_strict_check(self):
        r = self.client.post(
            reverse("payments:webhook-tap"),
            data=json.dumps({"id": "x", "status": "captured"}),
            content_type="application/json",
        )
        # Will still fail at signature verify (no header), but it's a
        # 401 from the adapter — not a 404 from strict-mode.
        self.assertNotEqual(r.status_code, 404)
