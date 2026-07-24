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
import os

from django.db import IntegrityError, transaction
from django.db.models import Count, Max, Q
from django.utils import timezone

from apps.audit.evidence_models import (
    AuditEvidenceAttachment,
    AuditEvidenceRequest,
    AuditEvidenceRequestEvent,
)
from apps.audit.services import evidence_notifications as ev_notify

# Sentinel so ``assign_users`` can distinguish "not provided" from "set to None".
_UNSET = object()

# ── TADGEEG-FIN-AUDIT-6B — evidence upload allowlist ─────────────────────────
# Client-facing uploads accept only these formats. Defined here (rather than
# widening the shared ``core.utils.file_validation.SAFE_MIME_TYPES``) so this
# phase cannot loosen validation for any other upload flow in the project.
ALLOWED_EVIDENCE_EXTENSIONS = frozenset({
    ".pdf", ".docx", ".xlsx", ".png", ".jpg", ".jpeg", ".zip",
})
# Executable/script magic bytes that must never be stored as evidence.
_DANGEROUS_SIGNATURES = (
    (b"MZ", "Windows executable"),
    (b"\x7fELF", "Linux executable"),
    (b"\xca\xfe\xba\xbe", "Mach-O binary"),
    (b"#!/", "Shell script"),
    (b"<?php", "PHP script"),
    (b"<%", "ASP script"),
    (b"<script", "Script injection"),
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


def _next_request_number(organization) -> str:
    """Human-readable per-organization request number (``EVR-00042``)."""
    count = AuditEvidenceRequest.objects.filter(organization=organization).count()
    return f"EVR-{count + 1:05d}"


def create_evidence_request(*, engagement, actor, title, gl_finding=None,
                            sad_item=None, description="",
                            request_reason=_R.RequestReason.SUPPORT_FINDING,
                            priority=_R.Priority.MEDIUM, due_date=None,
                            assigned_to=None,
                            assigned_client_user=None) -> AuditEvidenceRequest:
    """Create an evidence request (status ``open``) + a ``created`` event.

    ``assigned_client_user`` (6B) grants that user client-portal access to this
    request and is notified. Both assignees must belong to the same organization.
    """
    if not title:
        raise EvidenceRequestError("title is required.")
    organization = engagement.organization

    for user, label in ((assigned_to, "assigned_to"),
                        (assigned_client_user, "assigned_client_user")):
        if user is not None and getattr(user, "organization_id", None) != organization.id:
            raise EvidenceRequestError(f"{label} must belong to the same organization.")

    req = AuditEvidenceRequest(
        engagement=engagement, organization=organization,
        gl_finding=gl_finding, sad_item=sad_item,
        requested_by=_actor_pk(actor), assigned_to=_actor_pk(assigned_to),
        assigned_client_user=_actor_pk(assigned_client_user),
        title=title, description=description or "",
        request_reason=request_reason, priority=priority, due_date=due_date,
        status=_S.OPEN)
    # full_clean runs the org/engagement/link validation in the model.
    req.full_clean(exclude=["requested_by", "assigned_to", "assigned_client_user",
                            "request_number"])
    with transaction.atomic():
        # Retry a few times so a concurrent create can't break numbering.
        for attempt in range(5):
            req.request_number = _next_request_number(organization)
            try:
                with transaction.atomic():
                    req.save()
                break
            except IntegrityError:
                if attempt == 4:
                    raise
        _record_event(req, event_type=_ET.CREATED, actor=actor, to_status=_S.OPEN)
        if req.assigned_client_user_id:
            _record_event(req, event_type=_ET.ASSIGNED, actor=actor,
                          note=f"Client user assigned: {req.assigned_client_user}",
                          metadata={"assigned_client_user_id": str(req.assigned_client_user_id)})
    ev_notify.notify_request_created(req)
    return req


def assign_users(*, request, actor, assigned_to=_UNSET, assigned_client_user=_UNSET):
    """Assign/reassign the auditor and/or client user (append-only event)."""
    if request.is_final:
        raise EvidenceRequestError(f"cannot reassign a {request.status} request.")

    changed, fields = [], []
    if assigned_to is not _UNSET:
        if assigned_to is not None and getattr(assigned_to, "organization_id", None) != request.organization_id:
            raise EvidenceRequestError("assigned_to must belong to the same organization.")
        request.assigned_to = _actor_pk(assigned_to)
        fields.append("assigned_to")
        changed.append(f"auditor={request.assigned_to or '—'}")
    if assigned_client_user is not _UNSET:
        if assigned_client_user is not None and getattr(assigned_client_user, "organization_id", None) != request.organization_id:
            raise EvidenceRequestError("assigned_client_user must belong to the same organization.")
        request.assigned_client_user = _actor_pk(assigned_client_user)
        fields.append("assigned_client_user")
        changed.append(f"client={request.assigned_client_user or '—'}")

    if not fields:
        return request
    newly_assigned_client = "assigned_client_user" in fields and request.assigned_client_user_id
    with transaction.atomic():
        request.save(update_fields=fields + ["updated_at"])
        _record_event(request, event_type=_ET.ASSIGNED, actor=actor,
                      note="; ".join(changed))
    if newly_assigned_client:
        ev_notify.notify_request_created(request)
    return request


def record_management_explanation(*, request, actor, explanation):
    """Store the client's management explanation (append-only event)."""
    if request.is_final:
        raise EvidenceRequestError(
            f"cannot add a management explanation to a {request.status} request.")
    if not (explanation or "").strip():
        raise EvidenceRequestError("management explanation cannot be empty.")

    with transaction.atomic():
        request.management_explanation = explanation
        request.save(update_fields=["management_explanation", "updated_at"])
        _record_event(request, event_type=_ET.NOTE_ADDED, actor=actor,
                      note=explanation, metadata={"kind": "management_explanation"})
    return request


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


def validate_evidence_file(uploaded_file, filename=""):
    """Validate an evidence upload: extension allowlist, size, and magic bytes.

    Reuses the project's size limits from ``core.utils.file_validation`` and
    rejects anything outside :data:`ALLOWED_EVIDENCE_EXTENSIONS`.
    Raises :class:`EvidenceRequestError` on rejection.
    """
    from core.utils.file_validation import MAX_FILE_SIZE, MAX_ZIP_SIZE

    name = filename or getattr(uploaded_file, "name", "") or ""
    ext = os.path.splitext(name)[1].lower()
    if ext not in ALLOWED_EVIDENCE_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EVIDENCE_EXTENSIONS))
        raise EvidenceRequestError(
            f"file type '{ext or name}' is not allowed. Allowed: {allowed}.")

    size = getattr(uploaded_file, "size", 0) or 0
    limit = MAX_ZIP_SIZE if ext == ".zip" else MAX_FILE_SIZE
    if size > limit:
        raise EvidenceRequestError(
            f"file is too large ({size} bytes); limit is {limit} bytes.")

    # Magic-byte screen for executables/scripts masquerading as documents.
    try:
        uploaded_file.seek(0)
        header = uploaded_file.read(512)
        uploaded_file.seek(0)
    except Exception:  # pragma: no cover - non-seekable backends
        header = b""
    for signature, label in _DANGEROUS_SIGNATURES:
        if header.startswith(signature):
            raise EvidenceRequestError(f"file rejected: looks like a {label}.")
    return {"extension": ext, "size_bytes": size}


def add_attachment(*, request, actor, uploaded_file=None, document=None,
                   description="", original_filename="", content_type="",
                   validate=True, notify_auditor=False,
                   notes="") -> AuditEvidenceAttachment:
    """Attach a file/Document to a request. Not allowed on final requests.

    ``validate`` (6B) applies the evidence upload allowlist; ``notify_auditor``
    sends the "evidence uploaded" system notification (used by client uploads).
    """
    if request.is_final:
        raise EvidenceRequestError(
            f"cannot attach evidence to a {request.status} request.")
    if uploaded_file is None and document is None:
        raise EvidenceRequestError("an uploaded file or a document is required.")

    sha256, size = "", 0
    if uploaded_file is not None:
        if validate:
            validate_evidence_file(uploaded_file, original_filename)
        sha256, size = _compute_file_meta(uploaded_file)
        original_filename = original_filename or getattr(uploaded_file, "name", "")
        content_type = content_type or getattr(uploaded_file, "content_type", "") or ""

    with transaction.atomic():
        # 6C: every upload is a NEW immutable version; nothing is overwritten.
        version = (AuditEvidenceAttachment.objects
                   .filter(evidence_request=request)
                   .aggregate(mx=Max("version"))["mx"] or 0) + 1
        att = AuditEvidenceAttachment.objects.create(
            evidence_request=request, engagement=request.engagement,
            organization=request.organization, uploaded_by=_actor_pk(actor),
            document=document, uploaded_file=uploaded_file,
            original_filename=original_filename or "",
            file_sha256=sha256, content_type=content_type or "", size_bytes=size,
            description=description or "", notes=notes or "", version=version)
        _record_event(request, event_type=_ET.ATTACHMENT_ADDED, actor=actor,
                      note=description or "",
                      metadata={"attachment_id": str(att.id),
                                "filename": att.original_filename,
                                "version": version})
        if version > 1:
            _record_event(request, event_type=_ET.VERSION_CREATED, actor=actor,
                          note=notes or "",
                          metadata={"attachment_id": str(att.id), "version": version})
    if notify_auditor:
        ev_notify.notify_evidence_uploaded(request, actor=actor, count=1)
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
    # 6B: notify the client of the review outcome (accepted/rejected/more).
    ev_notify.notify_review_outcome(request, to_status=to_status, note=note or "")
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


def notify_evidence_uploaded(*, request, actor=None, count=1):
    """Send the "evidence uploaded" notification once for a batch of files."""
    return ev_notify.notify_evidence_uploaded(request, actor=actor, count=count)


def scoped_queryset(*, organization, engagement=None, client_user=None):
    """Base organization-scoped queryset (optionally narrowed to a client user)."""
    qs = AuditEvidenceRequest.objects.filter(organization=organization)
    if engagement is not None:
        qs = qs.filter(engagement=engagement)
    if client_user is not None:
        qs = qs.filter(assigned_client_user=client_user)
    return qs


def status_counts(*, organization, engagement=None, client_user=None) -> dict:
    """Status breakdown + overdue count — powers the dashboard/readiness widgets.

    Returns a dict with one key per status plus ``total``, ``overdue`` and
    ``open_gaps``. Deliberately a SINGLE aggregate query (conditional counts) so
    embedding this widget stays cheap on already query-budgeted pages.
    """
    qs = scoped_queryset(organization=organization, engagement=engagement,
                         client_user=client_user)
    today = timezone.now().date()

    aggregates = {
        s.value: Count("id", filter=Q(status=s.value)) for s in _R.Status
    }
    aggregates["overdue"] = Count(
        "id", filter=Q(due_date__lt=today) & ~Q(status__in=list(_R.FINAL_STATUSES)))
    counts = qs.aggregate(**aggregates)

    counts = {k: (v or 0) for k, v in counts.items()}
    counts["total"] = sum(counts[s.value] for s in _R.Status)
    counts["open_gaps"] = counts["total"] - (
        counts[_S.ACCEPTED] + counts[_S.REJECTED] + counts[_S.CANCELLED])
    return counts
