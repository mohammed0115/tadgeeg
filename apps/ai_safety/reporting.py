"""Read-only CRM aggregates sourced from AIUsageRecord."""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone


def monthly_usage_summary(organization, *, at=None) -> dict:
    """Return one organisation's current-month token, cost and failure metrics."""
    from apps.ai_safety.models import AIUsageRecord

    today = timezone.localdate() if at is None else at
    qs = AIUsageRecord.objects.filter(
        organization=organization,
        created_at__year=today.year,
        created_at__month=today.month,
    )
    totals = qs.aggregate(
        prompt_tokens=Sum("prompt_tokens"),
        completion_tokens=Sum("completion_tokens"),
        estimated_cost=Sum("estimated_cost"),
        requests=Count("id"),
    )
    failures = qs.filter(status=AIUsageRecord.Status.FAILED).count()
    by_operation = list(
        qs.values("operation")
        .annotate(
            requests=Count("id"),
            prompt_tokens=Sum("prompt_tokens"),
            completion_tokens=Sum("completion_tokens"),
            estimated_cost=Sum("estimated_cost"),
            failures=Count("id", filter=Q(status=AIUsageRecord.Status.FAILED)),
        )
        .order_by("operation")
    )
    return {
        "month": today.strftime("%Y-%m"),
        "prompt_tokens": int(totals["prompt_tokens"] or 0),
        "completion_tokens": int(totals["completion_tokens"] or 0),
        "estimated_cost": str(
            Decimal(str(totals["estimated_cost"] or 0)).quantize(Decimal("0.000001"))
        ),
        "requests": int(totals["requests"] or 0),
        "failures": failures,
        "failure_rate": (failures / totals["requests"]) if totals["requests"] else 0.0,
        "by_operation": by_operation,
    }
