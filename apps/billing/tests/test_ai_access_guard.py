"""PAY-HARDEN-1 — unified AI cost-access guard (apps.billing.ai_access).

These tests prove the guard blocks paid AI paths BEFORE any OpenAI call across
subscription/suspension/budget states, and that it works independently of
SubscriptionRequiredMiddleware (the views are driven via APIRequestFactory,
which does not run middleware). All AI is mocked — no real OpenAI calls.
"""
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.billing.ai_access import (
    AIAccessDenied,
    ai_access_allowed,
    ai_access_response_or_none,
    check_ai_access,
    require_ai_access,
)
from apps.billing.choices import PlanCode
from apps.billing.models import Plan
from apps.billing.services.subscription_service import SubscriptionService
from apps.billing.tests._factories import make_org, make_user
from core.services import ai_budget


class _Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_billing_plans", stdout=StringIO())

    def setUp(self):
        cache.clear()  # AI budget counters live in cache — isolate per test.

    # ---- org builders ----

    def _org_active(self, name="Active Org"):
        org = make_org(name)
        plan = Plan.objects.get(code=PlanCode.STARTER)
        sub = SubscriptionService().create_pending_paid_subscription(org, plan)
        SubscriptionService().activate_subscription(sub)
        return org, sub

    def _org_expired(self, name="Expired Org"):
        org, sub = self._org_active(name)
        sub.ends_at = timezone.now() - timedelta(days=1)
        sub.save(update_fields=["ends_at"])
        return org, sub

    def _org_no_sub(self, name="No Sub Org"):
        return make_org(name)


class CheckAIAccessMatrixTests(_Base):
    def test_active_with_budget_ok_is_allowed(self):
        org, _ = self._org_active()
        self.assertTrue(check_ai_access(org).allowed)

    def test_no_subscription_denied_402(self):
        org = self._org_no_sub()
        d = check_ai_access(org)
        self.assertFalse(d.allowed)
        self.assertEqual(d.code, "no_subscription")
        self.assertEqual(d.http_status, 402)

    def test_expired_subscription_denied_402(self):
        org, _ = self._org_expired()
        d = check_ai_access(org)
        self.assertFalse(d.allowed)
        self.assertEqual(d.code, "subscription_expired")
        self.assertEqual(d.http_status, 402)

    def test_suspended_org_denied_403(self):
        org, _ = self._org_active("Suspended")
        org.is_active = False
        org.save(update_fields=["is_active"])
        d = check_ai_access(org)
        self.assertFalse(d.allowed)
        self.assertEqual(d.code, "organization_suspended")
        self.assertEqual(d.http_status, 403)

    def test_budget_exhausted_denied_429(self):
        org, _ = self._org_active("OverBudget")
        ai_budget.charge(org.id, ai_budget.get_daily_cap(org.id) + 1)
        d = check_ai_access(org)
        self.assertFalse(d.allowed)
        self.assertEqual(d.code, "ai_budget_exhausted")
        self.assertEqual(d.http_status, 429)

    def test_no_organization_denied(self):
        d = check_ai_access(None)
        self.assertFalse(d.allowed)
        self.assertEqual(d.code, "no_organization")

    def test_invoice_quota_exhausted_does_NOT_block_ai(self):
        # AI features meter on the token budget, NOT invoice quota. An ACTIVE
        # subscription with 0 remaining invoice units may still use AI.
        org, sub = self._org_active("QuotaZero")
        sub.used_invoices = sub.invoice_limit
        sub.save(update_fields=["used_invoices"])
        self.assertEqual(sub.remaining_invoices, 0)
        self.assertTrue(check_ai_access(org).allowed)


class GuardSwitchTests(_Base):
    @override_settings(AI_ACCESS_GUARD_ENABLED=False)
    def test_master_switch_off_allows_even_suspended(self):
        org, _ = self._org_active("Suspended")
        org.is_active = False
        org.save(update_fields=["is_active"])
        self.assertTrue(check_ai_access(org).allowed)

    @override_settings(SUBSCRIPTION_REQUIRED=False)
    def test_subscription_off_still_blocks_suspended(self):
        org, _ = self._org_active("Suspended")
        org.is_active = False
        org.save(update_fields=["is_active"])
        d = check_ai_access(org)
        self.assertFalse(d.allowed)
        self.assertEqual(d.code, "organization_suspended")

    @override_settings(SUBSCRIPTION_REQUIRED=False)
    def test_subscription_off_still_enforces_budget(self):
        org, _ = self._org_active("OverBudget")
        ai_budget.charge(org.id, ai_budget.get_daily_cap(org.id) + 1)
        d = check_ai_access(org)
        self.assertFalse(d.allowed)
        self.assertEqual(d.code, "ai_budget_exhausted")

    @override_settings(SUBSCRIPTION_REQUIRED=False)
    def test_subscription_off_skips_expiry_check(self):
        # With the subscription wall off, expiry is not enforced (budget caps
        # cost). Documents the deliberate behavior.
        org, _ = self._org_expired()
        self.assertTrue(check_ai_access(org).allowed)


class HelperApiTests(_Base):
    def test_require_ai_access_raises_on_denied(self):
        org = self._org_no_sub()
        with self.assertRaises(AIAccessDenied):
            require_ai_access(org)

    def test_require_ai_access_returns_decision_when_allowed(self):
        org, _ = self._org_active()
        self.assertTrue(require_ai_access(org).allowed)

    def test_ai_access_allowed_bool(self):
        org, _ = self._org_active()
        self.assertTrue(ai_access_allowed(org))
        self.assertFalse(ai_access_allowed(self._org_no_sub()))

    def test_response_helper_returns_none_when_allowed(self):
        org, _ = self._org_active()
        self.assertIsNone(ai_access_response_or_none(org))

    def test_response_helper_returns_response_with_status(self):
        org, _ = self._org_expired()
        resp = ai_access_response_or_none(org)
        self.assertIsNotNone(resp)
        self.assertEqual(resp.status_code, 402)
        self.assertEqual(resp.data["code"], "subscription_expired")


class AnalyticsViewGuardTests(_Base):
    """End-to-end via APIRequestFactory (NO middleware) — proves the in-view
    guard, not middleware, blocks the OpenAI call."""

    def _make_tx(self, org):
        from apps.transactions.models import Transaction
        return Transaction.objects.create(
            organization=org,
            transaction_type="expense",
            amount="100.00",
            transaction_date=timezone.now().date(),
        )

    def _call_fraud_view(self, user, tx_id):
        from apps.analytics.views import FraudScoringView
        factory = APIRequestFactory()
        request = factory.post("/api/v1/analytics/fraud/", {"transaction_id": str(tx_id)})
        force_authenticate(request, user=user)
        return FraudScoringView.as_view()(request)

    @mock.patch("apps.analytics.views.score_fraud_risk")
    def test_blocked_org_does_not_call_openai(self, mock_score):
        org, _ = self._org_active("BlockedView")
        org.is_active = False
        org.save(update_fields=["is_active"])
        user = make_user(organization=org, email="blocked@example.com")
        tx = self._make_tx(org)

        resp = self._call_fraud_view(user, tx.id)

        self.assertEqual(resp.status_code, 403)
        self.assertEqual(mock_score.call_count, 0)

    @mock.patch("apps.analytics.views.score_fraud_risk",
                return_value={"risk_score": 12, "risk_level": "low"})
    def test_allowed_org_calls_openai_once(self, mock_score):
        org, _ = self._org_active("AllowedView")
        user = make_user(organization=org, email="allowed@example.com")
        tx = self._make_tx(org)

        resp = self._call_fraud_view(user, tx.id)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(mock_score.call_count, 1)


class BackgroundTaskGuardTests(_Base):
    """The nightly anomaly task uses ai_access_allowed() to skip ineligible
    orgs — assert the decision it relies on."""

    def test_expired_org_is_skipped(self):
        org, _ = self._org_expired("TaskExpired")
        self.assertFalse(ai_access_allowed(org))

    def test_suspended_org_is_skipped(self):
        org, _ = self._org_active("TaskSuspended")
        org.is_active = False
        org.save(update_fields=["is_active"])
        self.assertFalse(ai_access_allowed(org))

    def test_active_org_is_processed(self):
        org, _ = self._org_active("TaskActive")
        self.assertTrue(ai_access_allowed(org))
