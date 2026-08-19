from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from apps.authentication.models import Organization


@pytest.mark.django_db
def test_monthly_usage_summary_reads_tokens_cost_and_failures_from_records():
    from apps.ai_safety.models import AIUsageRecord
    from apps.ai_safety.reporting import monthly_usage_summary

    organization = Organization.objects.create(
        name="CRM usage tenant",
        name_ar="منظمة CRM",
        country="SA",
        currency="SAR",
        vat_number="300000000000501",
    )
    AIUsageRecord.objects.create(
        organization=organization, model="gpt-4o-mini", operation="extraction",
        prompt_tokens=100, completion_tokens=20, estimated_cost=Decimal("0.000027"),
        status=AIUsageRecord.Status.SUCCESS,
    )
    AIUsageRecord.objects.create(
        organization=organization, model="gpt-4o-mini", operation="assistant",
        prompt_tokens=10, completion_tokens=0, estimated_cost=Decimal("0.000002"),
        status=AIUsageRecord.Status.FAILED,
        failure_kind=AIUsageRecord.FailureKind.AUTH_401,
    )

    summary = monthly_usage_summary(organization, at=date.today())

    assert summary["prompt_tokens"] == 110
    assert summary["completion_tokens"] == 20
    assert summary["requests"] == 2
    assert summary["failures"] == 1
    assert summary["failure_rate"] == 0.5
    assert summary["estimated_cost"] == "0.000029"
    assert {row["operation"] for row in summary["by_operation"]} == {"assistant", "extraction"}
