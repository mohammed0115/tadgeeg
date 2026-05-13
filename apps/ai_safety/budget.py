"""Per-organization AI cost cap.

Two budgets, both expressed in USD (the underlying provider currency):
  • daily   — defaults to ``AI_BUDGET_DAILY_USD``    (200 USD)
  • monthly — defaults to ``AI_BUDGET_MONTHLY_USD``  (4000 USD)

Override per organization via ``Organization.ai_budget_daily_usd`` and
``ai_budget_monthly_usd`` if those fields exist (treated as soft
overrides — None means "use global default").

Usage::

    spec = get_model("claude-opus-4-7")
    cost = spec.cost(input_tokens=12_000, output_tokens=2_000)
    assert_within_budget(org, projected_cost=cost)
    # ... make the call ...
    record_call(org, model=spec.name, input_tokens=12_000,
                output_tokens=2_000, cost=cost)
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional


class BudgetExceededError(RuntimeError):
    """Daily or monthly AI spend cap exceeded for this organization."""

    def __init__(self, *, scope: str, spent: Decimal, cap: Decimal):
        self.scope = scope     # "daily" | "monthly"
        self.spent = spent
        self.cap   = cap
        super().__init__(
            f"AI {scope} budget exhausted: spent {spent} USD ≥ cap {cap} USD"
        )


def _settings_default(name: str, fallback: Decimal) -> Decimal:
    from django.conf import settings
    return Decimal(str(getattr(settings, name, fallback)))


def _caps(organization) -> tuple[Decimal, Decimal]:
    daily = getattr(organization, "ai_budget_daily_usd", None)
    monthly = getattr(organization, "ai_budget_monthly_usd", None)
    daily_cap   = Decimal(str(daily))   if daily   else _settings_default("AI_BUDGET_DAILY_USD",   Decimal("200"))
    monthly_cap = Decimal(str(monthly)) if monthly else _settings_default("AI_BUDGET_MONTHLY_USD", Decimal("4000"))
    return daily_cap, monthly_cap


def _spent(organization, *, scope: str) -> Decimal:
    from django.utils import timezone
    from django.db.models import Sum
    from apps.ai_safety.models import AICostEvent
    now = timezone.now()
    qs = AICostEvent.objects.filter(organization=organization)
    if scope == "daily":
        qs = qs.filter(created_at__date=now.date())
    elif scope == "monthly":
        qs = qs.filter(created_at__year=now.year, created_at__month=now.month)
    agg = qs.aggregate(s=Sum("cost_usd"))["s"]
    return Decimal(str(agg or 0))


def assert_within_budget(organization, *, projected_cost: Decimal) -> None:
    daily_cap, monthly_cap = _caps(organization)
    daily_spent   = _spent(organization, scope="daily")
    monthly_spent = _spent(organization, scope="monthly")
    if daily_spent + projected_cost > daily_cap:
        raise BudgetExceededError(
            scope="daily", spent=daily_spent, cap=daily_cap,
        )
    if monthly_spent + projected_cost > monthly_cap:
        raise BudgetExceededError(
            scope="monthly", spent=monthly_spent, cap=monthly_cap,
        )


def record_call(organization, *,
                model: str,
                input_tokens: int,
                output_tokens: int,
                cost: Decimal,
                prompt_name: Optional[str] = None,
                prompt_version: Optional[int] = None,
                prompt_sha: Optional[str] = None,
                user=None) -> None:
    from apps.ai_safety.models import AICostEvent
    AICostEvent.objects.create(
        organization=organization,
        model=model,
        prompt_name=prompt_name or "",
        prompt_version=prompt_version or 0,
        prompt_sha=prompt_sha or "",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=Decimal(str(cost)),
        user=user,
    )


def summary(organization) -> dict:
    daily_cap, monthly_cap = _caps(organization)
    daily_spent   = _spent(organization, scope="daily")
    monthly_spent = _spent(organization, scope="monthly")
    return {
        "daily":   {"spent": str(daily_spent),   "cap": str(daily_cap),
                    "remaining": str(daily_cap - daily_spent)},
        "monthly": {"spent": str(monthly_spent), "cap": str(monthly_cap),
                    "remaining": str(monthly_cap - monthly_spent)},
    }
