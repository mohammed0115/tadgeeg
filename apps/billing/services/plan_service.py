"""Plan catalogue lookup.

Thin wrapper around the ``Plan`` model. Keeps callers from having to
remember that disabled plans should not be sold to new customers but
existing subscriptions still need to be able to dereference them.
"""
from __future__ import annotations

from apps.billing.models import Plan


class PlanNotFound(LookupError):
    pass


def get_active_plan(code: str) -> Plan:
    """Return an *active* plan by code. Raises if missing/disabled."""
    try:
        return Plan.objects.get(code=code, is_active=True)
    except Plan.DoesNotExist as exc:
        raise PlanNotFound(f"No active plan with code={code!r}") from exc


def get_plan(code: str) -> Plan:
    """Return any plan by code (active or not). Used for back-references
    from existing subscriptions on retired plans."""
    try:
        return Plan.objects.get(code=code)
    except Plan.DoesNotExist as exc:
        raise PlanNotFound(f"No plan with code={code!r}") from exc


def list_purchasable_plans():
    """Active plans for display, ordered by the commercial ladder.

    Ordered by ``sort_order`` alone now, not ``sort_order, price``: custom-quote
    plans have a NULL price, and NULL ordering differs between backends
    (SQLite sorts NULL first, MySQL likewise, PostgreSQL last). ``sort_order``
    is explicit and identical everywhere.

    This returns everything DISPLAYABLE, including custom-quote plans — the
    pricing page must show Enterprise. Use ``list_checkout_plans()`` for what a
    customer may actually buy.
    """
    return Plan.objects.filter(is_active=True).order_by("sort_order")


def list_checkout_plans():
    """Plans a customer may purchase through self-service checkout.

    Excludes custom-quote plans: they carry no list price, so there is nothing
    for apps/payments/pricing.py to charge. Selling one at NULL/0 would hand
    away an unlimited plan for free.
    """
    return [plan for plan in list_purchasable_plans() if plan.is_purchasable]


def is_checkout_allowed(plan) -> bool:
    """Single predicate for 'can this be bought without talking to sales'."""
    return bool(plan) and plan.is_purchasable


def recommend_plan(*, users: int, invoices: int) -> dict:
    """Recommend the cheapest plan that fits both dimensions (§K).

    **The thresholds live here and only here.** §K and §M are explicit that the
    calculator holds no business rules: duplicating the ladder in JavaScript is
    how the page and the engine drift apart, and the first catalogue edit makes
    the page a liar. The page sends two numbers and renders what it is told.

    "Fits" means the plan covers BOTH dimensions. A plan with enough invoices
    but too few seats does not fit — recommending it would send someone to a
    checkout that cannot serve them.

    Unlimited (NULL) satisfies any requirement, which is why the comparison
    goes through an explicit None check rather than arithmetic.
    """
    from apps.billing.choices import ACCOUNTING_PLAN_CODES
    from apps.billing.models import Plan

    users = max(int(users or 0), 0)
    invoices = max(int(invoices or 0), 0)

    def fits(plan) -> bool:
        seat_ok = plan.user_limit is None or plan.user_limit >= users
        inv_ok = plan.invoice_limit is None or plan.invoice_limit >= invoices
        return seat_ok and inv_ok

    # The commercial ladder, cheapest first. Accounting plans are excluded:
    # they are priced on a client-companies dimension this platform cannot yet
    # enforce (ADR 0006), so recommending one would promise capability that
    # does not exist.
    candidates = [
        p for p in Plan.objects.filter(is_active=True).order_by("sort_order")
        if p.code not in ACCOUNTING_PLAN_CODES
    ]

    for plan in candidates:
        if not fits(plan):
            continue
        if plan.is_trial:
            # A trial is time-boxed and one-per-organisation; it is not an
            # answer to "which plan should I buy".
            continue
        return {
            "plan_code": plan.code,
            "plan_name_en": plan.name_en,
            "plan_name_ar": plan.name_ar or plan.name_en,
            "price": plan.price,
            "currency": plan.currency or "SAR",
            "is_custom_quote": bool(plan.is_custom_quote),
            "user_limit": plan.user_limit,
            "invoice_limit": plan.invoice_limit,
            "requested": {"users": users, "invoices": invoices},
        }

    # Nothing fits — which in practice means the top of the ladder is a custom
    # quote and the caller is beyond it. Say so rather than returning the
    # largest plan as though it were sufficient.
    return {
        "plan_code": None,
        "plan_name_en": "",
        "plan_name_ar": "",
        "price": None,
        "currency": "SAR",
        "is_custom_quote": True,
        "user_limit": None,
        "invoice_limit": None,
        "requested": {"users": users, "invoices": invoices},
    }
