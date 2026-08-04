"""Template context for billing-aware pages.

Adds ``billing`` to every dashboard template so the sidebar, the
dashboard header, and any internal page can render the org's current
subscription without re-querying:

    {{ billing.has_subscription }}
    {{ billing.plan_name }}
    {{ billing.used_invoices }} / {{ billing.invoice_limit }}
    {{ billing.usage_percent }}
    {{ billing.status }}
    {{ billing.show_billing_nav }}   ← role-gated visibility
    {{ billing.degraded }}           ← the query failed; figures are not real

Safe for unauthenticated traffic, missing-org users, and deployments
without ``apps.billing`` installed — returns an empty namespace.

**Why the failure path is shaped the way it is.** This ran on every page and
answered *any* exception with the empty namespace, whose
``show_billing_nav=False`` is correct for a logged-out visitor and badly wrong
for a billing fault. Unapplied migrations on production therefore presented as
"the الفوترة والاشتراك menu is gone" — no error, no banner, nothing in the UI
to suggest a fault. Hours went into looking for a permissions bug in the
navigation code. Two separate things were conflated:

  · **whether the menu may be shown** — a function of the user's role alone,
    which needs no subscription query and must survive one failing;
  · **what the quota figures are** — which does need the query.

So the role check is computed *before* the query, the failure path keeps the
menu visible, and ``degraded`` marks the figures as not real so a template can
say so out loud. A fault must never render as a missing feature.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace

from django.conf import settings
from django.utils.translation import get_language


logger = logging.getLogger("billing.context")


def _plan_name(plan):
    """Pick name_ar / name_en based on the current request language."""
    if plan is None:
        return ""
    lang = (get_language() or "").lower()
    if lang.startswith("ar"):
        return plan.name_ar or plan.name_en or ""
    return plan.name_en or plan.name_ar or ""


_BILLING_ROLES = {
    # Roles that should see the billing sidebar group.
    "admin", "cao",
    "finance_manager",
}


def _blank(*, show_billing_nav=False, degraded=False):
    return SimpleNamespace(
        has_subscription=False,
        plan_name="",
        plan_code="",
        status="",
        is_unlimited=False,
        is_unlimited_users=False,
        user_limit=0,
        seats_used=0,
        invoice_limit=0,
        used_invoices=0,
        reserved_invoices=0,
        remaining_invoices=0,
        usage_percent=0,
        starts_at=None,
        ends_at=None,
        is_expired=False,
        show_billing_nav=show_billing_nav,
        degraded=degraded,
    )


def _empty():
    return {"billing": _blank()}


def _nav_visible(user):
    """Role-only. Deliberately independent of any query that can fail."""
    return bool(
        user.is_superuser
        or user.is_staff
        or (getattr(user, "role", "") in _BILLING_ROLES)
    )


def billing(request):
    """Inject ``billing`` into every template context."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return _empty()
    organization = getattr(user, "organization", None)
    if organization is None:
        return _empty()

    try:
        from apps.billing.services.quota_service import QuotaService
    except ImportError:
        # The app genuinely is not deployed. There is no billing to link to,
        # so hiding the nav is the right answer here — unlike the failure path.
        return _empty()

    show_nav = _nav_visible(user)

    try:
        return {"billing": _subscription_context(organization, show_nav)}
    except Exception:                       # noqa: BLE001
        # A context processor raising takes down every authenticated page, so
        # production degrades rather than 500s. It degrades LOUDLY: ERROR with
        # a traceback, the nav still visible, and `degraded` set so the page
        # can tell the user the numbers are not real.
        logger.exception(
            "billing context failed for organization=%s — serving degraded "
            "context. Quota figures on this page are NOT real.",
            getattr(organization, "pk", "?"),
        )
        if settings.DEBUG:
            # In development the same fault must be impossible to miss.
            raise
        return {"billing": _blank(show_billing_nav=show_nav, degraded=True)}


def _subscription_context(organization, show_nav):
    from apps.billing.services.quota_service import QuotaService

    sub = QuotaService().get_active_subscription(organization)

    if sub is None:
        # Either no subscription yet, or expired/canceled/payment_failed.
        # Surface the "no sub" state so the dashboard can show a banner.
        from apps.billing.models import OrganizationSubscription
        last = (
            OrganizationSubscription.objects
            .select_related("plan")
            .filter(organization=organization)
            .order_by("-created_at")
            .first()
        )
        return SimpleNamespace(
            has_subscription=False,
            plan_name=(_plan_name(last.plan) if last else ""),
            plan_code=(last.plan.code if last else ""),
            status=(last.status if last else "none"),
            is_unlimited=False,
            is_unlimited_users=False,
            user_limit=0,
            seats_used=0,
            invoice_limit=0,
            used_invoices=0,
            reserved_invoices=0,
            remaining_invoices=0,
            usage_percent=0,
            starts_at=None,
            ends_at=None,
            is_expired=bool(last and last.status == "expired"),
            show_billing_nav=show_nav,
            degraded=False,
        )

    # NULL means unlimited; 0 means no allowance at all. `or 0` collapses the
    # two, which would tell an Enterprise customer their quota is zero on every
    # authenticated page. Branch on the flag instead of coercing.
    # §L.1.3 — the seat dimension rides on this same bar. Counted in SQL by
    # SeatService rather than by materialising the org's users here.
    from apps.billing.services.quota_service import SeatService

    seat_service       = SeatService()
    user_limit         = sub.user_limit
    is_unlimited_users = user_limit is None
    seats_used         = seat_service.seats_used(sub.organization)

    is_unlimited  = sub.is_unlimited_invoices
    invoice_limit = None if is_unlimited else int(sub.invoice_limit or 0)
    used          = int(sub.used_invoices or 0)
    reserved      = int(sub.reserved_invoices or 0)
    remaining     = sub.remaining_invoices
    usage_pct     = (
        0 if is_unlimited or not invoice_limit
        else int(round((used + reserved) * 100 / invoice_limit))
    )

    return SimpleNamespace(
        has_subscription=True,
        plan_name=_plan_name(sub.plan),
        plan_code=sub.plan.code,
        status=sub.status,
        is_unlimited=is_unlimited,
        is_unlimited_users=is_unlimited_users,
        user_limit=user_limit,
        seats_used=seats_used,
        invoice_limit=invoice_limit,
        used_invoices=used,
        reserved_invoices=reserved,
        remaining_invoices=remaining,
        usage_percent=usage_pct,
        starts_at=sub.starts_at,
        ends_at=sub.ends_at,
        is_expired=False,
        show_billing_nav=show_nav,
        degraded=False,
    )
