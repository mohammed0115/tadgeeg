"""Service-level tests covering activate / mark_payment_failed /
expire_old_subscriptions."""
from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.billing.choices import PlanCode, SubscriptionStatus
from apps.billing.models import OrganizationSubscription, Plan
from apps.billing.services.subscription_service import (
    SubscriptionError,
    SubscriptionService,
)
from apps.billing.tests._factories import make_org


class SubscriptionLifecycleTests(TestCase):
    def setUp(self):
        call_command("seed_billing_plans", stdout=StringIO())
        self.org      = make_org()
        self.starter  = Plan.objects.get(code=PlanCode.STARTER)
        self.business = Plan.objects.get(code=PlanCode.BUSINESS)

    def test_create_pending_paid_subscription_freezes_invoice_limit(self):
        sub = SubscriptionService().create_pending_paid_subscription(self.org, self.starter)
        self.assertEqual(sub.status, SubscriptionStatus.PENDING_PAYMENT)
        self.assertEqual(sub.invoice_limit, 100)  # frozen from plan
        self.assertIsNone(sub.starts_at)
        self.assertIsNone(sub.ends_at)

    def test_create_pending_paid_rejects_free_plan(self):
        free = Plan.objects.get(code=PlanCode.FREE_TRIAL)
        with self.assertRaises(SubscriptionError):
            SubscriptionService().create_pending_paid_subscription(self.org, free)

    def test_activate_flips_status_and_starts_clock(self):
        sub = SubscriptionService().create_pending_paid_subscription(self.org, self.business)
        activated = SubscriptionService().activate_subscription(sub)
        self.assertEqual(activated.status, SubscriptionStatus.ACTIVE)
        self.assertIsNotNone(activated.starts_at)
        self.assertIsNotNone(activated.ends_at)
        # Activation snapshots whatever the plan currently offers.
        self.assertEqual(activated.invoice_limit, self.business.invoice_limit)

    def test_activate_is_idempotent(self):
        sub = SubscriptionService().create_pending_paid_subscription(self.org, self.starter)
        first  = SubscriptionService().activate_subscription(sub)
        starts = first.starts_at
        ends   = first.ends_at
        # Second call must not extend the period.
        second = SubscriptionService().activate_subscription(sub)
        self.assertEqual(second.starts_at, starts)
        self.assertEqual(second.ends_at,   ends)

    def test_plan_price_change_does_not_mutate_existing_subscription(self):
        sub = SubscriptionService().create_pending_paid_subscription(self.org, self.starter)
        SubscriptionService().activate_subscription(sub)

        # Plan owner raises the quota …
        self.starter.invoice_limit = 999
        self.starter.save(update_fields=["invoice_limit"])
        sub.refresh_from_db()
        # … the existing subscription is unaffected (snapshot).
        self.assertEqual(sub.invoice_limit, 100)

    def test_expire_old_subscriptions_flips_past_due_only(self):
        # One active+past-due, one active+in-window.
        past_due = SubscriptionService().create_pending_paid_subscription(self.org, self.starter)
        SubscriptionService().activate_subscription(past_due)
        OrganizationSubscription.objects.filter(pk=past_due.pk).update(
            ends_at=timezone.now() - timedelta(hours=1),
        )

        in_window_org = make_org("Other")
        in_window = SubscriptionService().create_pending_paid_subscription(in_window_org, self.business)
        SubscriptionService().activate_subscription(in_window)

        count = SubscriptionService().expire_old_subscriptions()
        self.assertEqual(count, 1)

        past_due.refresh_from_db()
        in_window.refresh_from_db()
        self.assertEqual(past_due.status,  SubscriptionStatus.EXPIRED)
        self.assertEqual(in_window.status, SubscriptionStatus.ACTIVE)
