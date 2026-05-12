import hashlib
import hmac
import json
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.payments.choices import PaymentStatus
from apps.payments.gateways.base import GatewayResponse
from apps.payments.models import PaymentLog, PaymentTransaction
from apps.payments.services.payment_service import PaymentService
from apps.payments.tests._factories import make_org, make_user


_WEBHOOK_SECRET = "test-webhook-secret"


def _sign(body_bytes: bytes) -> str:
    return "sha256=" + hmac.new(_WEBHOOK_SECRET.encode(), body_bytes, hashlib.sha256).hexdigest()


@override_settings(
    PAYMENT_PROVIDER="moyasar",
    MOYASAR_WEBHOOK_SECRET=_WEBHOOK_SECRET,
)
class MoyasarWebhookTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = make_org()
        self.user = make_user(organization=self.org)
        with mock.patch(
            "apps.payments.gateways.moyasar.MoyasarGateway.create_payment",
            return_value=GatewayResponse(
                provider="moyasar", provider_payment_id="pay_w_1",
                provider_reference="", checkout_url="https://x",
                status=PaymentStatus.REDIRECT_REQUIRED, raw_response={},
            ),
        ):
            self.txn = PaymentService().create_transaction(
                organization=self.org, user=self.user,
                amount=Decimal("75.00"), purpose="wallet_topup",
            )

    def _post_webhook(self, body, *, signature=None):
        raw = json.dumps(body).encode("utf-8")
        kwargs = {"data": raw, "content_type": "application/json"}
        if signature is not None:
            kwargs["HTTP_X_MOYASAR_SIGNATURE"] = signature
        return self.client.post(reverse("payments:webhook-moyasar"), **kwargs)

    def test_paid_webhook_marks_transaction_paid(self):
        body = {"data": {"id": "pay_w_1", "status": "paid", "amount": 7500, "currency": "SAR"}}
        raw = json.dumps(body).encode("utf-8")
        r = self._post_webhook(body, signature=_sign(raw))
        self.assertEqual(r.status_code, 200, r.content)
        self.txn.refresh_from_db()
        self.assertEqual(self.txn.status, PaymentStatus.PAID)
        self.assertIsNotNone(self.txn.paid_at)

    def test_failed_webhook_marks_transaction_failed(self):
        body = {"data": {"id": "pay_w_1", "status": "failed"}}
        raw = json.dumps(body).encode("utf-8")
        r = self._post_webhook(body, signature=_sign(raw))
        self.assertEqual(r.status_code, 200)
        self.txn.refresh_from_db()
        self.assertEqual(self.txn.status, PaymentStatus.FAILED)

    def test_unsigned_webhook_is_rejected(self):
        body = {"data": {"id": "pay_w_1", "status": "paid"}}
        r = self._post_webhook(body)  # no signature header
        self.assertEqual(r.status_code, 401)
        self.txn.refresh_from_db()
        self.assertNotEqual(self.txn.status, PaymentStatus.PAID)

    def test_bad_signature_is_rejected(self):
        body = {"data": {"id": "pay_w_1", "status": "paid"}}
        r = self._post_webhook(body, signature="sha256=deadbeef")
        self.assertEqual(r.status_code, 401)
        self.txn.refresh_from_db()
        self.assertNotEqual(self.txn.status, PaymentStatus.PAID)

    def test_repeated_paid_webhook_does_not_duplicate_business_action(self):
        body = {"data": {"id": "pay_w_1", "status": "paid", "amount": 7500, "currency": "SAR"}}
        raw = json.dumps(body).encode("utf-8")
        self._post_webhook(body, signature=_sign(raw))
        self._post_webhook(body, signature=_sign(raw))

        self.txn.refresh_from_db()
        self.assertEqual(self.txn.status, PaymentStatus.PAID)
        paid_events     = PaymentLog.objects.filter(transaction=self.txn, event_type="paid").count()
        duplicate_events = PaymentLog.objects.filter(transaction=self.txn, event_type="paid_duplicate").count()
        self.assertEqual(paid_events, 1)
        self.assertEqual(duplicate_events, 1)

    def test_webhook_for_unknown_transaction_is_recorded_but_ok(self):
        body = {"data": {"id": "pay_unknown_id", "status": "paid"}}
        raw = json.dumps(body).encode("utf-8")
        r = self._post_webhook(body, signature=_sign(raw))
        # 200 so the provider doesn't escalate retries.
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["result"], "unknown_transaction")

    def test_callback_endpoint_does_not_confirm_payment(self):
        """The /callback/<provider>/ landing page must NEVER set status=paid by itself."""
        # Have sync_status return REDIRECT_REQUIRED — provider isn't done yet.
        with mock.patch(
            "apps.payments.gateways.moyasar.MoyasarGateway.retrieve_payment",
            return_value=GatewayResponse(
                provider="moyasar", provider_payment_id="pay_w_1",
                provider_reference="", checkout_url="",
                status=PaymentStatus.REDIRECT_REQUIRED, raw_response={},
            ),
        ):
            r = self.client.get(
                reverse("payments:callback", kwargs={"provider": "moyasar"}),
                data={"transaction_id": str(self.txn.id)},
            )
        self.assertEqual(r.status_code, 200)
        self.txn.refresh_from_db()
        self.assertNotEqual(self.txn.status, PaymentStatus.PAID)
        self.assertEqual(r.json()["message"], "verifying")
