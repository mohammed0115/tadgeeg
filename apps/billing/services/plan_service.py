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
    """Return the active plans, ordered for display on the billing page."""
    return Plan.objects.filter(is_active=True).order_by("sort_order", "price")
