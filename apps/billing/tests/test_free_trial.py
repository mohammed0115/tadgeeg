"""Tests #6 and #7: free-trial creation and one-time-only enforcement."""
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.billing.choices import PlanCode, SubscriptionStatus
from apps.billing.models import OrganizationSubscription
from apps.billing.services.subscription_service import (
    FreeTrialAlreadyUsed,
    SubscriptionService,
)
from apps.billing.tests._factories import make_org


class FreeTrialTests(TestCase):
    def setUp(self):
        call_command("seed_billing_plans", stdout=StringIO())
        self.org = make_org()

    def test_create_free_trial_returns_trialing_subscription(self):
        sub = SubscriptionService().create_free_trial(self.org)
        self.assertEqual(sub.status, SubscriptionStatus.TRIALING)
        self.assertEqual(sub.plan.code, PlanCode.FREE_TRIAL)
        self.assertEqual(sub.invoice_limit, 20)
        self.assertEqual(sub.used_invoices, 0)
        self.assertEqual(sub.reserved_invoices, 0)
        self.assertIsNotNone(sub.starts_at)
        self.assertIsNotNone(sub.ends_at)
        self.assertGreater(sub.ends_at, sub.starts_at)

    def test_second_free_trial_is_refused(self):
        SubscriptionService().create_free_trial(self.org)
        with self.assertRaises(FreeTrialAlreadyUsed):
            SubscriptionService().create_free_trial(self.org)

        # And only one row exists — the failed call must not have created another.
        self.assertEqual(
            OrganizationSubscription.objects.filter(organization=self.org).count(),
            1,
        )

    def test_other_org_can_still_use_free_trial(self):
        SubscriptionService().create_free_trial(self.org)
        other = make_org("Other Org")
        sub = SubscriptionService().create_free_trial(other)
        self.assertEqual(sub.status, SubscriptionStatus.TRIALING)
