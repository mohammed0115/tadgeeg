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
