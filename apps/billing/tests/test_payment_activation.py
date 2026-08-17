"""Stage 4 tests — Payment → Subscription Activation.

Covers the 10 cases from Documentation/payment/00.md §4:
  1. starter selection creates pending_payment
  2. business selection creates pending_payment
  3. professional selection creates pending_payment
  4. paid-plan selection creates PaymentTransaction
  5. webhook paid activates subscription
  6. repeated webhook does not activate twice
  7. payment failed flips subscription to payment_failed
  8. redirect callback does NOT activate
  9. (covered in test_registration_flow: active sub allows dashboard)
 10. (covered in test_registration_flow: pending_payment blocks API)

Plus a couple of structural tests (price-authority, idempotency).
"""
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.billing.choices import PlanCode, SubscriptionStatus
from apps.billing.models import OrganizationSubscription, Plan
from apps.billing.services.subscription_service import SubscriptionService
from apps.billing.tests._factories import make_org, make_user
from apps.billing.tests.test_registration_flow import _make_verified_user
from apps.payments.choices import PaymentStatus
from apps.payments.gateways.base import GatewayResponse
from apps.payments.models import PaymentLog, PaymentTransaction
from apps.payments.services.payment_service import PaymentService


def _fake_create_payment(checkout_url="https://checkout.test/x", provider_payment_id="pay_test"):
    return GatewayResponse(
        provider="moyasar",
        provider_payment_id=provider_payment_id,
        provider_reference="",
        checkout_url=checkout_url,
        status=PaymentStatus.REDIRECT_REQUIRED,
        raw_response={},
    )


@override_settings(PAYMENT_PROVIDER="moyasar")
class PaidPlanSelectionTests(TestCase):
    """Spec tests 1, 2, 3, 4."""

    def setUp(self):
        call_command("seed_billing_plans", stdout=StringIO())
        self.client = APIClient()
        self.org   = make_org()
        self.user  = _make_verified_user(organization=self.org)
        self.client.force_login(self.user)

    @mock.patch(
        "apps.payments.gateways.moyasar.MoyasarGateway.create_payment",
        return_value=_fake_create_payment(checkout_url="https://co/starter"),
    )
    def test_starter_selection_creates_pending_and_payment(self, _):
        r = self.client.post(reverse("billing:select-plan"),
                             data={"plan_code": "starter"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        sub = OrganizationSubscription.objects.get(organization=self.org)
        self.assertEqual(sub.status, SubscriptionStatus.PENDING_PAYMENT)
        self.assertEqual(sub.plan.code, PlanCode.STARTER)

        # PaymentTransaction must have been created and linked.
        txn = sub.payment_transaction
        self.assertEqual(txn.purpose, "subscription")
        self.assertEqual(txn.reference_type, "organization_subscription")
        self.assertEqual(txn.reference_id, str(sub.id))
        self.assertEqual(txn.amount, Decimal("149.00"))

    @mock.patch(
        "apps.payments.gateways.moyasar.MoyasarGateway.create_payment",
        return_value=_fake_create_payment(),
    )
    def test_business_selection_creates_pending_and_payment(self, _):
        r = self.client.post(reverse("billing:select-plan"),
                             data={"plan_code": "business"}, format="json")
        self.assertEqual(r.status_code, 201)
        sub = OrganizationSubscription.objects.get(organization=self.org)
        self.assertEqual(sub.status, SubscriptionStatus.PENDING_PAYMENT)
        self.assertEqual(sub.plan.code, PlanCode.BUSINESS)
        self.assertEqual(sub.invoice_limit, 2000)

    @mock.patch(
        "apps.payments.gateways.moyasar.MoyasarGateway.create_payment",
        return_value=_fake_create_payment(),
    )
    def test_professional_selection_creates_pending_and_payment(self, _):
        r = self.client.post(reverse("billing:select-plan"),
                             data={"plan_code": "professional"}, format="json")
        self.assertEqual(r.status_code, 201)
        sub = OrganizationSubscription.objects.get(organization=self.org)
        self.assertEqual(sub.status, SubscriptionStatus.PENDING_PAYMENT)
        self.assertEqual(sub.invoice_limit, 5000)
        txn = sub.payment_transaction
        self.assertEqual(txn.amount, Decimal("999.00"))


@override_settings(PAYMENT_PROVIDER="moyasar")
class WebhookActivatesSubscriptionTests(TestCase):
    """Spec tests 5 and 6 — paid webhook activates; repeats are no-ops."""

    def setUp(self):
        call_command("seed_billing_plans", stdout=StringIO())
        self.client = APIClient()
        self.org   = make_org()
        self.user  = _make_verified_user(organization=self.org)

        # Spin up the subscription + payment exactly as SelectPlanView would.
        plan = Plan.objects.get(code=PlanCode.STARTER)
        self.sub = SubscriptionService().create_pending_paid_subscription(self.org, plan)
        with mock.patch(
            "apps.payments.gateways.moyasar.MoyasarGateway.create_payment",
            return_value=_fake_create_payment(provider_payment_id="pay_act_1"),
        ):
            self.txn = PaymentService().create_transaction(
                organization=self.org, user=self.user,
                amount=Decimal("149.00"), currency="SAR",
                purpose="subscription",
                reference_type="organization_subscription",
                reference_id=str(self.sub.id),
            )
        self.sub.payment_transaction = self.txn
        self.sub.save(update_fields=["payment_transaction"])

    def test_paid_webhook_activates_the_subscription(self):
        with self.captureOnCommitCallbacks(execute=True):
            PaymentService().mark_paid(self.txn, payload={"id": "pay_act_1", "status": "paid"})
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, SubscriptionStatus.ACTIVE)
        self.assertIsNotNone(self.sub.starts_at)
        self.assertIsNotNone(self.sub.ends_at)
        # invoice_limit snapshotted from plan
        self.assertEqual(self.sub.invoice_limit, 100)

    def test_repeated_paid_webhook_does_not_reactivate(self):
        with self.captureOnCommitCallbacks(execute=True):
            PaymentService().mark_paid(self.txn, payload={})
        self.sub.refresh_from_db()
        starts_first = self.sub.starts_at
        ends_first   = self.sub.ends_at

        # Second delivery — must NOT reset the clock.
        PaymentService().mark_paid(self.txn, payload={})
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.starts_at, starts_first)
        self.assertEqual(self.sub.ends_at, ends_first)


@override_settings(PAYMENT_PROVIDER="moyasar")
class PaymentFailureFlipsSubscriptionTests(TestCase):
    """Spec test 7."""

    def setUp(self):
        call_command("seed_billing_plans", stdout=StringIO())
        self.org  = make_org()
        self.user = _make_verified_user(organization=self.org)
        plan = Plan.objects.get(code=PlanCode.STARTER)
        self.sub = SubscriptionService().create_pending_paid_subscription(self.org, plan)
        with mock.patch(
            "apps.payments.gateways.moyasar.MoyasarGateway.create_payment",
            return_value=_fake_create_payment(provider_payment_id="pay_fail_1"),
        ):
            self.txn = PaymentService().create_transaction(
                organization=self.org, user=self.user,
                amount=Decimal("149.00"), currency="SAR",
                purpose="subscription",
                reference_type="organization_subscription",
                reference_id=str(self.sub.id),
            )

    def test_failed_payment_flips_subscription_to_payment_failed(self):
        PaymentService().mark_failed(
            self.txn, reason="card declined", payload={},
        )
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, SubscriptionStatus.PAYMENT_FAILED)


@override_settings(PAYMENT_PROVIDER="moyasar")
class CallbackDoesNotActivateTests(TestCase):
    """Spec test 8 — the user landing back via the callback URL must NOT
    flip the subscription to ACTIVE on its own. Webhook is authoritative."""

    def setUp(self):
        call_command("seed_billing_plans", stdout=StringIO())
        self.client = APIClient()
        self.org  = make_org()
        self.user = _make_verified_user(organization=self.org)
        plan = Plan.objects.get(code=PlanCode.STARTER)
        self.sub = SubscriptionService().create_pending_paid_subscription(self.org, plan)
        with mock.patch(
            "apps.payments.gateways.moyasar.MoyasarGateway.create_payment",
            return_value=_fake_create_payment(provider_payment_id="pay_cb_1"),
        ):
            self.txn = PaymentService().create_transaction(
                organization=self.org, user=self.user,
                amount=Decimal("149.00"), currency="SAR",
                purpose="subscription",
                reference_type="organization_subscription",
                reference_id=str(self.sub.id),
            )

    def test_callback_does_not_activate_subscription(self):
        # The callback view kicks off a sync. If the provider says
        # the payment is still mid-flow, the subscription must stay
        # PENDING_PAYMENT.
        with mock.patch(
            "apps.payments.gateways.moyasar.MoyasarGateway.retrieve_payment",
            return_value=GatewayResponse(
                provider="moyasar", provider_payment_id="pay_cb_1",
                provider_reference="", checkout_url="",
                status=PaymentStatus.REDIRECT_REQUIRED, raw_response={},
            ),
        ):
            r = self.client.get(
                "/api/v1/payments/callback/moyasar/",
                {"transaction_id": str(self.txn.id)},
            )
        self.sub.refresh_from_db()
        self.assertNotEqual(self.sub.status, SubscriptionStatus.ACTIVE)


@override_settings(PAYMENT_PROVIDER="moyasar")
class SelectPlanIdempotencyTests(TestCase):
    """Defensive coverage of the 15-minute pending-reuse window."""

    def setUp(self):
        call_command("seed_billing_plans", stdout=StringIO())
        self.client = APIClient()
        self.org   = make_org()
        self.user  = _make_verified_user(organization=self.org)
        self.client.force_login(self.user)

    @mock.patch(
        "apps.payments.gateways.moyasar.MoyasarGateway.create_payment",
        return_value=_fake_create_payment(checkout_url="https://co/v1"),
    )
    def test_repeated_select_plan_returns_existing_pending(self, mock_create):
        r1 = self.client.post(reverse("billing:select-plan"),
                              data={"plan_code": "starter"}, format="json")
        r2 = self.client.post(reverse("billing:select-plan"),
                              data={"plan_code": "starter"}, format="json")
        self.assertEqual(r1.status_code, 201)
        self.assertEqual(r2.status_code, 200)  # 200, not 201 — reused
        # Same subscription, same payment, gateway called exactly once.
        subs = OrganizationSubscription.objects.filter(organization=self.org)
        self.assertEqual(subs.count(), 1)
        self.assertEqual(mock_create.call_count, 1)


@override_settings(PAYMENT_PROVIDER="moyasar")
class PriceAuthorityOnSubscriptionTests(TestCase):
    """The subscription resolver MUST override any client-supplied amount."""

    def setUp(self):
        call_command("seed_billing_plans", stdout=StringIO())
        self.org  = make_org()
        self.user = _make_verified_user(organization=self.org)
        plan = Plan.objects.get(code=PlanCode.PROFESSIONAL)
        self.sub = SubscriptionService().create_pending_paid_subscription(self.org, plan)

    @mock.patch("apps.payments.gateways.moyasar.MoyasarGateway.create_payment")
    def test_client_underpay_attempt_is_rejected(self, mock_create):
        from apps.payments.services.payment_service import (
            PaymentService,
            PaymentValidationError,
        )
        with self.assertRaises(PaymentValidationError):
            PaymentService().create_transaction(
                organization=self.org, user=self.user,
                amount=Decimal("1.00"),  # ← real price is 890
                currency="SAR",
                purpose="subscription",
                reference_type="organization_subscription",
                reference_id=str(self.sub.id),
            )
        mock_create.assert_not_called()
