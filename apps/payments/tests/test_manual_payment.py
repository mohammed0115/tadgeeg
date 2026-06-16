"""Tests for the official manual-payment service + provider (CRM-1F-3B-1)."""
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.test import TestCase

from apps.billing.choices import PlanCode, SubscriptionStatus
from apps.billing.models import OrganizationSubscription, Plan
from apps.payments.choices import PaymentProvider, PaymentStatus
from apps.payments.gateways.factory import (
    SUPPORTED_PROVIDERS,
    get_payment_gateway,
)
from apps.payments.models import PaymentLog, PaymentTransaction
from apps.payments.services.payment_service import (
    PaymentService,
    PaymentValidationError,
)
from apps.payments.tests._factories import make_org, make_user


# ── Provider tests ────────────────────────────────────────────────────────────
class ManualProviderTests(TestCase):
    def test_manual_provider_exists(self):
        self.assertEqual(PaymentProvider.MANUAL.value, "manual")

    def test_manual_has_no_gateway(self):
        self.assertNotIn("manual", SUPPORTED_PROVIDERS)
        with self.assertRaises(ImproperlyConfigured):
            get_payment_gateway("manual")

    def test_hosted_providers_still_supported(self):
        for p in ("moyasar", "tap", "telr"):
            self.assertIn(p, SUPPORTED_PROVIDERS)
        # a known provider still builds a gateway
        self.assertIsNotNone(get_payment_gateway("moyasar"))


# ── Service tests ─────────────────────────────────────────────────────────────
class CreateManualPaymentTests(TestCase):
    def setUp(self):
        call_command("seed_billing_plans", stdout=StringIO())
        self.org = make_org()
        self.user = make_user(organization=self.org)
        self.svc = PaymentService()
        self.plan = Plan.objects.get(code=PlanCode.BUSINESS)  # price 500-ish

    def _pending_sub(self, org=None):
        return OrganizationSubscription.objects.create(
            organization=org or self.org, plan=self.plan,
            status=SubscriptionStatus.PENDING_PAYMENT,
            invoice_limit=self.plan.invoice_limit,
        )

    def _create(self, sub=None, **over):
        sub = sub or self._pending_sub()
        kwargs = dict(
            organization=self.org, user=self.user, subscription=sub,
            amount=self.plan.price, currency=self.plan.currency,
            reference="TT-12345", reason="bank transfer",
        )
        kwargs.update(over)
        return self.svc.create_manual_payment(**kwargs)

    # happy path
    def test_creates_pending_manual_payment(self):
        sub = self._pending_sub()
        txn = self._create(sub)
        self.assertEqual(txn.provider, "manual")
        self.assertEqual(txn.status, PaymentStatus.PENDING)
        self.assertEqual(txn.purpose, "subscription")
        self.assertEqual(txn.reference_type, "organization_subscription")
        self.assertEqual(txn.reference_id, str(sub.id))
        self.assertEqual(txn.amount, Decimal(self.plan.price).quantize(Decimal("0.01")))
        self.assertEqual(txn.provider_reference, "TT-12345")
        self.assertEqual(txn.idempotency_key, f"manual-sub-{sub.id}")

    def test_no_secrets_or_gateway_fields_populated(self):
        txn = self._create()
        self.assertEqual(txn.raw_request, {})
        self.assertEqual(txn.raw_response, {})
        self.assertEqual(txn.raw_webhook, {})
        self.assertEqual(txn.checkout_url, "")
        self.assertEqual(txn.provider_payment_id, "")

    def test_payment_log_written(self):
        txn = self._create()
        log = PaymentLog.objects.get(transaction=txn, event_type="manual_created")
        self.assertEqual(log.payload["reference"], "TT-12345")
        self.assertEqual(log.payload["source"], "crm_manual")

    def test_subscription_not_activated_and_not_paid(self):
        sub = self._pending_sub()
        txn = self._create(sub)
        sub.refresh_from_db()
        self.assertEqual(sub.status, SubscriptionStatus.PENDING_PAYMENT)
        self.assertEqual(txn.status, PaymentStatus.PENDING)

    def test_no_gateway_called(self):
        sub = self._pending_sub()
        with mock.patch(
            "apps.payments.services.payment_service.get_payment_gateway"
        ) as gw:
            self._create(sub)
        gw.assert_not_called()

    def test_no_signal_emitted(self):
        sub = self._pending_sub()
        with mock.patch("apps.payments.signals.payment_paid.send") as sig:
            self._create(sub)
        sig.assert_not_called()

    # validation
    def test_wrong_amount_rejected(self):
        with self.assertRaises(PaymentValidationError):
            self._create(amount=Decimal("1.00"))

    def test_empty_reference_rejected(self):
        with self.assertRaises(PaymentValidationError):
            self._create(reference="   ")

    def test_wrong_currency_rejected(self):
        with self.assertRaises(PaymentValidationError):
            self._create(currency="USD")

    def test_wrong_organization_rejected(self):
        other = make_org(name="Other")
        sub = self._pending_sub()
        with self.assertRaises(PaymentValidationError):
            self.svc.create_manual_payment(
                organization=other, user=self.user, subscription=sub,
                amount=self.plan.price, currency=self.plan.currency,
                reference="X", reason="r",
            )

    def test_active_subscription_rejected(self):
        sub = self._pending_sub()
        sub.status = SubscriptionStatus.ACTIVE
        sub.save(update_fields=["status"])
        with self.assertRaises(PaymentValidationError):
            self._create(sub)

    def test_trialing_subscription_rejected(self):
        sub = self._pending_sub()
        sub.status = SubscriptionStatus.TRIALING
        sub.save(update_fields=["status"])
        with self.assertRaises(PaymentValidationError):
            self._create(sub)

    def test_expired_canceled_failed_rejected(self):
        for status in (
            SubscriptionStatus.EXPIRED,
            SubscriptionStatus.CANCELED,
            SubscriptionStatus.PAYMENT_FAILED,
        ):
            sub = self._pending_sub()
            sub.status = status
            sub.save(update_fields=["status"])
            with self.assertRaises(PaymentValidationError):
                self._create(sub)

    def test_org_with_other_usable_subscription_rejected(self):
        # an active subscription already exists for the org
        OrganizationSubscription.objects.create(
            organization=self.org, plan=self.plan,
            status=SubscriptionStatus.ACTIVE, invoice_limit=self.plan.invoice_limit,
        )
        pending = self._pending_sub()
        with self.assertRaises(PaymentValidationError):
            self._create(pending)

    # idempotency
    def test_duplicate_manual_payment_rejected(self):
        sub = self._pending_sub()
        self._create(sub)
        before = PaymentTransaction.objects.count()
        with self.assertRaises(PaymentValidationError):
            self._create(sub)
        self.assertEqual(PaymentTransaction.objects.count(), before)

    def test_idempotency_key_is_per_subscription(self):
        sub = self._pending_sub()
        txn = self._create(sub)
        self.assertEqual(txn.idempotency_key, f"manual-sub-{sub.id}")
