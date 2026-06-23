"""Management-response workflow for SAD items (TADGEEG-FIN-AUDIT-4B).

Moves an ``AuditDifferenceItem.management_response_status`` through a controlled
set of transitions, writing one append-only ``AuditDifferenceItemResponse`` per
action. Records the auditor's tracking of management's response to an accepted
audit difference. It never modifies the source finding and never touches the
ledger.
"""
from __future__ import annotations

from django.db import transaction

from apps.audit.audit_difference_models import (
    AuditDifferenceItem,
    AuditDifferenceItemResponse,
)

_MR = AuditDifferenceItem.ManagementResponse

# Allowed transitions. adjusted/unadjusted are FINAL in this phase.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    _MR.NOT_REQUESTED: {_MR.PENDING},
    _MR.PENDING:       {_MR.AGREED, _MR.DISAGREED},
    _MR.AGREED:        {_MR.ADJUSTED, _MR.UNADJUSTED},
    _MR.DISAGREED:     {_MR.UNADJUSTED},
    _MR.ADJUSTED:      set(),
    _MR.UNADJUSTED:    set(),
}

# Transitions that require a non-empty note.
NOTE_REQUIRED = {_MR.DISAGREED, _MR.UNADJUSTED, _MR.ADJUSTED}


class ManagementResponseError(Exception):
    """Raised for invalid transitions / missing notes / cross-tenant actions."""


def record_response(item: AuditDifferenceItem, *, actor, to_status: str,
                    response_note: str = "", response_reason: str = "",
                    metadata: dict | None = None) -> AuditDifferenceItemResponse:
    """Apply one management-response transition + write the trail row. Atomic."""
    Reason = AuditDifferenceItemResponse.Reason
    response_reason = response_reason or Reason.OTHER
    if response_reason not in Reason.values:
        raise ManagementResponseError(f"invalid response_reason: {response_reason!r}")

    if to_status not in _MR.values:
        raise ManagementResponseError(f"invalid status: {to_status!r}")

    actor_org_id = getattr(actor, "organization_id", None)
    if actor_org_id is not None and actor_org_id != item.organization_id:
        raise ManagementResponseError("cross-tenant response denied.")

    from_status = item.management_response_status
    if to_status not in ALLOWED_TRANSITIONS.get(from_status, set()):
        raise ManagementResponseError(
            f"transition {from_status} → {to_status} is not allowed."
        )

    note = (response_note or "").strip()
    if to_status in NOTE_REQUIRED and not note:
        raise ManagementResponseError(
            f"a response_note is required to set status '{to_status}'."
        )

    actor_user = actor if getattr(actor, "pk", None) else None
    with transaction.atomic():
        item.management_response_status = to_status
        item.save(update_fields=["management_response_status"])
        response = AuditDifferenceItemResponse.objects.create(
            item=item, summary=item.summary, engagement=item.engagement,
            organization=item.organization, from_status=from_status,
            to_status=to_status, actor=actor_user, response_note=note,
            response_reason=response_reason, metadata=metadata or {},
        )
    return response
