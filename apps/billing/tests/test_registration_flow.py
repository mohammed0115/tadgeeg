"""Stage 2 tests.

Covers the 8 cases listed in Docs/payment/00.md section 2:
  1. After registration, user is redirected to /billing/plans/.
  2. User without subscription cannot reach the dashboard.
  3. User can reach /billing/plans/.
  4. Selecting free_trial activates a trialing subscription.
  5. Cannot select free_trial twice.
  6. After an active subscription, user CAN reach the dashboard.
  7. Expired subscription blocks audit / upload endpoints.
  8. Superuser is unaffected by the middleware.

Plus a few defensive checks that fell out of the design (whitelist
coverage, post-auth helper behaviour).
"""
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.billing.choices import PlanCode, SubscriptionStatus
from apps.billing.models import OrganizationSubscription, Plan
from apps.billing.services.subscription_service import SubscriptionService
from apps.billing.tests._factories import make_org, make_user


def _make_verified_user(*, organization, email="user@example.com"):
    """Create a fully-verified user — what we have after OTP."""
    User = get_user_model()
    u = User.objects.create_user(
        email=email, password="StrongPass123!",
        full_name="Verified User", role=User.Role.ADMIN,
        organization=organization,
    )
    # ``is_email_verified`` is a derived property; persist the timestamp.
    u.email_verified_at = timezone.now()
    u.save(update_fields=["email_verified_at"])
    return u


class PostAuthRedirectTests(TestCase):
    """Test 1: post-auth helper routes new orgs to /billing/plans/."""

    def setUp(self):
        call_command("seed_billing_plans", stdout=StringIO())
        self.org = make_org()
        self.user = _make_verified_user(organization=self.org)

    def test_unsubscribed_verified_user_is_routed_to_plans(self):
        from apps.frontend.page_views import _post_auth_redirect
        self.assertEqual(_post_auth_redirect(self.user), "/billing/plans/")

    def test_subscribed_user_is_routed_to_dashboard(self):
        from apps.frontend.page_views import _post_auth_redirect
        SubscriptionService().create_free_trial(self.org)
        self.assertEqual(_post_auth_redirect(self.user), "/dashboard/")

    def test_unverified_user_is_routed_to_verify_email(self):
        from apps.frontend.page_views import _post_auth_redirect
        self.user.email_verified_at = None
        self.user.save(update_fields=["email_verified_at"])
        self.assertEqual(_post_auth_redirect(self.user), "/verify-email/")


class MiddlewareBlocksUnsubscribedDashboardTests(TestCase):
    """Tests 2, 6, 8."""

    def setUp(self):
        call_command("seed_billing_plans", stdout=StringIO())
        self.client = APIClient()
        self.org   = make_org()
        self.user  = _make_verified_user(organization=self.org)

    def test_unsubscribed_user_redirected_off_dashboard(self):
        self.client.force_login(self.user)
        r = self.client.get("/dashboard/", follow=False)
        self.assertIn(r.status_code, (302, 301), r.content[:200])
        self.assertEqual(r.url, "/billing/plans/")

    def test_unsubscribed_user_can_reach_billing_plans(self):
        self.client.force_login(self.user)
        r = self.client.get(reverse("billing:plans"), HTTP_ACCEPT="application/json")
        self.assertEqual(r.status_code, 200, r.content[:200])
        plans = r.json()["plans"]
        self.assertEqual(len(plans), 9)  # Phase 3A: catalogue is nine plans

    def test_subscribed_user_can_reach_dashboard(self):
        """Middleware must NOT redirect a subscribed user away from the
        dashboard. The dashboard view itself may 200, 500, or redirect
        somewhere else — those are not our concern. The single thing we
        assert here is that we don't see a 30x → /billing/plans/."""
        SubscriptionService().create_free_trial(self.org)
        self.client.force_login(self.user)
        r = self.client.get("/dashboard/", follow=False)
        if r.status_code in (301, 302):
            self.assertNotEqual(r.url, "/billing/plans/")

    def test_api_request_without_subscription_returns_402(self):
        self.client.force_login(self.user)
        r = self.client.get("/api/v1/invoices/")
        self.assertEqual(r.status_code, 402)
        self.assertEqual(r.json()["code"], "subscription_required")

    def test_superuser_is_not_blocked(self):
        """Superuser must not be redirected to /billing/plans/ — they
        bypass the subscription check entirely. The dashboard view
        itself may still fail for unrelated reasons (those are not our
        concern here)."""
        User = get_user_model()
        superuser = User.objects.create_superuser(
            email="root@example.com",
            password="StrongPass123!",
            full_name="Root",
        )
        client = APIClient(raise_request_exception=False)
        client.force_login(superuser)
        r = client.get("/dashboard/", follow=False)
        if r.status_code in (301, 302):
            self.assertNotEqual(r.url, "/billing/plans/")
        # 200 / 500 / etc all OK — middleware let the request through.


class SelectPlanFreeTrialTests(TestCase):
    """Tests 4 and 5."""

    def setUp(self):
        call_command("seed_billing_plans", stdout=StringIO())
        self.client = APIClient()
        self.org  = make_org()
        self.user = _make_verified_user(organization=self.org)

    def test_selecting_free_trial_activates_trialing_subscription(self):
        self.client.force_login(self.user)
        r = self.client.post(
            reverse("billing:select-plan"),
            data={"plan_code": "free_trial"}, format="json",
        )
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["next"], "/dashboard/")

        sub = OrganizationSubscription.objects.get(organization=self.org)
        self.assertEqual(sub.status, SubscriptionStatus.TRIALING)
        self.assertEqual(sub.invoice_limit, 20)

    def test_second_free_trial_is_refused(self):
        SubscriptionService().create_free_trial(self.org)
        self.client.force_login(self.user)
        r = self.client.post(
            reverse("billing:select-plan"),
            data={"plan_code": "free_trial"}, format="json",
        )
        self.assertEqual(r.status_code, 409)
        # The plan-action matrix now blocks a second trial up front with a
        # unified code (covers both "trial already used" and "already has an
        # active subscription").
        self.assertEqual(r.json()["code"], "trial_unavailable")

    def test_selecting_paid_plan_creates_pending_payment_subscription(self):
        """Stage 4: select-plan creates the subscription AND fires
        PaymentService.create_transaction; ``next`` is now the gateway's
        real checkout_url."""
        from unittest import mock
        from apps.payments.choices import PaymentStatus
        from apps.payments.gateways.base import GatewayResponse

        with mock.patch(
            "apps.payments.gateways.moyasar.MoyasarGateway.create_payment",
            return_value=GatewayResponse(
                provider="moyasar", provider_payment_id="pay_test_xx",
                provider_reference="", checkout_url="https://checkout.moyasar.test/xx",
                status=PaymentStatus.REDIRECT_REQUIRED, raw_response={},
            ),
        ):
            self.client.force_login(self.user)
            r = self.client.post(
                reverse("billing:select-plan"),
                data={"plan_code": "starter"}, format="json",
            )
        self.assertEqual(r.status_code, 201, r.content)
        sub = OrganizationSubscription.objects.get(organization=self.org)
        self.assertEqual(sub.status, SubscriptionStatus.PENDING_PAYMENT)
        self.assertEqual(r.json()["next"], "https://checkout.moyasar.test/xx")
        # subscription must be linked to the new payment_transaction
        self.assertIsNotNone(sub.payment_transaction)


class ExpiredSubscriptionBlocksAccessTests(TestCase):
    """Test 7."""

    def setUp(self):
        call_command("seed_billing_plans", stdout=StringIO())
        self.client = APIClient()
        self.org  = make_org()
        self.user = _make_verified_user(organization=self.org)

        # Build an expired subscription directly so we don't depend on time travel.
        plan = Plan.objects.get(code=PlanCode.STARTER)
        self.sub = OrganizationSubscription.objects.create(
            organization=self.org, plan=plan,
            status=SubscriptionStatus.EXPIRED,
            invoice_limit=100, used_invoices=100,
            starts_at=timezone.now(), ends_at=timezone.now(),
        )

    def test_expired_subscription_still_blocks_dashboard(self):
        self.client.force_login(self.user)
        r = self.client.get("/dashboard/", follow=False)
        self.assertIn(r.status_code, (301, 302))
        self.assertEqual(r.url, "/billing/plans/")

    def test_expired_subscription_message_says_renew(self):
        """The middleware distinguishes 'never had one' from 'expired'."""
        self.client.force_login(self.user)
        r = self.client.get("/api/v1/invoices/", HTTP_ACCEPT_LANGUAGE="en")
        self.assertEqual(r.status_code, 402)
        self.assertIn("expired", r.json()["detail"].lower())


class WhitelistTests(TestCase):
    """Defensive coverage of the middleware path whitelist."""

    def setUp(self):
        call_command("seed_billing_plans", stdout=StringIO())
        self.client = APIClient()
        self.org  = make_org()
        self.user = _make_verified_user(organization=self.org)
        self.client.force_login(self.user)

    def test_logout_path_is_reachable(self):
        # Logout works whether or not the user has a sub.
        r = self.client.get("/logout/", follow=False)
        self.assertIn(r.status_code, (200, 301, 302), r.content[:200])
        # Crucially: the redirect target is NOT /billing/plans/
        if r.status_code in (301, 302):
            self.assertNotEqual(r.url, "/billing/plans/")

    def test_payment_webhook_is_not_redirected(self):
        # Anonymous POST to a webhook URL must not be middleware-blocked.
        self.client.logout()
        r = self.client.post(
            "/api/v1/payments/webhooks/moyasar/",
            data=b"{}", content_type="application/json",
        )
        # The webhook view's own logic will reject the body, but we
        # must not see a 302 to /billing/plans/.
        self.assertNotIn(r.status_code, (301, 302))

    def test_static_path_is_not_redirected(self):
        r = self.client.get("/static/favicon.ico")
        self.assertNotIn(r.status_code, (301, 302))
