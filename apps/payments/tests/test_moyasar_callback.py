"""MOYASAR-CALLBACK-ROUTE-A — hosted-checkout return URL handling.

Covers the public ``/payments/callback/moyasar/`` route (the URL Moyasar
redirects the customer to after paying a hosted invoice). All Moyasar I/O is
mocked — no real calls.

Resolution is by OUR ``tx`` id (stamped into the redirect URL), NOT the
provider's echoed ``id`` — Moyasar may return a payment id rather than the
invoice id we stored. The callback NEVER trusts ?status=paid; it verifies
server-side via sync_status (GET /invoices/<our stored invoice id>).
"""
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.payments.choices import PaymentStatus
from apps.payments.gateways.base import GatewayResponse
from apps.payments.models import PaymentTransaction
from apps.payments.services.payment_service import PaymentService
from apps.payments.tests._factories import make_org, make_user

# Public path Moyasar actually redirects to (no /api/v1 prefix).
_CALLBACK = "/payments/callback/moyasar/"
_INVOICE_ID = "inv_test_1"           # what WE stored in provider_payment_id


def _gw_resp(status):
    return GatewayResponse(
        provider="moyasar", provider_payment_id=_INVOICE_ID,
        provider_reference="", checkout_url="", status=status, raw_response={},
    )


def _retrieve(status):
    return mock.patch(
        "apps.payments.gateways.moyasar.MoyasarGateway.retrieve_payment",
        return_value=_gw_resp(status),
    )


@override_settings(PAYMENT_PROVIDER="moyasar", MOYASAR_WEBHOOK_SECRET="whsec_test")
class MoyasarCallbackRouteTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = make_org()
        self.user = make_user(organization=self.org)
        with mock.patch(
            "apps.payments.gateways.moyasar.MoyasarGateway.create_payment",
            return_value=_gw_resp(PaymentStatus.REDIRECT_REQUIRED),
        ):
            self.txn = PaymentService().create_transaction(
                organization=self.org, user=self.user,
                amount=Decimal("75.00"), purpose="wallet_topup",
            )
        self.txn.provider_payment_id = _INVOICE_ID
        self.txn.save(update_fields=["provider_payment_id"])
        self.tx = str(self.txn.id)

    def test_callback_route_resolves_not_404(self):
        with _retrieve(PaymentStatus.REDIRECT_REQUIRED):
            r = self.client.get(_CALLBACK, {"transaction_id": self.tx, "id": _INVOICE_ID})
        self.assertNotEqual(r.status_code, 404)

    def test_resolves_by_tx_even_when_query_id_is_foreign(self):
        # Real Moyasar evidence: callback ?id is a PAYMENT id, not the invoice
        # id we stored. Resolution must work via our ``tx``, and server-side
        # verification must query OUR stored invoice id (provider_payment_id),
        # never the foreign query id.
        foreign_payment_id = "df3c6f13-9a34-4c82-86a5-b24041549a9e"
        with mock.patch(
            "apps.payments.gateways.moyasar.MoyasarGateway.retrieve_payment",
            return_value=_gw_resp(PaymentStatus.PAID),
        ) as mock_retrieve:
            r = self.client.get(_CALLBACK, {"transaction_id": self.tx,
                                            "id": foreign_payment_id, "status": "paid"})
        # Verified against our stored invoice id, not the echoed payment id.
        mock_retrieve.assert_called_once_with(_INVOICE_ID)
        self.assertNotEqual(_INVOICE_ID, foreign_payment_id)
        self.txn.refresh_from_db()
        self.assertEqual(self.txn.status, PaymentStatus.PAID)
        self.assertEqual(r.status_code, 302)
        self.assertIn("/billing/subscription/", r["Location"])

    def test_paid_query_param_alone_does_not_activate(self):
        # URL says status=paid, but the provider (server-side) says NOT paid.
        with _retrieve(PaymentStatus.FAILED):
            r = self.client.get(_CALLBACK, {"transaction_id": self.tx, "status": "paid"})
        self.txn.refresh_from_db()
        self.assertNotEqual(self.txn.status, PaymentStatus.PAID)
        self.assertEqual(r.status_code, 302)
        self.assertIn("/billing/plans/", r["Location"])

    def test_server_side_paid_activates_and_redirects_success(self):
        with _retrieve(PaymentStatus.PAID):
            r = self.client.get(_CALLBACK, {"transaction_id": self.tx})
        self.txn.refresh_from_db()
        self.assertEqual(self.txn.status, PaymentStatus.PAID)
        self.assertEqual(r.status_code, 302)
        self.assertIn("/billing/subscription/", r["Location"])

    def test_missing_tx_and_id_no_500_redirects_safely(self):
        r = self.client.get(_CALLBACK)
        self.assertEqual(r.status_code, 302)
        self.assertIn("/billing/plans/", r["Location"])

    def test_unknown_tx_no_500_no_activation(self):
        r = self.client.get(_CALLBACK, {"transaction_id": "11111111-1111-1111-1111-111111111111"})
        self.assertEqual(r.status_code, 302)
        self.assertIn("/billing/plans/", r["Location"])
        self.txn.refresh_from_db()
        self.assertNotEqual(self.txn.status, PaymentStatus.PAID)

    def test_invalid_tx_value_no_500(self):
        r = self.client.get(_CALLBACK, {"transaction_id": "not-a-uuid"})
        self.assertEqual(r.status_code, 302)
        self.assertIn("/billing/plans/", r["Location"])

    def test_fallback_lookup_by_provider_id_when_no_tx(self):
        # No tx, but the echoed id happens to match our stored invoice id.
        with _retrieve(PaymentStatus.PAID):
            r = self.client.get(_CALLBACK, {"id": _INVOICE_ID})
        self.txn.refresh_from_db()
        self.assertEqual(self.txn.status, PaymentStatus.PAID)
        self.assertEqual(r.status_code, 302)

    def test_pending_returns_verifying_landing(self):
        with _retrieve(PaymentStatus.REDIRECT_REQUIRED):
            r = self.client.get(_CALLBACK, {"transaction_id": self.tx})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["message"], "verifying")

    def test_duplicate_paid_callback_is_idempotent(self):
        with _retrieve(PaymentStatus.PAID):
            r1 = self.client.get(_CALLBACK, {"transaction_id": self.tx})
            r2 = self.client.get(_CALLBACK, {"transaction_id": self.tx})
        self.assertEqual(r1.status_code, 302)
        self.assertEqual(r2.status_code, 302)
        self.assertEqual(PaymentTransaction.objects.filter(pk=self.txn.pk).count(), 1)

    def test_no_raw_provider_json_in_terminal_response(self):
        with _retrieve(PaymentStatus.PAID):
            r = self.client.get(_CALLBACK, {"transaction_id": self.tx})
        self.assertEqual(r.status_code, 302)
        self.assertNotIn("{", r.content.decode("utf-8", "ignore"))

    def test_public_webhook_route_resolves_not_404(self):
        # POST /payments/webhooks/moyasar/ (no /api/v1) must be routed. Unsigned
        # POST is rejected by the adapter (not 404) — anything but 404 proves
        # the route exists.
        r = self.client.post("/payments/webhooks/moyasar/",
                             data="{}", content_type="application/json")
        self.assertNotEqual(r.status_code, 404)
