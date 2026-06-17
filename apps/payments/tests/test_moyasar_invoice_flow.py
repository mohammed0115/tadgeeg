"""MOYASAR-INVOICE-FLOW-A — Moyasar hosted checkout via Invoices API.

All Moyasar I/O is mocked at the HTTP layer (``http_post``/``http_get``) — no
real Moyasar calls, no card data. Verifies the gateway now uses /invoices, maps
the invoice id/url/status correctly, retrieves via /invoices/<id>, parses both
invoice- and payment-shaped webhooks, and that the create view never leaks raw
provider JSON to the user.
"""
import json
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.payments.choices import PaymentStatus
from apps.payments.gateways.base import GatewayError
from apps.payments.gateways.moyasar import MoyasarGateway
from apps.payments.tests._factories import make_org, make_user


class _Resp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class _Req:
    def __init__(self, body: str):
        self.body = body.encode("utf-8")
        self.META = {}


def _txn():
    return SimpleNamespace(
        id="11111111-1111-1111-1111-111111111111",
        organization_id="22222222-2222-2222-2222-222222222222",
        amount=Decimal("75.00"),
        currency="SAR",
        purpose="subscription",
        success_url="https://test.tadgeeg.com/pay/ok/",
        cancel_url="https://test.tadgeeg.com/pay/cancel/",
    )


@override_settings(
    MOYASAR_SECRET_KEY="sk_test_dummy",
    MOYASAR_CALLBACK_URL="https://test.tadgeeg.com/payments/callback/moyasar/",
    MOYASAR_WEBHOOK_URL="https://test.tadgeeg.com/payments/webhooks/moyasar/",
)
class MoyasarCreateInvoiceTests(TestCase):
    @mock.patch("apps.payments.gateways.moyasar.http_post")
    def test_create_payment_posts_to_invoices_endpoint(self, mock_post):
        mock_post.return_value = _Resp(201, {
            "id": "inv_abc", "status": "initiated",
            "amount": 7500, "currency": "SAR",
            "url": "https://moyasar.test/invoice/inv_abc",
        })
        MoyasarGateway().create_payment(_txn())
        url = mock_post.call_args[0][0]
        self.assertTrue(url.endswith("/invoices"))
        self.assertNotIn("/payments", url)

    @mock.patch("apps.payments.gateways.moyasar.http_post")
    def test_payload_has_no_card_source_and_required_fields(self, mock_post):
        mock_post.return_value = _Resp(201, {"id": "inv_abc", "status": "initiated",
                                             "url": "https://moyasar.test/x"})
        MoyasarGateway().create_payment(_txn())
        body = mock_post.call_args.kwargs["json"]
        # No card collection anywhere in the payload.
        self.assertNotIn("source", body)
        flat = json.dumps(body).lower()
        for forbidden in ("creditcard", "cvv", "card", "number", "pan"):
            self.assertNotIn(forbidden, flat)
        # Required hosted-invoice fields.
        self.assertEqual(body["amount"], 7500)
        self.assertEqual(body["currency"], "SAR")
        self.assertIn("description", body)
        self.assertEqual(body["metadata"]["transaction_id"],
                         "11111111-1111-1111-1111-111111111111")

    @mock.patch("apps.payments.gateways.moyasar.http_post")
    def test_success_url_carries_internal_transaction_id(self, mock_post):
        mock_post.return_value = _Resp(201, {"id": "inv_abc", "status": "initiated",
                                             "url": "https://moyasar.test/x"})
        txn = _txn()
        MoyasarGateway().create_payment(txn)
        body = mock_post.call_args.kwargs["json"]
        # Browser landing carries OUR id so the callback never depends on
        # Moyasar's echoed payment id.
        self.assertIn(f"transaction_id={txn.id}", body["success_url"])

    @mock.patch("apps.payments.gateways.moyasar.http_post")
    def test_callback_url_is_webhook_and_separate_from_success_url(self, mock_post):
        mock_post.return_value = _Resp(201, {"id": "inv_abc", "status": "initiated",
                                             "url": "https://moyasar.test/x"})
        MoyasarGateway().create_payment(_txn())
        body = mock_post.call_args.kwargs["json"]
        # callback_url (server notification) is the webhook endpoint, distinct
        # from success_url (browser landing carrying our transaction_id).
        self.assertEqual(body["callback_url"],
                         "https://test.tadgeeg.com/payments/webhooks/moyasar/")
        self.assertIn("transaction_id=", body["success_url"])
        self.assertNotEqual(body["callback_url"], body["success_url"])

    @mock.patch("apps.payments.gateways.moyasar.http_post")
    def test_response_maps_invoice_id_url_and_status(self, mock_post):
        mock_post.return_value = _Resp(201, {
            "id": "inv_abc", "status": "initiated",
            "url": "https://moyasar.test/invoice/inv_abc",
        })
        resp = MoyasarGateway().create_payment(_txn())
        self.assertEqual(resp.provider_payment_id, "inv_abc")
        self.assertEqual(resp.checkout_url, "https://moyasar.test/invoice/inv_abc")
        self.assertEqual(resp.status, PaymentStatus.INITIATED)

    @mock.patch("apps.payments.gateways.moyasar.http_post")
    def test_http_400_raises_gateway_error(self, mock_post):
        mock_post.return_value = _Resp(400, {"message": "bad"})
        with self.assertRaises(GatewayError):
            MoyasarGateway().create_payment(_txn())


@override_settings(MOYASAR_SECRET_KEY="sk_test_dummy")
class MoyasarRetrieveInvoiceTests(TestCase):
    @mock.patch("apps.payments.gateways.moyasar.http_get")
    def test_retrieve_uses_invoices_endpoint_and_maps_paid(self, mock_get):
        mock_get.return_value = _Resp(200, {"id": "inv_abc", "status": "paid",
                                            "url": "https://moyasar.test/x"})
        resp = MoyasarGateway().retrieve_payment("inv_abc")
        url = mock_get.call_args[0][0]
        self.assertTrue(url.endswith("/invoices/inv_abc"))
        self.assertNotIn("/payments/", url)
        self.assertEqual(resp.status, PaymentStatus.PAID)


@override_settings(MOYASAR_SECRET_KEY="sk_test_dummy")
class MoyasarParseWebhookTests(TestCase):
    def test_invoice_shaped_webhook_uses_id(self):
        ev = MoyasarGateway().parse_webhook(_Req(json.dumps(
            {"type": "invoice_paid",
             "data": {"id": "inv_abc", "status": "paid", "amount": 7500, "currency": "SAR"}})))
        self.assertEqual(ev.provider_payment_id, "inv_abc")
        self.assertEqual(ev.status, PaymentStatus.PAID)

    def test_payment_shaped_webhook_matches_on_invoice_id(self):
        ev = MoyasarGateway().parse_webhook(_Req(json.dumps(
            {"data": {"id": "pay_xyz", "invoice_id": "inv_abc", "status": "paid"}})))
        # Matches our stored invoice id, not the inner payment id.
        self.assertEqual(ev.provider_payment_id, "inv_abc")


@override_settings(PAYMENT_PROVIDER="moyasar")
class CreatePaymentViewErrorHardeningTests(TestCase):
    def setUp(self):
        self.org = make_org()
        self.user = make_user(organization=self.org)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    @mock.patch(
        "apps.payments.views.PaymentService.create_transaction",
        side_effect=GatewayError(
            "Moyasar create_invoice HTTP 400: {\"message\": \"source missing\"}"),
    )
    def test_gateway_error_does_not_leak_raw_json_to_user(self, _mock):
        r = self.client.post(reverse("payments:create"),
                             {"amount": "75.00", "currency": "SAR", "purpose": "wallet_topup"},
                             format="json")
        self.assertEqual(r.status_code, 502)
        detail = r.data["detail"]
        # Generic message only — no raw provider text / HTTP code / JSON.
        self.assertNotIn("HTTP 400", detail)
        self.assertNotIn("source", detail)
        self.assertNotIn("{", detail)
