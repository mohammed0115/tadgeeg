"""Evidence Request workflow service (TADGEEG-FIN-AUDIT-6A).

Create / submit / attach / review evidence requests against GL findings and SAD
items. Enforces organization consistency, an explicit status-transition graph,
reviewer-note requirements, and an append-only event history.

It NEVER modifies the linked GL finding (accepting evidence does not accept or
dismiss the finding — the auditor reviews the finding separately via 3B), never
issues an opinion, never uses AI, and never writes to ``apps.ledger``.
"""
from __future__ import annotations

import hashlib

from django.db import transaction
from django.utils import timezone

from apps.audit.evidence_models import (
    AuditEvidenceAttachment,
    AuditEvidenceRequest,
    AuditEvidenceRequestEvent,
)

_R = AuditEvidenceRequest
_S = _R.Status
_ET = AuditEvidenceRequestEvent.EventType

# Explicit transition graph (TADGEEG-FIN-AUDIT-6A §6). Cancel is permitted from
# any non-final state (safe superset — a cancel is not a reopen).
ALLOWED_TRANSITIONS = {
    _S.OPEN:                   {_S.SUBMITTED, _S.CANCELLED},
    _S.SUBMITTED:              {_S.UNDER_REVIEW, _S.CANCELLED},
    _S.UNDER_REVIEW:           {_S.ACCEPTED, _S.REJECTED, _S.MORE_EVIDENCE_REQUIRED, _S.CANCELLED},
    _S.MORE_EVIDENCE_REQUIRED: {_S.SUBMITTED, _S.CANCELLED},
    _S.ACCEPTED:               set(),
    _S.REJECTED:               set(),
    _S.CANCELLED:              set(),
}

# Map a review action → target status.
REVIEW_ACTIONS = {
    "under_review":  _S.UNDER_REVIEW,
    "accept":        _S.ACCEPTED,
    "reject":        _S.REJECTED,
    "more_evidence": _S.MORE_EVIDENCE_REQUIRED,
    "cancel":        _S.CANCELLED,
}

_STATUS_TO_EVENT = {
    _S.SUBMITTED:              _ET.SUBMITTED,
    _S.UNDER_REVIEW:           _ET.UNDER_REVIEW,
    _S.ACCEPTED:               _ET.ACCEPTED,
    _S.REJECTED:               _ET.REJECTED,
    _S.MORE_EVIDENCE_REQUIRED: _ET.MORE_EVIDENCE_REQUIRED,
    _S.CANCELLED:              _ET.CANCELLED,
}


class EvidenceRequestError(Exception):
    """Raised for invalid transitions, missing notes, or scoping violations."""


def _actor_pk(actor):
    return actor if getattr(actor, "pk", None) else None


def _record_event(request, *, event_type, actor=None, from_status="",
                  to_status="", note="", metadata=None):
    return AuditEvidenceRequestEvent.objects.create(
        evidence_request=request, engagement=request.engagement,
        organization=request.organization, actor=_actor_pk(actor),
        event_type=event_type, from_status=from_status, to_status=to_status,
        note=note or "", metadata=metadata or {})


def create_evidence_request(*, engagement, actor, title, gl_finding=None,
                            sad_item=None, description="",
                            request_reason=_R.RequestReason.SUPPORT_FINDING,
                            priority=_R.Priority.MEDIUM, due_date=None,
                            assigned_to=None) -> AuditEvidenceRequest:
    """Create an evidence request (status ``open``) + a ``created`` event."""
    if not title:
        raise EvidenceRequestError("title is required.")
    organization = engagement.organization

    req = AuditEvidenceRequest(
        engagement=engagement, organization=organization,
        gl_finding=gl_finding, sad_item=sad_item,
        requested_by=_actor_pk(actor), assigned_to=_actor_pk(assigned_to),
        title=title, description=description or "",
        request_reason=request_reason, priority=priority, due_date=due_date,
        status=_S.OPEN)
    # full_clean runs the org/engagement/link validation in the model.
    req.full_clean(exclude=["requested_by", "assigned_to"])
    with transaction.atomic():
        req.save()
        _record_event(req, event_type=_ET.CREATED, actor=actor, to_status=_S.OPEN)
    return req


def _compute_file_meta(uploaded_file):
    """Return (sha256, size_bytes) for an uploaded file, rewinding it after."""
    sha = hashlib.sha256()
    size = 0
    for chunk in uploaded_file.chunks():
        sha.update(chunk)
        size += len(chunk)
    try:
        uploaded_file.seek(0)
    except Exception:  # pragma: no cover - some backends are non-seekable
        pass
    return sha.hexdigest(), size


def add_attachment(*, request, actor, uploaded_file=None, document=None,
                   description="", original_filename="", content_type="") -> AuditEvidenceAttachment:
    """Attach a file/Document to a request. Not allowed on final requests."""
    if request.is_final:
        raise EvidenceRequestError(
            f"cannot attach evidence to a {request.status} request.")
    if uploaded_file is None and document is None:
        raise EvidenceRequestError("an uploaded file or a document is required.")

    sha256, size = "", 0
    if uploaded_file is not None:
        sha256, size = _compute_file_meta(uploaded_file)
        original_filename = original_filename or getattr(uploaded_file, "name", "")
        content_type = content_type or getattr(uploaded_file, "content_type", "") or ""

    with transaction.atomic():
        att = AuditEvidenceAttachment.objects.create(
            evidence_request=request, engagement=request.engagement,
            organization=request.organization, uploaded_by=_actor_pk(actor),
            document=document, uploaded_file=uploaded_file,
            original_filename=original_filename or "",
            file_sha256=sha256, content_type=content_type or "", size_bytes=size,
            description=description or "")
        _record_event(request, event_type=_ET.ATTACHMENT_ADDED, actor=actor,
                      note=description or "",
                      metadata={"attachment_id": str(att.id),
                                "filename": att.original_filename})
    return att


def _transition(request, *, to_status, actor, note=""):
    """Validated status transition + event. Returns the refreshed request."""
    from_status = request.status
    if to_status not in ALLOWED_TRANSITIONS.get(from_status, set()):
        raise EvidenceRequestError(
            f"invalid transition {from_status} → {to_status}.")
    if to_status in _R.NOTE_REQUIRED_STATUSES and not (note or "").strip():
        raise EvidenceRequestError(
            f"a reviewer note is required to set status {to_status}.")

    now = timezone.now()
    request.status = to_status
    fields = ["status", "updated_at"]
    if to_status == _S.SUBMITTED:
        request.submitted_at = now
        fields.append("submitted_at")
    if to_status in (_S.ACCEPTED, _S.REJECTED, _S.MORE_EVIDENCE_REQUIRED):
        request.reviewed_by = _actor_pk(actor)
        request.reviewed_at = now
        request.reviewer_note = note or ""
        fields += ["reviewed_by", "reviewed_at", "reviewer_note"]

    with transaction.atomic():
        request.save(update_fields=fields)
        _record_event(request, event_type=_STATUS_TO_EVENT[to_status], actor=actor,
                      from_status=from_status, to_status=to_status, note=note or "")
    return request


def submit_evidence(*, request, actor) -> AuditEvidenceRequest:
    """Move ``open``/``more_evidence_required`` → ``submitted``."""
    return _transition(request, to_status=_S.SUBMITTED, actor=actor)


def review_evidence_request(*, request, actor, action, note="") -> AuditEvidenceRequest:
    """Apply a review action: under_review / accept / reject / more_evidence / cancel.

    Accepting requires at least one active attachment unless the request reason
    is explanation-only (``management_explanation``).
    """
    if action not in REVIEW_ACTIONS:
        raise EvidenceRequestError(f"unknown review action: {action}.")
    to_status = REVIEW_ACTIONS[action]

    if to_status == _S.ACCEPTED:
        explanation_only = request.request_reason in _R.EXPLANATION_ONLY_REASONS
        has_attachment = request.attachments.filter(is_active=True).exists()
        if not has_attachment and not explanation_only:
            raise EvidenceRequestError(
                "cannot accept: at least one attachment is required "
                "(unless the request reason is management_explanation).")

    return _transition(request, to_status=to_status, actor=actor, note=note)


def open_evidence_request_count(*, engagement=None, organization=None) -> int:
    """Count non-final evidence requests (open evidence gaps) for a scope."""
    qs = AuditEvidenceRequest.objects.exclude(status__in=_R.FINAL_STATUSES)
    if engagement is not None:
        qs = qs.filter(engagement=engagement)
    if organization is not None:
        qs = qs.filter(organization=organization)
    return qs.count()
