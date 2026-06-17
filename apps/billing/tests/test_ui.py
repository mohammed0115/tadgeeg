"""Stage 7 — Billing UI tests.

Covers the 8 checks from Docs/payment/00.md §7:
  1. Plans page shows the 4 plans.
  2. Prices come from the DB (Plan model), not hardcoded HTML.
  3. free_trial is shown as free.
  4. Business carries the "Most popular" badge.
  5. Subscription page shows remaining correctly.
  6. Usage page shows the ledger.
  7. (No regressions on mobile — exercised manually; we assert
     viewport meta tag presence as a smoke check.)
  8. RTL is correct — assert dir="rtl" when Arabic.

Plus a JSON content-negotiation check so SPAs don't get HTML.
"""
import json
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.billing.choices import PlanCode, SubscriptionStatus, UsageAction
from apps.billing.models import (
    OrganizationSubscription,
    Plan,
    UsageLedger,
)
from apps.billing.services.subscription_service import SubscriptionService
from apps.billing.tests._factories import make_org, make_user


def _verified_user(*, organization, email="ui@example.com"):
    User = get_user_model()
    u = User.objects.create_user(
        email=email, password="StrongPass123!",
        full_name="UI Test", role=User.Role.ADMIN,
        organization=organization,
    )
    u.email_verified_at = timezone.now()
    u.save(update_fields=["email_verified_at"])
    return u


class PlansPageTests(TestCase):
    """Tests 1, 2, 3, 4, 8."""

    def setUp(self):
        call_command("seed_billing_plans", stdout=StringIO())
        self.client = APIClient()
        self.org  = make_org()
        self.user = _verified_user(organization=self.org)
        self.client.force_login(self.user)

    def test_shows_four_plans(self):
        r = self.client.get(reverse("billing:plans"))
        self.assertEqual(r.status_code, 200)
        html = r.content.decode("utf-8")
        for code in ("free_trial", "starter", "business", "professional"):
            self.assertIn(f'data-plan="{code}"', html, f"plan card missing: {code}")

    def test_prices_come_from_database(self):
        """Spec test 2: don't hardcode prices — pull from Plan."""
        # Bump the DB price and assert the page reflects it.
        plan = Plan.objects.get(code=PlanCode.STARTER)
        plan.price = Decimal("777")
        plan.save(update_fields=["price"])

        r = self.client.get(reverse("billing:plans"))
        self.assertIn("777", r.content.decode("utf-8"))

    def test_free_trial_renders_as_free(self):
        r = self.client.get(reverse("billing:plans"), HTTP_ACCEPT_LANGUAGE="en")
        html = r.content.decode("utf-8")
        self.assertIn('data-plan="free_trial"', html)
        self.assertIn("Free", html)

    def test_business_has_most_popular_badge(self):
        r = self.client.get(reverse("billing:plans"))
        html = r.content.decode("utf-8")
        # CSS class `featured` is what styles the badge.
        # Look for the business card carrying that class.
        self.assertRegex(
            html,
            r'class="card[^"]*featured[^"]*"[^>]*data-plan="business"',
        )

    def test_rtl_when_language_is_arabic(self):
        r = self.client.get(reverse("billing:plans"), HTTP_ACCEPT_LANGUAGE="ar")
        html = r.content.decode("utf-8")
        self.assertIn('dir="rtl"', html)

    def test_viewport_meta_present(self):
        """Smoke check that the responsive viewport meta is shipped."""
        r = self.client.get(reverse("billing:plans"))
        self.assertIn('name="viewport"', r.content.decode("utf-8"))

    def test_free_trial_button_disabled_after_use(self):
        SubscriptionService().create_free_trial(self.org)
        r = self.client.get(reverse("billing:plans"), HTTP_ACCEPT_LANGUAGE="en")
        html = r.content.decode("utf-8")
        # The trial button changes to a disabled outline button.
        self.assertIn("Trial unavailable", html)
        self.assertIn('disabled', html)

    def test_json_request_returns_json_not_html(self):
        r = self.client.get(
            reverse("billing:plans"),
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(r["Content-Type"].split(";")[0], "application/json")
        data = r.json()
        self.assertEqual(len(data["plans"]), 4)


class SubscriptionPageTests(TestCase):
    """Test 5 — remaining + progress."""

    def setUp(self):
        call_command("seed_billing_plans", stdout=StringIO())
        self.client = APIClient()
        self.org  = make_org()
        self.user = _verified_user(organization=self.org)
        self.client.force_login(self.user)

    def _activate(self, *, used=0):
        plan = Plan.objects.get(code=PlanCode.BUSINESS)
        sub = SubscriptionService().create_pending_paid_subscription(self.org, plan)
        sub = SubscriptionService().activate_subscription(sub)
        if used:
            sub.used_invoices = used
            sub.save(update_fields=["used_invoices"])
        return sub

    def test_shows_plan_name_status_used_remaining(self):
        self._activate(used=320)
        r = self.client.get(reverse("billing:subscription"), HTTP_ACCEPT_LANGUAGE="en")
        self.assertEqual(r.status_code, 200)
        html = r.content.decode("utf-8")
        self.assertIn("Business", html)              # plan name
        self.assertIn("Active", html)                # localised status
        self.assertIn("320", html)                   # used
        self.assertIn("180", html)                   # remaining (500 - 320)

    def test_progress_bar_width_matches_used_pct(self):
        self._activate(used=400)                     # 80% of 500
        r = self.client.get(reverse("billing:subscription"))
        html = r.content.decode("utf-8")
        self.assertIn("width: 80%", html)

    def test_empty_state_when_no_subscription(self):
        r = self.client.get(reverse("billing:subscription"), HTTP_ACCEPT_LANGUAGE="en")
        self.assertEqual(r.status_code, 200)
        html = r.content.decode("utf-8")
        self.assertIn("don't have an active subscription", html.lower())

    def test_quota_full_warning_card_appears(self):
        self._activate(used=500)
        r = self.client.get(reverse("billing:subscription"), HTTP_ACCEPT_LANGUAGE="en")
        html = r.content.decode("utf-8")
        self.assertIn("used all available invoices", html.lower())

    def test_json_response_returns_subscription_payload(self):
        sub = self._activate(used=10)
        r = self.client.get(
            reverse("billing:subscription"),
            HTTP_ACCEPT="application/json",
        )
        data = r.json()
        self.assertEqual(data["subscription"]["status"], "active")
        self.assertEqual(data["subscription"]["used_invoices"], 10)


class UsagePageTests(TestCase):
    """Test 6 — ledger renders with pagination."""

    def setUp(self):
        call_command("seed_billing_plans", stdout=StringIO())
        self.client = APIClient()
        self.org  = make_org()
        self.user = _verified_user(organization=self.org)
        self.client.force_login(self.user)
        plan = Plan.objects.get(code=PlanCode.STARTER)
        self.sub = SubscriptionService().activate_subscription(
            SubscriptionService().create_pending_paid_subscription(self.org, plan)
        )

    def _seed_ledger(self, n=3):
        for i in range(n):
            UsageLedger.objects.create(
                organization=self.org,
                subscription=self.sub,
                action=UsageAction.CONSUME,
                quantity=1,
                reason=f"row {i}",
            )

    def test_usage_page_renders_ledger_rows(self):
        self._seed_ledger(3)
        r = self.client.get(reverse("billing:usage"))
        self.assertEqual(r.status_code, 200)
        html = r.content.decode("utf-8")
        self.assertIn("row 0", html)
        self.assertIn("row 1", html)
        self.assertIn("row 2", html)

    def test_usage_page_pagination_when_many_rows(self):
        self._seed_ledger(60)
        # Force English so the assertion isn't locale-dependent — matches the
        # established pattern used by test_usage_empty_state in this class.
        r = self.client.get(
            reverse("billing:usage") + "?page=1", HTTP_ACCEPT_LANGUAGE="en"
        )
        self.assertEqual(r.status_code, 200)
        html = r.content.decode("utf-8")
        # PAGE_SIZE=25 → 3 pages for 60 rows.
        self.assertIn("Page 1 of 3", html)
        # Page 2 link rendered (language-independent).
        self.assertIn("?page=2", html)

    def test_usage_empty_state(self):
        r = self.client.get(reverse("billing:usage"), HTTP_ACCEPT_LANGUAGE="en")
        html = r.content.decode("utf-8")
        self.assertIn("No usage recorded yet", html)

    def test_usage_json_endpoint(self):
        self._seed_ledger(2)
        r = self.client.get(
            reverse("billing:usage"),
            HTTP_ACCEPT="application/json",
        )
        data = r.json()
        self.assertEqual(data["count"], 2)
        self.assertEqual(len(data["results"]), 2)


class TenantIsolationOnUIPages(TestCase):
    """Org A must never see Org B's plans-page state, subscription, or ledger."""

    def setUp(self):
        call_command("seed_billing_plans", stdout=StringIO())
        self.client = APIClient()
        self.org_a = make_org("A")
        self.org_b = make_org("B")
        self.user_a = _verified_user(organization=self.org_a, email="a@example.com")
        self.user_b = _verified_user(organization=self.org_b, email="b@example.com")

        # Org B has used its trial; org A has not.
        SubscriptionService().create_free_trial(self.org_b)

    def test_org_a_sees_trial_available_when_org_b_consumed_it(self):
        self.client.force_login(self.user_a)
        r = self.client.get(
            reverse("billing:plans"),
            HTTP_ACCEPT="application/json",
        )
        self.assertFalse(r.json()["has_used_free_trial"])

    def test_org_b_sees_trial_unavailable(self):
        self.client.force_login(self.user_b)
        r = self.client.get(
            reverse("billing:plans"),
            HTTP_ACCEPT="application/json",
        )
        self.assertTrue(r.json()["has_used_free_trial"])

    def test_usage_page_only_shows_own_org_entries(self):
        # Seed a row for each org.
        plan = Plan.objects.get(code=PlanCode.STARTER)
        sub_a = SubscriptionService().activate_subscription(
            SubscriptionService().create_pending_paid_subscription(self.org_a, plan)
        )
        from apps.billing.services.quota_service import QuotaService
        sub_b = QuotaService().get_active_subscription(self.org_b)  # the trial
        UsageLedger.objects.create(
            organization=self.org_a, subscription=sub_a,
            action=UsageAction.CONSUME, reason="A-only",
        )
        UsageLedger.objects.create(
            organization=self.org_b, subscription=sub_b,
            action=UsageAction.CONSUME, reason="B-only",
        )
        self.client.force_login(self.user_a)
        r = self.client.get(reverse("billing:usage"))
        html = r.content.decode("utf-8")
        self.assertIn("A-only", html)
        self.assertNotIn("B-only", html)
