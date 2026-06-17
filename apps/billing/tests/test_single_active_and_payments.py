"""SUBSCRIPTION-ACTIVE-STATE-UX-A — one usable subscription per org, plus the
customer payment-history page. No real Moyasar calls; HTML rendered in English.
"""
from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.billing.choices import PlanCode, SubscriptionStatus, USABLE_STATUSES
from apps.billing.models import OrganizationSubscription, Plan
from apps.billing.services.quota_service import QuotaService
from apps.billing.services.subscription_service import SubscriptionService
from apps.billing.tests._factories import make_org, make_user


def _usable_count(org):
    return OrganizationSubscription.objects.filter(
        organization=org, status__in=tuple(USABLE_STATUSES)
    ).count()


class SingleActiveSubscriptionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_billing_plans", stdout=StringIO())

    def setUp(self):
        self.org = make_org()
        self.svc = SubscriptionService()
        self.starter = Plan.objects.get(code=PlanCode.STARTER)
        self.business = Plan.objects.get(code=PlanCode.BUSINESS)

    def _activate(self, plan):
        sub = self.svc.create_pending_paid_subscription(self.org, plan)
        return self.svc.activate_subscription(sub)

    def test_first_activation_yields_one_active(self):
        self._activate(self.starter)
        self.assertEqual(_usable_count(self.org), 1)

    def test_idempotent_reactivation_keeps_single_active(self):
        sub = self._activate(self.starter)
        again = self.svc.activate_subscription(sub)  # duplicate webhook/callback
        self.assertEqual(again.pk, sub.pk)
        self.assertEqual(_usable_count(self.org), 1)

    def test_new_plan_supersedes_old_active(self):
        old = self._activate(self.starter)
        new = self._activate(self.business)
        old.refresh_from_db()
        self.assertEqual(_usable_count(self.org), 1)
        self.assertEqual(old.status, SubscriptionStatus.CANCELED)
        self.assertEqual(new.status, SubscriptionStatus.ACTIVE)

    def test_renewal_same_plan_does_not_create_second_active(self):
        first = self._activate(self.starter)
        second = self._activate(self.starter)
        first.refresh_from_db()
        self.assertEqual(_usable_count(self.org), 1)
        self.assertEqual(first.status, SubscriptionStatus.CANCELED)
        self.assertEqual(second.status, SubscriptionStatus.ACTIVE)

    def test_activate_after_payment_is_idempotent(self):
        from apps.payments.choices import PaymentStatus
        from apps.payments.models import PaymentTransaction
        sub = self.svc.create_pending_paid_subscription(self.org, self.starter)
        txn = PaymentTransaction.objects.create(
            organization=self.org, provider="moyasar", purpose="subscription",
            reference_type="organization_subscription", reference_id=str(sub.id),
            amount=Decimal("75.00"), currency="SAR", status=PaymentStatus.PAID,
        )
        # Webhook then callback (same paid payment) → still a single active.
        self.svc.activate_after_payment(txn)
        self.svc.activate_after_payment(txn)
        self.assertEqual(_usable_count(self.org), 1)

    def test_active_selector_returns_the_single_active(self):
        self._activate(self.starter)
        active = self._activate(self.business)
        got = QuotaService().get_active_subscription(self.org)
        self.assertEqual(got.pk, active.pk)


class SubscriptionPageButtonTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_billing_plans", stdout=StringIO())

    def setUp(self):
        self.org = make_org()
        self.user = make_user(organization=self.org)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.svc = SubscriptionService()

    def _get(self):
        return self.client.get("/billing/subscription/",
                               HTTP_ACCEPT="text/html,*/*", HTTP_ACCEPT_LANGUAGE="en")

    def _activate(self, code):
        plan = Plan.objects.get(code=code)
        sub = self.svc.create_pending_paid_subscription(self.org, plan)
        return self.svc.activate_subscription(sub)

    def test_fresh_active_hides_renew(self):
        self._activate(PlanCode.STARTER)  # 30-day period, far from expiry
        r = self._get()
        self.assertNotContains(r, ">Renew<")

    def test_near_expiry_shows_renew(self):
        sub = self._activate(PlanCode.STARTER)
        sub.ends_at = timezone.now() + timedelta(days=3)
        sub.save(update_fields=["ends_at"])
        r = self._get()
        self.assertContains(r, ">Renew<")

    def test_upgrade_shown_when_higher_plan_exists(self):
        self._activate(PlanCode.STARTER)  # cheaper plan; Business/Professional higher
        r = self._get()
        self.assertContains(r, "Upgrade plan")

    def test_upgrade_hidden_on_top_plan(self):
        self._activate(PlanCode.PROFESSIONAL)  # most expensive
        r = self._get()
        self.assertNotContains(r, "Upgrade plan")

    def test_subscription_page_links_to_payment_history(self):
        self._activate(PlanCode.STARTER)
        r = self._get()
        self.assertContains(r, "/billing/payments/")


class PaymentHistoryPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_billing_plans", stdout=StringIO())

    def setUp(self):
        self.org = make_org("Org A")
        self.other = make_org("Org B")
        self.user = make_user(organization=self.org)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _txn(self, org, **kw):
        from apps.payments.choices import PaymentStatus
        from apps.payments.models import PaymentTransaction
        defaults = dict(
            organization=org, provider="moyasar", purpose="subscription",
            amount=Decimal("75.00"), currency="SAR", status=PaymentStatus.PAID,
            provider_reference="ref_safe_123",
            raw_response={"secret": "should-never-render"},
        )
        defaults.update(kw)
        return PaymentTransaction.objects.create(**defaults)

    def _get(self):
        return self.client.get("/billing/payments/",
                               HTTP_ACCEPT="text/html,*/*", HTTP_ACCEPT_LANGUAGE="en")

    def test_only_own_org_payments_visible(self):
        self._txn(self.org, provider_reference="MINE_ref")
        self._txn(self.other, provider_reference="THEIRS_ref")
        r = self._get()
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "MINE_ref")
        self.assertNotContains(r, "THEIRS_ref")

    def test_empty_state(self):
        r = self._get()
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "No payments recorded yet")

    def test_no_raw_provider_json_rendered(self):
        self._txn(self.org)
        body = self._get().content.decode("utf-8", "ignore")
        self.assertNotIn("should-never-render", body)
        for forbidden in ("raw_request", "raw_response", "raw_webhook",
                          "checkout_url", "idempotency_key"):
            self.assertNotIn(forbidden, body)

    def test_paid_and_failed_rows_show_correct_status(self):
        from apps.payments.choices import PaymentStatus
        self._txn(self.org, status=PaymentStatus.PAID, provider_reference="PAID_ROW")
        self._txn(self.org, status=PaymentStatus.FAILED, provider_reference="FAILED_ROW")
        r = self._get()
        self.assertContains(r, "PAID_ROW")
        self.assertContains(r, "FAILED_ROW")
        self.assertContains(r, "pay-pill paid")
        self.assertContains(r, "pay-pill failed")
