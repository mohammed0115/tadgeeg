"""Package retention evaluation with no destructive side effects.

Database backups are platform-wide safety controls, not per-tenant data deletion.
This module therefore only computes and records which evidence is due for the
existing audit lifecycle; archival or purge remains an explicit, checkpointed
operation owned by the evidence service.
"""
from __future__ import annotations

import calendar
from datetime import date

from django.utils import timezone

from apps.billing.models import OrganizationSubscription
from apps.billing.choices import USABLE_STATUSES


def months_before(value: date, months: int) -> date:
    """Calendar-safe month subtraction without approximating months as days."""
    month_index = value.year * 12 + (value.month - 1) - months
    year, month_zero = divmod(month_index, 12)
    month = month_zero + 1
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def retention_due_summary(*, as_of: date | None = None) -> dict:
    """Return due audit evidence by organisation without archiving or deleting.

    Frozen attachments and hash-chain rows are deliberately excluded.  The
    caller can use the summary to request a checkpointed archival operation.
    """
    from apps.audit.models import AuditEvidenceAttachment

    as_of = as_of or timezone.localdate()
    due_by_org: dict[str, int] = {}
    checked = 0
    subscriptions = (
        OrganizationSubscription.objects
        .filter(status__in=tuple(USABLE_STATUSES))
        .exclude(retention_months_snapshot__isnull=True)
        .select_related("organization")
    )
    for subscription in subscriptions.iterator(chunk_size=200):
        checked += 1
        cutoff = months_before(as_of, subscription.retention_months_snapshot)
        due = AuditEvidenceAttachment.objects.filter(
            organization=subscription.organization,
            uploaded_at__date__lt=cutoff,
            is_frozen=False,
        ).count()
        if due:
            due_by_org[str(subscription.organization_id)] = due

    return {
        "as_of": as_of.isoformat(),
        "subscriptions_checked": checked,
        "organizations_with_due_evidence": len(due_by_org),
        "due_attachments_by_organization": due_by_org,
        "destructive_action": False,
        "note": "Candidates only; archival must use the audit evidence lifecycle and a checkpoint.",
    }
