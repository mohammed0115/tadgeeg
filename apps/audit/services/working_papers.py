"""
Working-paper workflow service — Phase 1.3 of the Enterprise Roadmap.

State machine:

    DRAFT ──submit──▶ READY_FOR_REVIEW ──review(approve)──▶ REVIEWED ──partner_sign──▶ LOCKED
                  ▲                  │
                  └─review(reject)───┘   (reviewer kicks the paper back)

Each transition is authorised against the actor's role:

    submit       → preparer  (the user who created the paper)
    review       → senior reviewer (User.Role.SENIOR_AUDITOR or above)
    partner_sign → partner    (User.Role.CHIEF_AUDIT_OFFICER, ADMIN, or
                               EXTERNAL_AUDITOR-acting-as-partner)

Once the partner signs, the paper transitions to LOCKED. The HashChainMixin
``_should_chain_now()`` returns True at that point and the pre_save signal
computes the chain hash, freezing the row.
"""

from __future__ import annotations

import logging
from typing import Optional

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.models import WorkingPaper, WPSignature
from apps.authentication.models import User

logger = logging.getLogger("finai")


# ─────────────────────────────────────────────────────────────────────────────
# Role gates
# ─────────────────────────────────────────────────────────────────────────────

REVIEWER_ROLES = {
    User.Role.SENIOR_AUDITOR,
    User.Role.CHIEF_AUDIT_OFFICER,
    User.Role.ADMIN,
}

PARTNER_ROLES = {
    User.Role.CHIEF_AUDIT_OFFICER,
    User.Role.ADMIN,
    User.Role.EXTERNAL_AUDITOR,
}


def _is_reviewer(user: User) -> bool:
    return user.is_superuser or user.role in REVIEWER_ROLES


def _is_partner(user: User) -> bool:
    return user.is_superuser or user.role in PARTNER_ROLES


# ─────────────────────────────────────────────────────────────────────────────
# Workflow API
# ─────────────────────────────────────────────────────────────────────────────

class WorkingPaperWorkflowError(ValidationError):
    """Raised when a workflow transition is rejected (wrong status, role, etc.)."""


def submit_for_review(paper: WorkingPaper, user: User) -> WorkingPaper:
    """Preparer submits the paper for senior review.

    The preparer FK is set if not already populated (typically the creating
    user). Status moves DRAFT → READY_FOR_REVIEW.
    """
    if paper.status != WorkingPaper.Status.DRAFT:
        raise WorkingPaperWorkflowError(
            f"Cannot submit a paper in status '{paper.status}'. "
            f"Only DRAFT papers may be submitted for review."
        )

    paper.status = WorkingPaper.Status.READY_FOR_REVIEW
    paper.submitted_at = timezone.now()
    if not paper.prepared_by_id:
        paper.prepared_by = user
        paper.prepared_at = paper.submitted_at
    paper.save(update_fields=["status", "submitted_at", "prepared_by",
                              "prepared_at", "updated_at"])
    return paper


@transaction.atomic
def review_paper(
    paper: WorkingPaper,
    user: User,
    *,
    decision: str,
    notes: str = "",
    method: str = WPSignature.Method.TYPED,
    signature_data: Optional[dict] = None,
    ip_address: Optional[str] = None,
) -> WorkingPaper:
    """Senior reviewer approves or rejects a submitted paper.

    Args:
        decision:        ``"approve"`` to advance to REVIEWED, ``"reject"`` to
                         kick back to DRAFT.
        notes:           Reviewer comments (mandatory on reject).
        method:          How the signature was captured.
        signature_data:  Method-specific payload (see WPSignature model).
        ip_address:      Optional, recorded on the WPSignature row.
    """
    if not _is_reviewer(user):
        raise PermissionDenied(
            "Senior auditor (or above) role is required to review working papers."
        )

    if paper.status != WorkingPaper.Status.READY_FOR_REVIEW:
        raise WorkingPaperWorkflowError(
            f"Cannot review a paper in status '{paper.status}'. "
            f"Only READY_FOR_REVIEW papers may be reviewed."
        )

    decision = (decision or "").lower()
    if decision not in {"approve", "reject"}:
        raise WorkingPaperWorkflowError("decision must be 'approve' or 'reject'.")

    if decision == "reject" and not notes.strip():
        raise WorkingPaperWorkflowError("A reason is required when rejecting a paper.")

    if decision == "approve":
        paper.status = WorkingPaper.Status.REVIEWED
        paper.reviewed_by = user
        paper.reviewed_at = timezone.now()
        paper.reviewer_notes = notes
        paper.save(update_fields=["status", "reviewed_by", "reviewed_at",
                                  "reviewer_notes", "updated_at"])

        WPSignature.objects.create(
            paper=paper, user=user,
            role=WPSignature.Role.REVIEWER,
            method=method,
            signature_data=signature_data or {"name": user.full_name},
            notes=notes,
            ip_address=ip_address,
        )
    else:
        paper.status = WorkingPaper.Status.DRAFT
        paper.reviewer_notes = notes
        paper.reviewed_by = None
        paper.reviewed_at = None
        paper.submitted_at = None
        paper.save(update_fields=["status", "reviewer_notes", "reviewed_by",
                                  "reviewed_at", "submitted_at", "updated_at"])

    return paper


@transaction.atomic
def partner_sign(
    paper: WorkingPaper,
    user: User,
    *,
    notes: str = "",
    method: str = WPSignature.Method.TYPED,
    signature_data: Optional[dict] = None,
    ip_address: Optional[str] = None,
) -> WorkingPaper:
    """Partner signs off → paper transitions to LOCKED and the chain freezes it."""

    if not _is_partner(user):
        raise PermissionDenied(
            "Partner / Chief Audit Officer role is required to sign working papers."
        )

    if paper.status != WorkingPaper.Status.REVIEWED:
        raise WorkingPaperWorkflowError(
            f"Cannot partner-sign a paper in status '{paper.status}'. "
            f"Only REVIEWED papers may be signed."
        )

    now = timezone.now()
    paper.status = WorkingPaper.Status.LOCKED
    paper.partner_signed_by = user
    paper.partner_signed_at = now
    paper.partner_notes = notes
    paper.locked_at = now

    # Saving with status=LOCKED makes _should_chain_now() return True; the
    # pre_save signal then computes and stores the chain hash.
    #
    # The chain columns are deliberately NOT listed here. HashChainMixin.save()
    # adds whatever it is about to write, because listing them by hand is a
    # trap: this call used to name previous_hash/event_hash/chain_position
    # explicitly, and when chain_partition joined them every locked paper was
    # saved with an empty partition.
    paper.save(update_fields=["status", "partner_signed_by", "partner_signed_at",
                              "partner_notes", "locked_at", "updated_at"])

    WPSignature.objects.create(
        paper=paper, user=user,
        role=WPSignature.Role.PARTNER,
        method=method,
        signature_data=signature_data or {"name": user.full_name},
        notes=notes,
        ip_address=ip_address,
    )
    logger.info(
        "[WorkingPaper] %s LOCKED by partner %s — chain head=%s",
        paper.reference, user.email, (paper.event_hash or "")[:16],
    )
    return paper


# ─────────────────────────────────────────────────────────────────────────────
# Reference numbering
# ─────────────────────────────────────────────────────────────────────────────

def next_reference(organization, paper_type: str) -> str:
    """Suggest the next reference number for a new paper.

    Format: ``WP-{YYYY}-{TYPE_PREFIX}-{seq}`` where TYPE_PREFIX is a short
    code per paper type (LS, ST, IC, AR, PBC, MEMO).

    Sequence resets per (organization, year, type_prefix).
    """
    type_prefix = {
        WorkingPaper.PaperType.LEAD_SCHEDULE:         "LS",
        WorkingPaper.PaperType.SUBSTANTIVE_TEST:      "ST",
        WorkingPaper.PaperType.INTERNAL_CONTROL_TEST: "IC",
        WorkingPaper.PaperType.ANALYTICAL_REVIEW:     "AR",
        WorkingPaper.PaperType.PBC_REQUEST:           "PBC",
        WorkingPaper.PaperType.MEMO:                  "MEMO",
    }.get(paper_type, "WP")

    year = timezone.now().year
    prefix = f"WP-{year}-{type_prefix}-"
    last = (
        WorkingPaper.objects
        .filter(organization=organization, reference__startswith=prefix)
        .order_by("-reference").first()
    )
    if not last:
        return f"{prefix}001"
    try:
        last_seq = int(last.reference.rsplit("-", 1)[-1])
    except (ValueError, IndexError):
        last_seq = 0
    return f"{prefix}{last_seq + 1:03d}"
