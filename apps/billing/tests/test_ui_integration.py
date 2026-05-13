"""Tests for the billing UI integration — pricing page from DB,
dashboard subscription card, sidebar role-gating, context processor."""
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.billing.choices import PlanCode, SubscriptionStatus
from apps.billing.context_processors import billing as billing_cp
from apps.billing.models import Plan
from apps.billing.services.subscription_service import SubscriptionService
from apps.billing.tests._factories import make_org, make_user


User = get_user_model()


def _verified(*, organization, email="cp@e.com", role=None):
    u = User.objects.create_user(
        email=email, password="StrongPass123!",
        full_name="X", role=role or User.Role.ADMIN,
        organization=organization,
    )
    u.email_verified_at = timezone.now()
    u.save(update_fields=["email_verified_at"])
    return u


class PricingPageTests(TestCase):
    """The public /pricing/ page pulls plans from Plan model."""

    def setUp(self):
        call_command("seed_billing_plans", stdout=StringIO())
        self.client = APIClient()

    def test_anonymous_visitor_sees_all_four_plans(self):
        r = self.client.get(reverse("frontend:pricing"))
        self.assertEqual(r.status_code, 200)
        html = r.content.decode("utf-8")
        for code in ("free_trial", "starter", "business", "professional"):
            self.assertIn(f'data-plan="{code}"', html, f"missing plan card: {code}")

    def test_prices_come_from_database(self):
        # Tweak a price, expect the page to follow.
        plan = Plan.objects.get(code=PlanCode.BUSINESS)
        plan.price = 999
        plan.save(update_fields=["price"])
        r = self.client.get(reverse("frontend:pricing"))
        self.assertIn("999", r.content.decode("utf-8"))

    def test_business_has_most_popular_badge(self):
        r = self.client.get(reverse("frontend:pricing"))
        html = r.content.decode("utf-8")
        self.assertRegex(
            html,
            r'class="card[^"]*featured[^"]*"[^>]*data-plan="business"',
        )

    def test_authenticated_user_sees_dashboard_cta_in_topbar(self):
        org = make_org()
        user = _verified(organization=org, role=User.Role.ADMIN)
        self.client.force_login(user)
        r = self.client.get(reverse("frontend:pricing"), HTTP_ACCEPT_LANGUAGE="en")
        html = r.content.decode("utf-8")
        # Authenticated → the Dashboard CTA is rendered (label is
        # translation-aware; assert the href instead of the visible text).
        self.assertIn('href="/dashboard/" class="cta"', html)
        # And the "Start free trial" CTA is suppressed.
        self.assertNotIn(">Start free trial<", html)


class BillingContextProcessorTests(TestCase):
    """The context processor must return safe defaults across all
    user states (anonymous, no-org, no-sub, active-sub)."""

    def setUp(self):
        call_command("seed_billing_plans", stdout=StringIO())
        self.factory = RequestFactory()

    def _request_for(self, user):
        req = self.factory.get("/dashboard/")
        req.user = user
        return req

    def test_anonymous_user_gets_empty_namespace(self):
        from django.contrib.auth.models import AnonymousUser
        ctx = billing_cp(self._request_for(AnonymousUser()))
        self.assertFalse(ctx["billing"].has_subscription)
        self.assertFalse(ctx["billing"].show_billing_nav)

    def test_user_without_org_gets_empty_namespace(self):
        u = User.objects.create_user(
            email="noorg@e.com", password="StrongPass123!",
            full_name="X", role=User.Role.JUNIOR_AUDITOR,
        )
        ctx = billing_cp(self._request_for(u))
        self.assertFalse(ctx["billing"].has_subscription)

    def test_user_without_subscription_gets_no_sub_state(self):
        org = make_org()
        u = _verified(organization=org, role=User.Role.ADMIN)
        ctx = billing_cp(self._request_for(u))
        self.assertFalse(ctx["billing"].has_subscription)
        self.assertTrue(ctx["billing"].show_billing_nav)   # admin can manage

    def test_active_subscription_populates_full_namespace(self):
        org = make_org()
        u = _verified(organization=org, role=User.Role.ADMIN)
        plan = Plan.objects.get(code=PlanCode.STARTER)
        sub = SubscriptionService().create_pending_paid_subscription(org, plan)
        sub = SubscriptionService().activate_subscription(sub)
        sub.used_invoices = 30
        sub.save(update_fields=["used_invoices"])

        ctx = billing_cp(self._request_for(u))
        b = ctx["billing"]
        self.assertTrue(b.has_subscription)
        self.assertEqual(b.plan_code, "starter")
        self.assertEqual(b.status, "active")
        self.assertEqual(b.invoice_limit, 100)
        self.assertEqual(b.used_invoices, 30)
        self.assertEqual(b.remaining_invoices, 70)
        self.assertEqual(b.usage_percent, 30)
        self.assertTrue(b.show_billing_nav)

    def test_junior_auditor_does_not_see_billing_nav(self):
        org = make_org()
        u = _verified(organization=org, email="junior@e.com",
                      role=User.Role.JUNIOR_AUDITOR)
        ctx = billing_cp(self._request_for(u))
        self.assertFalse(ctx["billing"].show_billing_nav)

    def test_finance_manager_sees_billing_nav(self):
        org = make_org()
        u = _verified(organization=org, email="fm@e.com",
                      role=User.Role.FINANCE_MANAGER)
        ctx = billing_cp(self._request_for(u))
        self.assertTrue(ctx["billing"].show_billing_nav)
