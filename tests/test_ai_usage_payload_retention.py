from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.authentication.models import Organization


def _organization() -> Organization:
    return Organization.objects.create(
        name="Payload retention tenant",
        name_ar="منظمة تقليم الحمولات",
        country="SA",
        currency="SAR",
        vat_number="300000000000401",
    )


@pytest.mark.django_db
def test_payload_pruning_keeps_durable_usage_record(settings):
    from apps.ai_safety.models import AIUsagePayload, AIUsageRecord
    from apps.ai_safety.tasks import prune_usage_payloads

    settings.AI_USAGE_PAYLOAD_RETENTION_DAYS = 30
    record = AIUsageRecord.objects.create(
        organization=_organization(),
        model="gpt-4o-mini",
        operation="assistant",
        status=AIUsageRecord.Status.SUCCESS,
    )
    payload = AIUsagePayload.objects.create(
        usage_record=record,
        request_payload={"safe": "diagnostic"},
        response_payload={"safe": "diagnostic"},
    )
    AIUsageRecord.objects.filter(pk=record.pk).update(
        created_at=timezone.now() - timedelta(days=31)
    )

    outcome = prune_usage_payloads()

    assert outcome["payload_rows_deleted"] == 1
    assert not AIUsagePayload.objects.filter(pk=payload.pk).exists()
    assert AIUsageRecord.objects.filter(pk=record.pk).exists()


def test_payload_pruning_is_scheduled(settings):
    entry = settings.CELERY_BEAT_SCHEDULE["ai-safety-prune-usage-payloads"]
    assert entry["task"] == "ai_safety.prune_usage_payloads"
