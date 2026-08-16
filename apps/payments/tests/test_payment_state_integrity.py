"""Regression tests for payment state, refund, and durable entitlement invariants."""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import Mock, patch

from django.test import TestCase

from apps.authentication.models import Organization, User
from apps.payments.choices import PaymentProvider, PaymentPurpose, PaymentStatus
from apps.payments.gateways.base import GatewayError, GatewayResponse
from apps.payments.models import PaymentRefund, PaymentTransaction
from apps.payments.services.payment_service import PaymentService, PaymentValidationError


class PaymentStateIntegrityTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(
            name="Payments Org", country=Organization.Country.SAUDI_ARABIA
        )
        self.user = User.objects.create_user(
            email="payment@example.com", password="StrongPass123!",
            full_name="Payment User", role=User.Role.ADMIN, organization=self.organization,
        )

    def _transaction(self, *, status=PaymentStatus.PENDING, amount=Decimal("100.00")):
        return PaymentTransaction.objects.create(
            organization=self.organization,
            user=self.user,
            provider=PaymentProvider.MOYASAR,
            purpose=PaymentPurpose.OTHER,
            amount=amount,
            currency="SAR",
            status=status,
        )

    @patch("apps.payments.services.payment_service._dispatch_business_action")
    def test_paid_event_cannot_resurrect_canceled_or_refunded_transaction(self, dispatch):
        service = PaymentService()
        for status in (PaymentStatus.CANCELED, PaymentStatus.REFUNDED, PaymentStatus.PARTIALLY_REFUNDED):
            txn = self._transaction(status=status)
            self.assertFalse(service.mark_paid(txn))
            txn.refresh_from_db()
            self.assertEqual(txn.status, status)
        dispatch.assert_not_called()

    @patch("apps.payments.services.payment_service._dispatch_business_action")
    def test_paid_event_creates_durable_pending_business_action(self, dispatch):
        txn = self._transaction()
        with self.captureOnCommitCallbacks(execute=True):
            self.assertTrue(PaymentService().mark_paid(txn))
        txn.refresh_from_db()
        self.assertEqual(txn.status, PaymentStatus.PAID)
        self.assertEqual(txn.business_action_status, "pending")
        dispatch.assert_called_once_with(str(txn.pk))

    @patch("apps.payments.services.payment_service.get_payment_gateway")
    def test_partial_refunds_are_capped_by_reserved_total(self, gateway_factory):
        txn = self._transaction(status=PaymentStatus.PAID)
        gateway = Mock()
        gateway.refund_payment.return_value = GatewayResponse(
            provider="moyasar", provider_payment_id="refund-one", provider_reference="",
            checkout_url="", status=PaymentStatus.REFUNDED,
        )
        gateway_factory.return_value = gateway
        service = PaymentService()

        service.refund(txn, amount=Decimal("60.00"))
        txn.refresh_from_db()
        self.assertEqual(txn.status, PaymentStatus.PARTIALLY_REFUNDED)
        self.assertEqual(txn.refunded_amount, Decimal("60.00"))
        self.assertEqual(PaymentRefund.objects.filter(status=PaymentRefund.Status.SUCCEEDED).count(), 1)

        with self.assertRaises(PaymentValidationError):
            service.refund(txn, amount=Decimal("50.00"))
        txn.refresh_from_db()
        self.assertEqual(txn.refunded_amount, Decimal("60.00"))

    @patch("apps.payments.services.payment_service.get_payment_gateway")
    def test_gateway_refund_failure_releases_reserved_amount(self, gateway_factory):
        txn = self._transaction(status=PaymentStatus.PAID)
        gateway = Mock()
        gateway.refund_payment.side_effect = GatewayError("provider unavailable")
        gateway_factory.return_value = gateway

        with self.assertRaises(GatewayError):
            PaymentService().refund(txn, amount=Decimal("25.00"))
        txn.refresh_from_db()
        self.assertEqual(txn.refunded_amount, Decimal("0.00"))
        self.assertEqual(txn.status, PaymentStatus.PAID)
        self.assertEqual(PaymentRefund.objects.get().status, PaymentRefund.Status.FAILED)
