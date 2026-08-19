"""Package-aware, non-destructive audit evidence archiving."""
from __future__ import annotations

from datetime import date

from django.utils import timezone

from apps.billing.choices import USABLE_STATUSES
from apps.billing.models import OrganizationSubscription
from apps.billing.services.retention import months_before


def archive_due_evidence(*, as_of: date | None = None, actor=None) -> dict:
    """Archive evidence beyond a frozen subscription retention term.

    This function never deletes a record or stored file. It delegates lifecycle
    changes to the established evidence service so frozen evidence remains
    immutable and every archive action emits an append-only event.
    """
    from apps.audit.evidence_models import AuditEvidenceAttachment
    from apps.audit.services.evidence_lifecycle import archive_attachment

    as_of = as_of or timezone.localdate()
    archived = skipped_frozen = 0
    subscriptions = (
        OrganizationSubscription.objects.filter(status__in=tuple(USABLE_STATUSES))
        .exclude(retention_months_snapshot__isnull=True)
        .select_related("organization")
    )
    for subscription in subscriptions.iterator(chunk_size=200):
        cutoff = months_before(as_of, subscription.retention_months_snapshot)
        candidates = AuditEvidenceAttachment.objects.filter(
            organization=subscription.organization,
            lifecycle_state=AuditEvidenceAttachment.Lifecycle.ACTIVE,
            uploaded_at__date__lt=cutoff,
        ).select_related("evidence_request")
        for attachment in candidates.iterator(chunk_size=200):
            if attachment.is_frozen:
                skipped_frozen += 1
                continue
            archive_attachment(
                attachment=attachment,
                actor=actor,
                note="Package retention archive; stored evidence remains recoverable.",
            )
            archived += 1
    return {
        "as_of": as_of.isoformat(),
        "archived": archived,
        "skipped_frozen": skipped_frozen,
        "destructive_action": False,
    }
