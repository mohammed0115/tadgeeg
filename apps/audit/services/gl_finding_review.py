"""GL risk-finding review workflow (TADGEEG-FIN-AUDIT-3B).

Lets an authorised auditor move a ``GeneralLedgerRiskFinding`` through a
controlled set of status transitions, writing one immutable
``GeneralLedgerRiskFindingReview`` trail row per action.

It changes only the finding's review state (status / reviewed_by / reviewed_at /
reviewer_note). It NEVER changes the original deterministic risk score/severity
(2B) or the materiality assessment (3A), never uses AI, and never writes to the
ledger.
"""
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.general_ledger_models import (
    GeneralLedgerRiskFinding,
    GeneralLedgerRiskFindingReview,
)

_F = GeneralLedgerRiskFinding
_S = _F.Status

# Allowed transitions. accepted/dismissed are FINAL (no reopen in this phase).
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    _S.CANDIDATE:      {_S.ACCEPTED, _S.DISMISSED, _S.NEEDS_EVIDENCE, _S.ESCALATED},
    _S.NEEDS_EVIDENCE: {_S.ACCEPTED, _S.DISMISSED, _S.ESCALATED},
    _S.ESCALATED:      {_S.ACCEPTED, _S.DISMISSED},
    _S.ACCEPTED:       set(),
    _S.DISMISSED:      set(),
}

# Transitions that require a non-empty reviewer note.
NOTE_REQUIRED = {_S.DISMISSED, _S.NEEDS_EVIDENCE, _S.ESCALATED}


class GLFindingReviewError(Exception):
    """Raised for invalid transitions / missing notes / cross-tenant actions.

    Carries a user-safe message suitable for a 400 response.
    """


def review_finding(finding: GeneralLedgerRiskFinding, *, actor, to_status: str,
                    reviewer_note: str = "", review_reason: str = "",
                    metadata: dict | None = None) -> GeneralLedgerRiskFindingReview:
    """Apply one review transition + write the audit-trail row. Atomic.

    Raises ``GLFindingReviewError`` for: unknown/invalid transition, a note
    required but missing, or an actor from another organization.
    """
    Reason = GeneralLedgerRiskFindingReview.Reason
    review_reason = review_reason or Reason.OTHER
    if review_reason not in Reason.values:
        raise GLFindingReviewError(f"invalid review_reason: {review_reason!r}")

    if to_status not in _F.Status.values:
        raise GLFindingReviewError(f"invalid status: {to_status!r}")

    # Tenant safety: the actor must belong to the finding's organization.
    actor_org_id = getattr(actor, "organization_id", None)
    if actor_org_id is not None and actor_org_id != finding.organization_id:
        raise GLFindingReviewError("cross-tenant review denied.")

    from_status = finding.status
    allowed = ALLOWED_TRANSITIONS.get(from_status, set())
    if to_status not in allowed:
        raise GLFindingReviewError(
            f"transition {from_status} → {to_status} is not allowed."
        )

    note = (reviewer_note or "").strip()
    if to_status in NOTE_REQUIRED and not note:
        raise GLFindingReviewError(
            f"a reviewer_note is required to set status '{to_status}'."
        )

    actor_user = actor if getattr(actor, "pk", None) else None
    now = timezone.now()
    with transaction.atomic():
        finding.status = to_status
        finding.reviewed_by = actor_user
        finding.reviewed_at = now
        finding.reviewer_note = note
        # Only review-state fields are saved — risk score/severity and the
        # materiality assessment are left exactly as they were.
        finding.save(update_fields=["status", "reviewed_by", "reviewed_at",
                                    "reviewer_note", "updated_at"])
        review = GeneralLedgerRiskFindingReview.objects.create(
            finding=finding,
            engagement=finding.engagement,
            organization=finding.organization,
            from_status=from_status,
            to_status=to_status,
            reviewer=actor_user,
            reviewer_note=note,
            review_reason=review_reason,
            metadata=metadata or {},
        )
    return review
