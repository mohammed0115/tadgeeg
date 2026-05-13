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

Safe for unauthenticated traffic, missing-org users, and deployments
without ``apps.billing`` installed — returns an empty namespace.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace


logger = logging.getLogger("billing.context")


_BILLING_ROLES = {
    # Roles that should see the billing sidebar group.
    "admin", "cao",
    "finance_manager",
}


def _empty():
    return {"billing": SimpleNamespace(
        has_subscription=False,
        plan_name="",
        plan_code="",
        status="",
        invoice_limit=0,
        used_invoices=0,
        reserved_invoices=0,
        remaining_invoices=0,
        usage_percent=0,
        starts_at=None,
        ends_at=None,
        is_expired=False,
        show_billing_nav=False,
    )}


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
        return _empty()

    try:
        sub = QuotaService().get_active_subscription(organization)
    except Exception:                       # noqa: BLE001 — never break a page
        logger.exception("billing context processor failed")
        return _empty()

    show_nav = bool(
        user.is_superuser
        or user.is_staff
        or (getattr(user, "role", "") in _BILLING_ROLES)
    )

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
        return {"billing": SimpleNamespace(
            has_subscription=False,
            plan_name=(last.plan.name_ar if last else ""),
            plan_code=(last.plan.code if last else ""),
            status=(last.status if last else "none"),
            invoice_limit=0,
            used_invoices=0,
            reserved_invoices=0,
            remaining_invoices=0,
            usage_percent=0,
            starts_at=None,
            ends_at=None,
            is_expired=bool(last and last.status == "expired"),
            show_billing_nav=show_nav,
        )}

    invoice_limit = int(sub.invoice_limit or 0)
    used          = int(sub.used_invoices or 0)
    reserved      = int(sub.reserved_invoices or 0)
    remaining     = sub.remaining_invoices
    usage_pct     = int(round((used + reserved) * 100 / invoice_limit)) if invoice_limit else 0

    return {"billing": SimpleNamespace(
        has_subscription=True,
        plan_name=sub.plan.name_ar or sub.plan.name_en,
        plan_code=sub.plan.code,
        status=sub.status,
        invoice_limit=invoice_limit,
        used_invoices=used,
        reserved_invoices=reserved,
        remaining_invoices=remaining,
        usage_percent=usage_pct,
        starts_at=sub.starts_at,
        ends_at=sub.ends_at,
        is_expired=False,
        show_billing_nav=show_nav,
    )}
