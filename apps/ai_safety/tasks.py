"""Maintenance tasks for durable AI accounting and short-lived diagnostics."""
from __future__ import annotations

from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone


@shared_task(name="ai_safety.prune_usage_payloads")
def prune_usage_payloads() -> dict[str, int]:
    """Delete diagnostic payloads after retention without touching usage rows."""
    from apps.ai_safety.models import AIUsagePayload

    days = int(getattr(settings, "AI_USAGE_PAYLOAD_RETENTION_DAYS", 30))
    cutoff = timezone.now() - timedelta(days=max(0, days))
    deleted, _ = AIUsagePayload.objects.filter(
        usage_record__created_at__lt=cutoff
    ).delete()
    return {"payload_rows_deleted": int(deleted), "retention_days": days}
