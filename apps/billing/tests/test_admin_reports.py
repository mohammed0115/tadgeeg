"""Stage 8 tests — admin actions + management commands + reports.

Covers the 5 spec test cases from Docs/payment/00.md §8:
  1. expire_subscriptions flips expired ones
  2. expire_subscriptions does NOT change non-expired
  3. remaining_invoices correct in admin display
  4. recalculate_usage_from_ledger works
  5. admin actions don't break data

Plus structural tests for the new management commands.
"""
from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import RequestFactory, TestCase
from django.utils import timezone

from apps.billing.admin import OrganizationSubscriptionAdmin
from apps.billing.choices import (
    PlanCode,
    SubscriptionStatus,
    UsageAction,
)
from apps.billing.models import (
    OrganizationSubscription,
    Plan,
    UsageLedger,
)
from apps.billing.services.subscription_service import SubscriptionService
from apps.billing.tests._factories import make_org


def _superuser(email="root@test.local"):
    User = get_user_model()
    return User.objects.create_superuser(
        email=email, password="StrongPass123!", full_name="Root",
    )


# ─── expire_subscriptions management command ────────────────────────────────
class ExpireSubscriptionsCommandTests(TestCase):
    """Spec tests 1 + 2."""

    def setUp(self):
        call_command("seed_billing_plans", stdout=StringIO())
        self.org = make_org()
        starter = Plan.objects.get(code=PlanCode.STARTER)

        # One past-due active subscription, one in-window active subscription.
        self.expired = SubscriptionService().create_pending_paid_subscription(self.org, starter)
        SubscriptionService().activate_subscription(self.expired)
        OrganizationSubscription.objects.filter(pk=self.expired.pk).update(
            ends_at=timezone.now() - timedelta(hours=1),
        )
        self.expired.refresh_from_db()

        other_org = make_org("Other")
        self.in_window = SubscriptionService().create_pending_paid_subscription(other_org, starter)
        SubscriptionService().activate_subscription(self.in_window)

    def test_expire_subscriptions_flips_past_due(self):
        call_command("expire_subscriptions", stdout=StringIO())
        self.expired.refresh_from_db()
        self.assertEqual(self.expired.status, SubscriptionStatus.EXPIRED)

    def test_expire_subscriptions_does_not_change_in_window(self):
        call_command("expire_subscriptions", stdout=StringIO())
        self.in_window.refresh_from_db()
        self.assertEqual(self.in_window.status, SubscriptionStatus.ACTIVE)

    def test_dry_run_does_not_mutate(self):
        out = StringIO()
        call_command("expire_subscriptions", "--dry-run", stdout=out)
        self.expired.refresh_from_db()
        self.assertEqual(self.expired.status, SubscriptionStatus.ACTIVE)
        self.assertIn("DRY RUN", out.getvalue())
        self.assertIn("1", out.getvalue())  # would-expire count

    def test_idempotent_on_second_run(self):
        call_command("expire_subscriptions", stdout=StringIO())
        # Already-expired rows are filtered out → second run is a no-op.
        out = StringIO()
        call_command("expire_subscriptions", stdout=out)
        self.assertIn("No subscriptions past", out.getvalue())


# ─── remaining_invoices property + admin column ─────────────────────────────
class RemainingInvoicesTests(TestCase):
    """Spec test 3."""

    def setUp(self):
        call_command("seed_billing_plans", stdout=StringIO())
        self.org = make_org()
        starter = Plan.objects.get(code=PlanCode.STARTER)
        sub = SubscriptionService().create_pending_paid_subscription(self.org, starter)
        self.sub = SubscriptionService().activate_subscription(sub)

    def test_remaining_invoices_equals_limit_minus_used_minus_reserved(self):
        self.sub.used_invoices = 30
        self.sub.reserved_invoices = 5
        self.sub.save()
        self.assertEqual(self.sub.remaining_invoices, 65)

    def test_remaining_invoices_never_negative(self):
        self.sub.used_invoices = 200
        self.sub.save()
        self.assertEqual(self.sub.remaining_invoices, 0)


# ─── recalculate_usage_from_ledger admin action ─────────────────────────────
class RecalculateUsageActionTests(TestCase):
    """Spec test 4."""

    def setUp(self):
        call_command("seed_billing_plans", stdout=StringIO())
        self.org = make_org()
        starter = Plan.objects.get(code=PlanCode.STARTER)
        sub = SubscriptionService().create_pending_paid_subscription(self.org, starter)
        self.sub = SubscriptionService().activate_subscription(sub)

        # Drift: counters say 0 / 0 but the ledger has activity.
        self._add_ledger(UsageAction.RESERVE, 5)
        self._add_ledger(UsageAction.CONSUME, 3)
        self._add_ledger(UsageAction.RELEASE, 1)
        # Manually break the counters:
        OrganizationSubscription.objects.filter(pk=self.sub.pk).update(
            used_invoices=0, reserved_invoices=0,
        )
        self.sub.refresh_from_db()

    def _add_ledger(self, action, n):
        for _ in range(n):
            UsageLedger.objects.create(
                organization=self.org, subscription=self.sub,
                action=action, quantity=1,
            )

    def _admin(self):
        from django.contrib.admin.sites import AdminSite
        return OrganizationSubscriptionAdmin(OrganizationSubscription, AdminSite())

    def test_recalculate_fixes_drift(self):
        admin = self._admin()
        req = RequestFactory().post("/admin/")
        req.user = _superuser()
        # Django admin needs a messages backend on the request when an
        # action calls message_user. The simplest test-time stub:
        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(req, "session", {})
        setattr(req, "_messages", FallbackStorage(req))

        admin.recalculate_usage_from_ledger(
            req, OrganizationSubscription.objects.filter(pk=self.sub.pk),
        )

        self.sub.refresh_from_db()
        # consume=3, refund=0 → used=3
        self.assertEqual(self.sub.used_invoices, 3)
        # reserve=5, consume=3, release=1 → reserved=1
        self.assertEqual(self.sub.reserved_invoices, 1)


# ─── expire/cancel admin actions ────────────────────────────────────────────
class AdminBulkActionsSafetyTests(TestCase):
    """Spec test 5 — admin actions don't corrupt data."""

    def setUp(self):
        call_command("seed_billing_plans", stdout=StringIO())
        self.org = make_org()
        starter = Plan.objects.get(code=PlanCode.STARTER)
        sub = SubscriptionService().create_pending_paid_subscription(self.org, starter)
        self.sub = SubscriptionService().activate_subscription(sub)
        # Snapshot quota counters so we can assert they're untouched.
        self.sub.used_invoices = 17
        self.sub.save(update_fields=["used_invoices"])

    def _admin(self):
        from django.contrib.admin.sites import AdminSite
        return OrganizationSubscriptionAdmin(OrganizationSubscription, AdminSite())

    def _request_with_messages(self):
        from django.contrib.messages.storage.fallback import FallbackStorage
        req = RequestFactory().post("/admin/")
        req.user = _superuser()
        setattr(req, "session", {})
        setattr(req, "_messages", FallbackStorage(req))
        return req

    def test_expire_action_flips_status_only(self):
        admin = self._admin()
        admin.expire_selected_subscriptions(
            self._request_with_messages(),
            OrganizationSubscription.objects.filter(pk=self.sub.pk),
        )
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, SubscriptionStatus.EXPIRED)
        # Counters preserved.
        self.assertEqual(self.sub.used_invoices, 17)
        # invoice_limit snapshot preserved.
        self.assertEqual(self.sub.invoice_limit, 100)

    def test_cancel_action_flips_status_only(self):
        admin = self._admin()
        admin.cancel_selected_subscriptions(
            self._request_with_messages(),
            OrganizationSubscription.objects.filter(pk=self.sub.pk),
        )
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, SubscriptionStatus.CANCELED)
        self.assertEqual(self.sub.used_invoices, 17)

    def test_csv_export_returns_valid_csv(self):
        admin = self._admin()
        response = admin.export_subscriptions_csv(
            self._request_with_messages(),
            OrganizationSubscription.objects.filter(pk=self.sub.pk),
        )
        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8")
        # Header + at least one data row.
        lines = [ln for ln in body.splitlines() if ln]
        self.assertGreaterEqual(len(lines), 2)
        self.assertIn("organization", lines[0])
        self.assertIn(str(self.sub.id), lines[1])


# ─── billing_usage_report command ───────────────────────────────────────────
class BillingUsageReportCommandTests(TestCase):
    """Verifies the 10-metric report runs and surfaces the right counts."""

    def setUp(self):
        call_command("seed_billing_plans", stdout=StringIO())
        plan = Plan.objects.get(code=PlanCode.STARTER)
        # 3 orgs in a mix of states.
        self.org_active = make_org("Active org")
        sub_a = SubscriptionService().create_pending_paid_subscription(self.org_active, plan)
        sub_a = SubscriptionService().activate_subscription(sub_a)
        sub_a.used_invoices = 60
        sub_a.save(update_fields=["used_invoices"])

        self.org_low = make_org("Low quota org")
        sub_low = SubscriptionService().create_pending_paid_subscription(self.org_low, plan)
        sub_low = SubscriptionService().activate_subscription(sub_low)
        sub_low.used_invoices = 95   # remaining = 5 → triggers "near depletion"
        sub_low.save(update_fields=["used_invoices"])

        self.org_expired = make_org("Expired org")
        sub_exp = SubscriptionService().create_pending_paid_subscription(self.org_expired, plan)
        SubscriptionService().activate_subscription(sub_exp)
        OrganizationSubscription.objects.filter(pk=sub_exp.pk).update(
            status=SubscriptionStatus.EXPIRED,
            ends_at=timezone.now() - timedelta(days=1),
        )

    def test_report_runs_and_prints_summary(self):
        out = StringIO()
        call_command("billing_usage_report", stdout=out)
        text = out.getvalue()
        self.assertIn("Billing Report", text)
        # 2 active subs in the window, 1 expired
        self.assertIn("Active subscriptions", text)
        self.assertIn("Expired subscriptions", text)
        # Top10 list shows the active orgs by used_invoices
        self.assertIn("Active org", text)
        self.assertIn("Low quota org", text)
        # Expected revenue: two starter subscriptions at the current list price.
        from apps.billing.models import Plan
        expected = int(Plan.objects.get(code=PlanCode.STARTER).price) * 2
        self.assertIn(str(expected), text)

    def test_report_csv_output(self):
        out = StringIO()
        call_command("billing_usage_report", "--csv", stdout=out)
        body = out.getvalue()
        self.assertIn("metric,value", body)
        self.assertIn("expected_revenue_sar", body)
        self.assertIn("top10_org", body)

    def test_near_depletion_threshold(self):
        # default threshold is 10 — Low quota org (remaining=5) should appear.
        out = StringIO()
        call_command("billing_usage_report", "--low-remaining-threshold=10",
                      stdout=out)
        self.assertIn("Low quota org", out.getvalue())

    def test_near_depletion_threshold_zero_excludes_all(self):
        """Threshold < 0 excludes everyone from the near-depletion list.
        Look ONLY inside the near-depletion section — Low quota org
        still appears in the Top-10 section above it."""
        out = StringIO()
        call_command(
            "billing_usage_report", "--low-remaining-threshold=-1",
            stdout=out,
        )
        text = out.getvalue()
        self.assertIn("Near-depletion", text)
        # Slice the section between the heading and the next heading.
        near_section = text.split("Near-depletion")[1].split("Near-expiry")[0]
        self.assertIn("(none)", near_section)
        self.assertNotIn("Low quota org", near_section)
