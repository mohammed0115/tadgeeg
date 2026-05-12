from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.payments.choices import PaymentStatus
from apps.payments.gateways.base import GatewayResponse
from apps.payments.models import PaymentLog, PaymentTransaction
from apps.payments.services.payment_service import (
    PaymentService,
    PaymentValidationError,
)
from apps.payments.tests._factories import make_org, make_user


@override_settings(PAYMENT_PROVIDER="moyasar")
class PaymentServiceCreateTests(TestCase):
    def setUp(self):
        self.org = make_org()
        self.user = make_user(organization=self.org)

    def _fake_gateway_response(self, **overrides):
        defaults = dict(
            provider="moyasar",
            provider_payment_id="pay_test_123",
            provider_reference="ref_abc",
            checkout_url="https://checkout.moyasar.test/123",
            status=PaymentStatus.REDIRECT_REQUIRED,
            raw_response={"id": "pay_test_123", "status": "initiated"},
        )
        defaults.update(overrides)
        return GatewayResponse(**defaults)

    @mock.patch("apps.payments.gateways.moyasar.MoyasarGateway.create_payment")
    def test_create_transaction_persists_and_returns_checkout_url(self, mock_create):
        mock_create.return_value = self._fake_gateway_response()
        txn = PaymentService().create_transaction(
            organization=self.org, user=self.user,
            amount=Decimal("100.00"), purpose="subscription",
        )
        self.assertEqual(txn.status, PaymentStatus.REDIRECT_REQUIRED)
        self.assertEqual(txn.provider, "moyasar")
        self.assertEqual(txn.provider_payment_id, "pay_test_123")
        self.assertEqual(txn.checkout_url, "https://checkout.moyasar.test/123")
        # PaymentLog rows: created + gateway_created
        events = list(PaymentLog.objects.filter(transaction=txn).values_list("event_type", flat=True))
        self.assertIn("created", events)
        self.assertIn("gateway_created", events)

    @mock.patch("apps.payments.gateways.moyasar.MoyasarGateway.create_payment")
    def test_amount_must_be_positive(self, mock_create):
        with self.assertRaises(PaymentValidationError):
            PaymentService().create_transaction(
                organization=self.org, user=self.user,
                amount=Decimal("0"), purpose="invoice",
            )
        mock_create.assert_not_called()

    @mock.patch("apps.payments.gateways.moyasar.MoyasarGateway.create_payment")
    def test_idempotency_key_returns_existing_row(self, mock_create):
        mock_create.return_value = self._fake_gateway_response()
        txn_a = PaymentService().create_transaction(
            organization=self.org, user=self.user, amount=Decimal("10.00"),
            purpose="invoice", idempotency_key="key-1",
        )
        txn_b = PaymentService().create_transaction(
            organization=self.org, user=self.user, amount=Decimal("99.00"),
            purpose="invoice", idempotency_key="key-1",
        )
        self.assertEqual(txn_a.pk, txn_b.pk)
        # The second call must NOT have invoked the gateway again.
        self.assertEqual(mock_create.call_count, 1)


@override_settings(PAYMENT_PROVIDER="moyasar")
class CreatePaymentAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org_a = make_org("A")
        self.org_b = make_org("B")
        self.user_a = make_user(organization=self.org_a, email="a@example.com")
        self.user_b = make_user(organization=self.org_b, email="b@example.com")

    @mock.patch("apps.payments.gateways.moyasar.MoyasarGateway.create_payment")
    def test_user_cannot_choose_provider_from_request(self, mock_create):
        """Even if the client sends provider=tap, the active provider is whatever settings says."""
        mock_create.return_value = GatewayResponse(
            provider="moyasar", provider_payment_id="pay_xxx",
            provider_reference="", checkout_url="https://x",
            status=PaymentStatus.REDIRECT_REQUIRED, raw_response={},
        )
        self.client.force_authenticate(self.user_a)
        r = self.client.post(
            reverse("payments:create"),
            data={
                "amount": "50.00", "currency": "SAR", "purpose": "invoice",
                "provider": "tap",  # ← ignored; serializer doesn't declare this field
            },
            format="json",
        )
        self.assertEqual(r.status_code, 201, r.content)
        txn = PaymentTransaction.objects.get(pk=r.json()["transaction_id"])
        self.assertEqual(txn.provider, "moyasar")

    @mock.patch("apps.payments.gateways.moyasar.MoyasarGateway.create_payment")
    def test_user_cannot_see_other_organizations_transaction(self, mock_create):
        mock_create.return_value = GatewayResponse(
            provider="moyasar", provider_payment_id="pay_other",
            provider_reference="", checkout_url="https://x",
            status=PaymentStatus.REDIRECT_REQUIRED, raw_response={},
        )
        self.client.force_authenticate(self.user_b)
        r = self.client.post(
            reverse("payments:create"),
            data={"amount": "20.00", "currency": "SAR", "purpose": "invoice"},
            format="json",
        )
        txn_b = PaymentTransaction.objects.get(pk=r.json()["transaction_id"])

        # User A from a different org must NOT be able to see it.
        self.client.force_authenticate(self.user_a)
        r = self.client.get(reverse("payments:detail", kwargs={"pk": txn_b.pk}))
        self.assertEqual(r.status_code, 404)

    def test_zero_amount_is_rejected(self):
        self.client.force_authenticate(self.user_a)
        r = self.client.post(
            reverse("payments:create"),
            data={"amount": "0", "currency": "SAR", "purpose": "invoice"},
            format="json",
        )
        self.assertEqual(r.status_code, 400)
