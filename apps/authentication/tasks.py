"""Celery tasks for authentication app."""

from celery import shared_task


@shared_task(name="apps.authentication.tasks.prune_audit_logs")
def prune_audit_logs():
    """Delete audit log records that have exceeded their 7-year retention window.

    Retention and tamper-evidence are in direct conflict here, and this task is
    where they meet. `verify_chain` walks from the head and reports the first
    gap, so a plain `.delete()` of the expired prefix would have made every
    surviving row report a break — permanently, for an operation the retention
    policy requires. An audit trail that cries tampering every night because of
    its own retention job stops being read, and then it protects nothing.

    So each organisation's expired prefix is retired through a checkpoint: an
    anchor recording how far the deletion ran and the `event_hash` it ran to,
    itself chained so it cannot be forged in isolation. Verification resumes
    from the anchor, and the remaining chain still commits to what was removed.

    Only a contiguous prefix is ever retired. Deleting expired rows from the
    *middle* of a chain — which a naive `retain_until__lt=now` filter would do
    whenever an older row had a later retention date — cannot be anchored and
    would be indistinguishable from tampering, so those rows are left until the
    whole prefix ahead of them has expired.
    """
    from datetime import timedelta

    from django.db.models import Max
    from django.utils import timezone

    from apps.audit.integrity import retire_chain_prefix
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

    deleted = 0
    checkpoints = []

    partitions = (
        AuditLog.objects.order_by()
        .values_list("chain_partition", flat=True)
        .distinct()
    )

    for partition in partitions:
        # The highest position whose entire prefix has expired. Anything at or
        # below the first *unexpired* row stays, so the deletion is always a
        # contiguous prefix and always anchorable.
        first_surviving = (
            AuditLog.objects
            .filter(chain_partition=partition, chain_position__isnull=False)
            .exclude(retain_until__lt=now)
            .order_by("chain_position")
            .values_list("chain_position", flat=True)
            .first()
        )

        if first_surviving is None:
            # Everything in this partition has expired.
            up_to = (
                AuditLog.objects
                .filter(chain_partition=partition, chain_position__isnull=False)
                .aggregate(m=Max("chain_position"))["m"]
            )
        else:
            up_to = first_surviving - 1

        if not up_to or up_to < 1:
            continue

        checkpoint = retire_chain_prefix(AuditLog, partition, up_to, reason="retention")
        if checkpoint is not None:
            deleted += checkpoint.rows_removed
            checkpoints.append(str(checkpoint.id))

    return {"deleted": deleted, "checkpoints": checkpoints}
