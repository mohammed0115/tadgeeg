"""Tests for the post-#1-#10 hardening:
   - server-side price authority (#7)
   - encryption (#1)
   - refund endpoint (#6)
   - DLQ (#8)
   - reconcile task (#5)
"""
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.payments.choices import PaymentStatus
from apps.payments.encryption import EncryptedTextField
from apps.payments.gateways.base import GatewayError, GatewayResponse
from apps.payments.models import (
    FailedWebhookEvent,
    PaymentLog,
    PaymentTransaction,
)
from apps.payments.services.payment_service import (
    PaymentService,
    PaymentValidationError,
)
from apps.payments.tasks import reconcile_stale_payments
from apps.payments.tests._factories import make_org, make_user


# ─── #7 — Server-side price authority ───────────────────────────────────────
@override_settings(PAYMENT_PROVIDER="moyasar")
class PriceAuthorityTests(TestCase):
    def setUp(self):
        self.org  = make_org()
        self.user = make_user(organization=self.org)

    @mock.patch("apps.payments.gateways.moyasar.MoyasarGateway.create_payment")
    def test_subscription_with_unresolvable_reference_is_refused(self, mock_create):
        """Stage 4 registered a resolver for purpose=subscription. The
        resolver requires a valid OrganizationSubscription UUID; anything
        else (junk string, wrong tenant, deleted row) must surface as a
        400-class PaymentValidationError BEFORE the gateway is called."""
        with self.assertRaises(PaymentValidationError):
            PaymentService().create_transaction(
                organization=self.org, user=self.user,
                amount=Decimal("10.00"), purpose="subscription",
                reference_id="some-plan-id",  # not a valid UUID
            )
        mock_create.assert_not_called()

    @mock.patch("apps.payments.gateways.moyasar.MoyasarGateway.create_payment")
    def test_invoice_amount_mismatch_is_rejected(self, mock_create):
        """If client requests less than the invoice's authoritative total,
        the request must be rejected — not silently overwritten."""
        from apps.invoices.models import Invoice
        inv = Invoice.objects.create(
            organization=self.org,
            invoice_number="INV-PAY-TEST",
            vendor_name="Test Vendor",
            total_amount=Decimal("500.00"),
            currency="SAR",
        )
        with self.assertRaises(PaymentValidationError) as cm:
            PaymentService().create_transaction(
                organization=self.org, user=self.user,
                amount=Decimal("1.00"),  # ← attacker trying to underpay
                purpose="invoice", reference_id=str(inv.pk),
            )
        self.assertIn("mismatch", str(cm.exception).lower())
        mock_create.assert_not_called()

    @mock.patch("apps.payments.gateways.moyasar.MoyasarGateway.create_payment")
    def test_invoice_correct_amount_succeeds(self, mock_create):
        from apps.invoices.models import Invoice
        inv = Invoice.objects.create(
            organization=self.org,
            invoice_number="INV-OK",
            vendor_name="V",
            total_amount=Decimal("250.00"),
            currency="SAR",
        )
        mock_create.return_value = GatewayResponse(
            provider="moyasar", provider_payment_id="pay_x",
            provider_reference="", checkout_url="https://x",
            status=PaymentStatus.REDIRECT_REQUIRED, raw_response={},
        )
        txn = PaymentService().create_transaction(
            organization=self.org, user=self.user,
            amount=Decimal("250.00"),
            purpose="invoice", reference_id=str(inv.pk),
        )
        self.assertEqual(txn.amount, Decimal("250.00"))

    @mock.patch("apps.payments.gateways.moyasar.MoyasarGateway.create_payment")
    def test_wallet_topup_accepts_client_amount(self, mock_create):
        """Unguarded purposes (wallet top-up) trust the request amount."""
        mock_create.return_value = GatewayResponse(
            provider="moyasar", provider_payment_id="pay_w",
            provider_reference="", checkout_url="https://x",
            status=PaymentStatus.REDIRECT_REQUIRED, raw_response={},
        )
        txn = PaymentService().create_transaction(
            organization=self.org, user=self.user,
            amount=Decimal("50.00"), purpose="wallet_topup",
        )
        self.assertEqual(txn.amount, Decimal("50.00"))


# ─── #1 — Encryption at rest ────────────────────────────────────────────────
class EncryptedTextFieldUnitTests(TestCase):
    """The concrete user of EncryptedTextField (PaymentProviderConfig)
    was removed in QA-cleanup M-3, but the field itself stays — to be
    re-used when per-tenant overrides land. These tests exercise the
    field's encrypt/decrypt + idempotency contracts directly so
    regressions get caught even with no model wired in."""

    def _field(self):
        from apps.payments.encryption import EncryptedTextField
        return EncryptedTextField()

    def test_plaintext_round_trips_through_prep_and_decrypt(self):
        field = self._field()
        plain = "sk_test_super_secret"
        token = field.get_prep_value(plain)
        self.assertTrue(token.startswith("gAAAA"), f"expected Fernet token, got {token[:20]!r}")
        self.assertNotEqual(token, plain)
        self.assertEqual(field._decrypt(token), plain)

    def test_empty_values_pass_through(self):
        field = self._field()
        self.assertEqual(field.get_prep_value(""),   "")
        self.assertEqual(field.get_prep_value(None), None)
        self.assertEqual(field._decrypt(""),   "")
        self.assertEqual(field._decrypt(None), None)

    def test_save_is_idempotent_for_already_encrypted_input(self):
        field = self._field()
        token_once  = field.get_prep_value("hello")
        # Storing the same token again must not double-encrypt.
        token_twice = field.get_prep_value(token_once)
        self.assertEqual(token_once, token_twice)
        self.assertEqual(field._decrypt(token_twice), "hello")


# ─── #6 — Refund endpoint ───────────────────────────────────────────────────
@override_settings(PAYMENT_PROVIDER="moyasar")
class RefundEndpointTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        self.client = APIClient()
        self.org = make_org()
        # Maker: initiated the original payment.
        self.admin = User.objects.create_user(
            email="admin@example.com", password="StrongPass123!",
            full_name="Admin", role=User.Role.ADMIN, organization=self.org,
        )
        # Checker: refunds. Segregation of Duties (F-1) requires a different
        # admin to approve the refund — the user who created the payment
        # cannot also approve its reversal.
        self.approver = User.objects.create_user(
            email="approver@example.com", password="StrongPass123!",
            full_name="Approver", role=User.Role.ADMIN, organization=self.org,
        )
        self.member = make_user(organization=self.org, email="member@example.com")

        with mock.patch(
            "apps.payments.gateways.moyasar.MoyasarGateway.create_payment",
            return_value=GatewayResponse(
                provider="moyasar", provider_payment_id="pay_r",
                provider_reference="", checkout_url="https://x",
                status=PaymentStatus.PAID, raw_response={},
            ),
        ):
            self.txn = PaymentService().create_transaction(
                organization=self.org, user=self.admin,
                amount=Decimal("100.00"), purpose="wallet_topup",
            )
        # Force it to PAID since the mock returned that status.
        self.txn.refresh_from_db()
        self.txn.status = PaymentStatus.PAID
        self.txn.paid_at = timezone.now()
        self.txn.save(update_fields=["status", "paid_at"])

    @mock.patch("apps.payments.gateways.moyasar.MoyasarGateway.refund_payment")
    def test_admin_can_refund(self, mock_refund):
        mock_refund.return_value = GatewayResponse(
            provider="moyasar", provider_payment_id="pay_r",
            provider_reference="", checkout_url="",
            status=PaymentStatus.REFUNDED, raw_response={"refund_id": "r_1"},
        )
        self.client.force_authenticate(self.approver)
        r = self.client.post(reverse("payments:refund", kwargs={"pk": self.txn.pk}))
        self.assertEqual(r.status_code, 200, r.content)
        self.txn.refresh_from_db()
        self.assertEqual(self.txn.status, PaymentStatus.REFUNDED)

    @mock.patch("apps.payments.gateways.moyasar.MoyasarGateway.refund_payment")
    def test_non_admin_cannot_refund(self, mock_refund):
        self.client.force_authenticate(self.member)
        r = self.client.post(reverse("payments:refund", kwargs={"pk": self.txn.pk}))
        self.assertEqual(r.status_code, 403)
        mock_refund.assert_not_called()

    def test_cannot_refund_an_unpaid_transaction(self):
        self.txn.status = PaymentStatus.PENDING
        self.txn.save(update_fields=["status"])
        self.client.force_authenticate(self.approver)
        r = self.client.post(reverse("payments:refund", kwargs={"pk": self.txn.pk}))
        self.assertEqual(r.status_code, 400)

    @mock.patch("apps.payments.gateways.moyasar.MoyasarGateway.refund_payment")
    def test_maker_cannot_also_refund_sod(self, mock_refund):
        """F-1: the admin who initiated the payment may not approve its refund."""
        self.client.force_authenticate(self.admin)
        r = self.client.post(reverse("payments:refund", kwargs={"pk": self.txn.pk}))
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json().get("code"), "sod_violation")
        mock_refund.assert_not_called()


# ─── #8 — Webhook DLQ ───────────────────────────────────────────────────────
import hashlib, hmac, json


_SECRET = "dlq-test-secret"


@override_settings(PAYMENT_PROVIDER="moyasar", MOYASAR_WEBHOOK_SECRET=_SECRET)
class WebhookDLQTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = make_org()
        self.user = make_user(organization=self.org)

    def _post(self, body, *, signature=None):
        raw = json.dumps(body).encode("utf-8")
        kwargs = {"data": raw, "content_type": "application/json"}
        if signature is not None:
            kwargs["HTTP_X_MOYASAR_SIGNATURE"] = signature
        return self.client.post(reverse("payments:webhook-moyasar"), **kwargs)

    def test_bad_signature_lands_in_dlq(self):
        body = {"data": {"id": "any", "status": "paid"}}
        self.assertEqual(FailedWebhookEvent.objects.count(), 0)
        self._post(body, signature="sha256=deadbeef")
        self.assertEqual(FailedWebhookEvent.objects.count(), 1)
        evt = FailedWebhookEvent.objects.first()
        self.assertEqual(evt.reason, FailedWebhookEvent.Reason.UNVERIFIED)
        self.assertFalse(evt.replayed)

    def test_unknown_txn_lands_in_dlq(self):
        body = {"data": {"id": "pay_does_not_exist", "status": "paid"}}
        raw = json.dumps(body).encode("utf-8")
        sig = "sha256=" + hmac.new(_SECRET.encode(), raw, hashlib.sha256).hexdigest()
        r = self._post(body, signature=sig)
        self.assertEqual(r.status_code, 200)
        evts = FailedWebhookEvent.objects.filter(reason=FailedWebhookEvent.Reason.UNKNOWN_TXN)
        self.assertEqual(evts.count(), 1)


# ─── #5 — Reconciliation task ────────────────────────────────────────────────
@override_settings(PAYMENT_PROVIDER="moyasar")
class ReconcileStalePaymentsTests(TestCase):
    def setUp(self):
        self.org = make_org()
        self.user = make_user(organization=self.org)

    def _make_stale_txn(self, *, status=PaymentStatus.REDIRECT_REQUIRED, age_minutes=60):
        from datetime import timedelta
        txn = PaymentTransaction.objects.create(
            organization=self.org, user=self.user,
            provider="moyasar", purpose="wallet_topup",
            amount=Decimal("10.00"), currency="SAR",
            status=status, provider_payment_id="pay_stale",
        )
        # Force timestamps backwards.
        old = timezone.now() - timedelta(minutes=age_minutes)
        PaymentTransaction.objects.filter(pk=txn.pk).update(updated_at=old, created_at=old)
        txn.refresh_from_db()
        return txn

    @mock.patch("apps.payments.gateways.moyasar.MoyasarGateway.retrieve_payment")
    def test_stale_paid_at_provider_is_reconciled_to_paid(self, mock_retrieve):
        txn = self._make_stale_txn()
        mock_retrieve.return_value = GatewayResponse(
            provider="moyasar", provider_payment_id="pay_stale",
            provider_reference="", checkout_url="",
            status=PaymentStatus.PAID, raw_response={"status": "paid"},
        )
        counts = reconcile_stale_payments(grace_minutes=30)
        txn.refresh_from_db()
        self.assertEqual(txn.status, PaymentStatus.PAID)
        self.assertEqual(counts["checked"], 1)
        self.assertEqual(counts["transitioned"], 1)

    @mock.patch("apps.payments.gateways.moyasar.MoyasarGateway.retrieve_payment")
    def test_very_old_transactions_are_expired(self, mock_retrieve):
        txn = self._make_stale_txn(age_minutes=60 * 36)  # 36h old
        counts = reconcile_stale_payments(grace_minutes=30)
        txn.refresh_from_db()
        self.assertEqual(txn.status, PaymentStatus.EXPIRED)
        self.assertEqual(counts["expired"], 1)
        mock_retrieve.assert_not_called()

    @mock.patch("apps.payments.gateways.moyasar.MoyasarGateway.retrieve_payment")
    def test_fresh_transactions_are_skipped(self, mock_retrieve):
        # 5 min old — within grace window
        self._make_stale_txn(age_minutes=5)
        counts = reconcile_stale_payments(grace_minutes=30)
        self.assertEqual(counts["checked"], 0)
        mock_retrieve.assert_not_called()
