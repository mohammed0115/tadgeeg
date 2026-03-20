"""Celery tasks for authentication app."""

from celery import shared_task


@shared_task(name="apps.authentication.tasks.prune_audit_logs")
def prune_audit_logs():
    """Delete audit log records that have exceeded their 7-year retention window."""
    from datetime import timedelta
    from django.utils import timezone
    from .models import AuditLog

    RETENTION_YEARS = 7
    now = timezone.now()

    # Backfill retain_until for records that never had it set
    unset = list(
        AuditLog.objects.filter(retain_until__isnull=True).only("id", "timestamp")
    )
    for log in unset:
        log.retain_until = log.timestamp + timedelta(days=RETENTION_YEARS * 365)
    if unset:
        AuditLog.objects.bulk_update(unset, fields=["retain_until"])

    # Delete expired records
    deleted, _ = AuditLog.objects.filter(retain_until__lt=now).delete()
    return {"deleted": deleted}
