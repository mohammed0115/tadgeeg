"""SubscriptionRequiredMiddleware.

Sits between the auth middleware and the app views. For any
authenticated, non-superuser, non-API request that lands on an
"app-internal" page, this middleware checks whether the requester's
organization has a usable (trialing/active, within period) subscription.
If not, the request is redirected to ``/billing/plans/`` so the user
picks a plan before continuing.

What is allowed without a subscription:
- Anonymous traffic (handled by auth middleware/login views elsewhere).
- Superusers (Django admin operators, support staff).
- Billing pages themselves (so the user can pick a plan).
- Payment flow + provider webhooks (so they can pay).
- Auth + account-settings paths (logout, profile, OTP, password reset).
- Static / media files.
- Public marketing pages on / (landing, /pricing/, /about/, etc).
- The ``frontend:home`` route stays public.

Anything else under the dashboard or audit pipeline returns a redirect
(for HTML) or a 402 JSON response (for /api/v1/). 402 = Payment Required,
which lets SPAs route the user to the plan selector cleanly.
"""
from __future__ import annotations

import re

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect
from django.utils.translation import gettext as _

from apps.billing.services.quota_service import QuotaService


# Paths reachable without a subscription. The first match wins. Each
# entry is matched as a "starts-with" against request.path so we can
# whitelist whole route trees cheaply.
_WHITELIST_PREFIXES = (
    # Billing onboarding
    "/billing/plans/",
    "/billing/select-plan/",
    "/billing/subscription/",   # so the user can SEE that they're expired
    "/billing/usage/",          # usage history accessible during onboarding/expiry
    # Payments
    "/payments/",
    "/api/v1/payments/",
    # Auth + account self-service
    "/login/",
    "/logout/",
    "/register/",
    "/verify-email/",
    "/forgot-password/",
    "/reset/",
    "/mfa-login/",
    "/google-pending/",
    "/auth/",
    "/accounts/",
    # Public marketing
    "/about/",
    "/pricing/",
    "/contact/",
    "/privacy/",
    "/blog/",
    "/integrations/",
    "/api-page/",
    # API docs / schema only — NOT a blanket /api/ allow, which would
    # let unsubscribed users hit /api/v1/invoices/ etc.
    "/api/docs/",
    "/api/schema/",
    "/api/redoc/",
    "/careers/",
    "/robots.txt",
    "/sitemap.xml",
    "/i18n/",
    # System endpoints
    "/static/",
    "/media/",
    "/healthz",
    "/health/",
    "/admin/",
    "/django-admin/",
)


def _is_whitelisted(path: str) -> bool:
    if path == "/":  # public landing
        return True
    for prefix in _WHITELIST_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


class SubscriptionRequiredMiddleware:
    """Block app-internal pages for authenticated users whose org has
    no usable subscription. Configurable via ``SUBSCRIPTION_REQUIRED``
    setting (default True) — flip to False during migration windows."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.enabled = getattr(settings, "SUBSCRIPTION_REQUIRED", True)
        self.svc = QuotaService()

    def __call__(self, request):
        if self.enabled and self._needs_subscription_check(request):
            blocked = self._maybe_block(request)
            if blocked is not None:
                return blocked
        return self.get_response(request)

    # ---- decision pieces ----

    def _needs_subscription_check(self, request) -> bool:
        # Anonymous → other middleware handles login.
        if not getattr(request, "user", None) or not request.user.is_authenticated:
            return False
        # Superusers / staff bypass — admin/support tooling.
        if request.user.is_superuser or request.user.is_staff:
            return False
        # Whitelisted paths.
        if _is_whitelisted(request.path):
            return False
        return True

    def _maybe_block(self, request):
        org = getattr(request.user, "organization", None)
        if org is None:
            # User has no org at all → not a billing decision; let other
            # parts of the system surface that.
            return None

        sub = self.svc.get_active_subscription(org)
        if sub is not None:
            return None  # all good

        # No usable subscription. Distinguish "never had one" from "had
        # one and it expired/canceled" so the message is helpful.
        from apps.billing.models import OrganizationSubscription
        has_history = OrganizationSubscription.objects.filter(organization=org).exists()
        message = (
            _("Your subscription has expired. Please renew to continue.")
            if has_history
            else _("Please choose a plan to continue.")
        )

        # API requests → JSON 402. UI requests → redirect.
        if request.path.startswith("/api/"):
            return JsonResponse(
                {
                    "detail": str(message),
                    "code": "subscription_required",
                    "redirect": "/billing/plans/",
                },
                status=402,
            )
        return redirect("/billing/plans/")
