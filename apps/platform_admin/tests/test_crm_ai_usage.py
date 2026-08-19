from __future__ import annotations

import pytest
from django.urls import reverse

from apps.ai_safety.models import AIUsagePayload, AIUsageRecord


@pytest.mark.django_db
def test_finance_can_view_ai_usage_summary_but_not_payload(client, finance_user, organization):
    record = AIUsageRecord.objects.create(
        organization=organization,
        model="gpt-4o-mini",
        operation="assistant",
        prompt_tokens=10,
        completion_tokens=2,
        estimated_cost="0.000002",
        status=AIUsageRecord.Status.SUCCESS,
    )
    AIUsagePayload.objects.create(
        usage_record=record,
        request_payload={"secret": "must-never-render"},
        response_payload={"content": "must-never-render"},
    )
    client.force_login(finance_user)

    response = client.get(reverse("platform_admin:crm:customer_detail", args=[organization.id]))
    body = response.content.decode()

    assert response.status_code == 200
    assert "tab==='ai-usage'" in body
    assert "must-never-render" not in body


@pytest.mark.django_db
def test_support_cannot_view_financial_ai_usage(client, support_user, organization):
    client.force_login(support_user)

    response = client.get(reverse("platform_admin:crm:customer_detail", args=[organization.id]))

    assert response.status_code == 200
    assert "tab==='ai-usage'" not in response.content.decode()
