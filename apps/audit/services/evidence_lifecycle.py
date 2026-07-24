"""Evidence delivery & lifecycle service (TADGEEG-FIN-AUDIT-6C).

Completes the evidence lifecycle on top of 6A/6B — it does not replace them.
Reuses ``AuditEvidenceRequest`` / ``AuditEvidenceAttachment`` /
``AuditEvidenceRequestEvent`` and the ``evidence_request`` service's append-only
event recorder and notification wrappers.

Capabilities:
  * secure download with SHA-256 re-verification BEFORE any byte is served;
  * archive / restore / freeze (never a hard delete, never an overwrite);
  * retention states (active · archived · frozen · expired);
  * the auditor review queue, bulk reviewer assignment, SLA escalation;
  * a dashboard summary (incl. average review time).

Nothing here writes to ``apps.ledger``, uses AI, or issues an audit opinion.
"""
from __future__ import annotations

import hashlib

from django.db import transaction
from django.db.models import Avg, Count, F, Max, Q
from django.utils import timezone

from apps.audit.evidence_models import (
    AuditEvidenceAttachment,
    AuditEvidenceRequest,
    AuditEvidenceRequestEvent,
)
from apps.audit.services import evidence_notifications as ev_notify
from apps.audit.services.evidence_request import (
    EvidenceRequestError,
    _record_event,
    assign_users,
)

_A = AuditEvidenceAttachment
_L = _A.Lifecycle
_R = AuditEvidenceRequest
_S = _R.Status
_ET = AuditEvidenceRequestEvent.EventType

# Read files in chunks when hashing so a large ZIP never loads twice over.
_HASH_CHUNK = 1024 * 1024


class EvidenceIntegrityError(Exception):
    """Raised when stored bytes no longer match the recorded SHA-256."""


class EvidenceLifecycleError(Exception):
    """Raised for invalid lifecycle transitions (e.g. modifying frozen evidence)."""


def _attachment_event(attachment, *, event_type, actor=None, note="", metadata=None):
    """Append an attachment-scoped entry to the SAME immutable request trail."""
    event = _record_event(
        attachment.evidence_request, event_type=event_type, actor=actor,
        note=note, metadata=metadata or {})
    # Link the event to the attachment (single trail, no second event model).
    event.attachment = attachment
    event.save(update_fields=["attachment"])
    return event


# ─────────────────────────────────────────────────────────────────────────────
# PART 2 — SHA-256 verification
# ─────────────────────────────────────────────────────────────────────────────
def _read_and_hash(attachment) -> tuple[bytes, str]:
    """Read the stored file once, returning (bytes, sha256 hexdigest)."""
    fh = attachment.uploaded_file
    if not fh:
        raise EvidenceIntegrityError("attachment has no stored file.")
    sha = hashlib.sha256()
    chunks = []
    try:
        fh.open("rb")
    except FileNotFoundError as exc:
        # 6D: the row exists but the stored bytes are gone. Report it as an
        # integrity problem instead of crashing the caller (sweep/download).
        raise EvidenceIntegrityError(
            f"stored file is missing from storage: {exc}") from exc
    except OSError as exc:
        raise EvidenceIntegrityError(f"stored file is unreadable: {exc}") from exc
    try:
        while True:
            chunk = fh.read(_HASH_CHUNK)
            if not chunk:
                break
            sha.update(chunk)
            chunks.append(chunk)
    except OSError as exc:
        raise EvidenceIntegrityError(f"stored file is unreadable: {exc}") from exc
    finally:
        try:
            fh.close()
        except Exception:  # pragma: no cover - some backends auto-close
            pass
    return b"".join(chunks), sha.hexdigest()


def verify_attachment(attachment, *, actor=None, record=True) -> dict:
    """Recompute the SHA-256 and compare it with the stored digest.

    Records a ``verified`` / ``verification_failed`` event (append-only) and
    updates the verification bookkeeping. Returns a result dict; it does NOT
    raise on mismatch so callers can decide how to surface it.
    """
    expected = attachment.file_sha256 or ""
    try:
        _, actual = _read_and_hash(attachment)
        ok = bool(expected) and actual == expected
        error = "" if expected else "no stored SHA-256 to compare against."
    except EvidenceIntegrityError as exc:
        ok, actual, error = False, "", str(exc)

    attachment.last_verified_at = timezone.now()
    attachment.last_verification_ok = ok
    attachment.save(update_fields=["last_verified_at", "last_verification_ok"])

    if record:
        _attachment_event(
            attachment,
            event_type=_ET.VERIFIED if ok else _ET.VERIFICATION_FAILED,
            actor=actor,
            note="" if ok else (error or "stored bytes do not match the recorded SHA-256."),
            metadata={"expected_sha256": expected, "actual_sha256": actual})
    return {"ok": ok, "expected": expected, "actual": actual, "error": error}


# ─────────────────────────────────────────────────────────────────────────────
# PART 1 — Secure download (integrity-checked before serving)
# ─────────────────────────────────────────────────────────────────────────────
def read_for_download(attachment, *, actor) -> bytes:
    """Return the file bytes ONLY if the SHA-256 still matches.

    Corrupted evidence is never served: the digest is recomputed first and a
    ``verification_failed`` event is written before raising.
    """
    if attachment.is_expired:
        raise EvidenceLifecycleError("attachment retention has expired.")
    try:
        data, actual = _read_and_hash(attachment)
    except EvidenceIntegrityError as exc:
        attachment.last_verified_at = timezone.now()
        attachment.last_verification_ok = False
        attachment.save(update_fields=["last_verified_at", "last_verification_ok"])
        _attachment_event(attachment, event_type=_ET.VERIFICATION_FAILED,
                          actor=actor, note=str(exc))
        raise

    expected = attachment.file_sha256 or ""
    ok = bool(expected) and actual == expected
    attachment.last_verified_at = timezone.now()
    attachment.last_verification_ok = ok
    attachment.save(update_fields=["last_verified_at", "last_verification_ok"])

    if not ok:
        _attachment_event(
            attachment, event_type=_ET.VERIFICATION_FAILED, actor=actor,
            note="stored bytes do not match the recorded SHA-256; download refused.",
            metadata={"expected_sha256": expected, "actual_sha256": actual})
        raise EvidenceIntegrityError(
            "integrity check failed: this evidence file does not match its "
            "recorded SHA-256 and will not be served.")

    _attachment_event(attachment, event_type=_ET.DOWNLOADED, actor=actor,
                      metadata={"sha256": actual, "version": attachment.version})
    return data


# ─────────────────────────────────────────────────────────────────────────────
# PART 5/6 — Archive · Restore · Freeze · Retention
# ─────────────────────────────────────────────────────────────────────────────
def _set_lifecycle(attachment, *, state, actor, event_type, note=""):
    if attachment.is_frozen and state != _L.FROZEN:
        raise EvidenceLifecycleError(
            "this attachment is frozen and can no longer be modified.")
    with transaction.atomic():
        attachment.lifecycle_state = state
        # Mirror into the pre-6C boolean so existing queries stay correct.
        attachment.is_active = state in (_L.ACTIVE, _L.FROZEN)
        attachment.lifecycle_changed_at = timezone.now()
        attachment.lifecycle_changed_by = actor if getattr(actor, "pk", None) else None
        attachment.save(update_fields=[
            "lifecycle_state", "is_active", "lifecycle_changed_at",
            "lifecycle_changed_by"])
        _attachment_event(attachment, event_type=event_type, actor=actor, note=note,
                          metadata={"lifecycle_state": state})
    return attachment


def archive_attachment(*, attachment, actor, note=""):
    """Retire evidence WITHOUT deleting it (it stays readable and auditable)."""
    if attachment.is_archived:
        return attachment
    return _set_lifecycle(attachment, state=_L.ARCHIVED, actor=actor,
                          event_type=_ET.ARCHIVED, note=note)


def restore_attachment(*, attachment, actor, note=""):
    """Bring archived evidence back to active."""
    if attachment.is_frozen:
        raise EvidenceLifecycleError("frozen evidence cannot be restored.")
    if attachment.lifecycle_state == _L.ACTIVE:
        return attachment
    return _set_lifecycle(attachment, state=_L.ACTIVE, actor=actor,
                          event_type=_ET.RESTORED, note=note)


def freeze_attachment(*, attachment, actor, note=""):
    """Freeze evidence — a terminal state that blocks any further modification."""
    if attachment.is_frozen:
        return attachment
    return _set_lifecycle(attachment, state=_L.FROZEN, actor=actor,
                          event_type=_ET.FROZEN, note=note)


def mark_expired(*, attachment, actor=None, note=""):
    """Flag retention expiry. Never deletes bytes — evidence stays recoverable."""
    if attachment.is_frozen:
        raise EvidenceLifecycleError("frozen evidence cannot expire.")
    return _set_lifecycle(attachment, state=_L.EXPIRED, actor=actor,
                          event_type=_ET.EXPIRED, note=note)


def set_retention(*, attachment, actor, retention_until):
    """Set/clear the retention date (blocked on frozen evidence)."""
    if attachment.is_frozen:
        raise EvidenceLifecycleError("frozen evidence cannot be modified.")
    attachment.retention_until = retention_until
    attachment.save(update_fields=["retention_until"])
    _attachment_event(attachment, event_type=_ET.NOTE_ADDED, actor=actor,
                      note=f"retention_until set to {retention_until}")
    return attachment


# ─────────────────────────────────────────────────────────────────────────────
# PART 3 — Versioning
# ─────────────────────────────────────────────────────────────────────────────
def next_version_for(request) -> int:
    """Next version ordinal within a request (versions are never reused)."""
    return (AuditEvidenceAttachment.objects
            .filter(evidence_request=request)
            .aggregate(mx=Max("version"))["mx"] or 0) + 1


def version_history(request):
    """All versions for a request, oldest first — including archived/expired."""
    return (AuditEvidenceAttachment.objects
            .filter(evidence_request=request)
            .select_related("uploaded_by", "replaces")
            .order_by("version", "uploaded_at"))


def supersede(*, attachment, replacement, actor, note=""):
    """Link ``replacement`` as the new version of ``attachment`` and archive it."""
    if attachment.is_frozen:
        raise EvidenceLifecycleError("frozen evidence cannot be superseded.")
    with transaction.atomic():
        replacement.replaces = attachment
        replacement.save(update_fields=["replaces"])
        _attachment_event(replacement, event_type=_ET.VERSION_CREATED, actor=actor,
                          note=note,
                          metadata={"replaces": str(attachment.id),
                                    "version": replacement.version})
        archive_attachment(attachment=attachment, actor=actor,
                           note="superseded by a newer version")
    return replacement


# ─────────────────────────────────────────────────────────────────────────────
# PART 7 — Auditor evidence queue
# ─────────────────────────────────────────────────────────────────────────────
QUEUE_SORTS = {
    "due_date": "due_date",
    "-due_date": "-due_date",
    "priority": "priority",
    "created": "created_at",
    "-created": "-created_at",
    "updated": "-updated_at",
}


def auditor_queue(*, organization, engagement=None, status=None, priority=None,
                  assigned_to=None, search="", bucket="", sort="-created"):
    """Organization-scoped auditor review queue with filters/search/sorting."""
    qs = (AuditEvidenceRequest.objects
          .filter(organization=organization)
          .select_related("engagement", "requested_by", "assigned_to",
                          "assigned_client_user", "gl_finding", "sad_item"))
    if engagement:
        qs = qs.filter(engagement_id=engagement)
    if status:
        qs = qs.filter(status=status)
    if priority:
        qs = qs.filter(priority=priority)
    if assigned_to:
        qs = qs.filter(assigned_to_id=assigned_to)

    today = timezone.now().date()
    if bucket == "waiting_review":
        qs = qs.filter(status__in=[_S.SUBMITTED, _S.UNDER_REVIEW])
    elif bucket == "overdue":
        qs = qs.filter(due_date__lt=today).exclude(status__in=_R.FINAL_STATUSES)
    elif bucket == "due_today":
        qs = qs.filter(due_date=today).exclude(status__in=_R.FINAL_STATUSES)
    elif bucket == "accepted_today":
        qs = qs.filter(status=_S.ACCEPTED, reviewed_at__date=today)
    elif bucket == "rejected":
        qs = qs.filter(status=_S.REJECTED)
    elif bucket == "more_evidence":
        qs = qs.filter(status=_S.MORE_EVIDENCE_REQUIRED)
    elif bucket == "high_priority":
        qs = qs.filter(priority__in=[_R.Priority.HIGH, _R.Priority.CRITICAL])

    if search:
        qs = qs.filter(
            Q(title__icontains=search)
            | Q(request_number__icontains=search)
            | Q(description__icontains=search)
            | Q(gl_finding__risk_code__icontains=search)
            | Q(gl_finding__account_code__icontains=search)
            | Q(sad_item__account_code__icontains=search))

    return qs.order_by(QUEUE_SORTS.get(sort, "-created_at"))


def queue_counts(*, organization, engagement=None) -> dict:
    """Counts for every queue bucket (single aggregate query)."""
    qs = AuditEvidenceRequest.objects.filter(organization=organization)
    if engagement:
        qs = qs.filter(engagement_id=engagement)
    today = timezone.now().date()
    final = list(_R.FINAL_STATUSES)
    return qs.aggregate(
        waiting_review=Count("id", filter=Q(status__in=[_S.SUBMITTED, _S.UNDER_REVIEW])),
        overdue=Count("id", filter=Q(due_date__lt=today) & ~Q(status__in=final)),
        due_today=Count("id", filter=Q(due_date=today) & ~Q(status__in=final)),
        accepted_today=Count("id", filter=Q(status=_S.ACCEPTED, reviewed_at__date=today)),
        rejected=Count("id", filter=Q(status=_S.REJECTED)),
        more_evidence=Count("id", filter=Q(status=_S.MORE_EVIDENCE_REQUIRED)),
        high_priority=Count("id", filter=Q(
            priority__in=[_R.Priority.HIGH, _R.Priority.CRITICAL]) & ~Q(status__in=final)),
    )


# ─────────────────────────────────────────────────────────────────────────────
# PART 8 — Bulk reviewer assignment (single transaction)
# ─────────────────────────────────────────────────────────────────────────────
def bulk_assign_reviewer(*, organization, request_ids, reviewer, actor) -> dict:
    """Assign one reviewer to many requests atomically.

    Skips requests outside the organization or already final; returns a summary.
    Reuses ``evidence_request.assign_users`` so assignment rules and the
    append-only event trail are identical to the single-request path.
    """
    if reviewer is not None and getattr(reviewer, "organization_id", None) != organization.id:
        raise EvidenceRequestError("reviewer must belong to the same organization.")

    requests = list(AuditEvidenceRequest.objects.filter(
        organization=organization, id__in=list(request_ids or [])))
    found_ids = {str(r.id) for r in requests}
    missing = [str(i) for i in (request_ids or []) if str(i) not in found_ids]

    assigned, skipped = [], []
    with transaction.atomic():
        for req in requests:
            if req.is_final:
                skipped.append(str(req.id))
                continue
            assign_users(request=req, actor=actor, assigned_to=reviewer)
            assigned.append(str(req.id))
            ev_notify.notify_assignment_changed(req, actor=actor)
    return {"assigned": assigned, "skipped_final": skipped, "not_found": missing,
            "assigned_count": len(assigned)}


# ─────────────────────────────────────────────────────────────────────────────
# PART 9 — SLA escalation (never auto-closes anything)
# ─────────────────────────────────────────────────────────────────────────────
def escalate_overdue(*, organization=None, actor=None, notify=True) -> dict:
    """Record an escalation event for overdue requests + notify.

    Idempotent per day: a request that already has an ``escalated`` event today
    is not escalated again. NEVER changes a request's status.
    """
    today = timezone.now().date()
    qs = AuditEvidenceRequest.objects.exclude(status__in=list(_R.FINAL_STATUSES)) \
        .filter(due_date__lt=today)
    if organization is not None:
        qs = qs.filter(organization=organization)

    escalated = []
    for req in qs.select_related("assigned_to", "assigned_client_user", "organization"):
        already = req.events.filter(
            event_type=_ET.ESCALATED, created_at__date=today).exists()
        if already:
            continue
        _record_event(req, event_type=_ET.ESCALATED, actor=actor,
                      note=f"Overdue by {abs(req.days_remaining or 0)} day(s).",
                      metadata={"due_date": str(req.due_date)})
        if notify:
            ev_notify.notify_overdue(req)
        escalated.append(str(req.id))
    return {"escalated": escalated, "count": len(escalated)}


def notify_due_tomorrow(*, organization=None) -> dict:
    """Send "due tomorrow" reminders. Records nothing — purely a notification."""
    from datetime import timedelta
    tomorrow = timezone.now().date() + timedelta(days=1)
    qs = AuditEvidenceRequest.objects.exclude(status__in=list(_R.FINAL_STATUSES)) \
        .filter(due_date=tomorrow)
    if organization is not None:
        qs = qs.filter(organization=organization)
    sent = 0
    for req in qs.select_related("assigned_client_user", "assigned_to", "organization"):
        if ev_notify.notify_due_tomorrow(req):
            sent += 1
    return {"notified": sent}


# ─────────────────────────────────────────────────────────────────────────────
# PART 10 — Dashboard summary
# ─────────────────────────────────────────────────────────────────────────────
def dashboard_summary(*, organization, engagement=None) -> dict:
    """Cards for the evidence dashboard, including average review time."""
    qs = AuditEvidenceRequest.objects.filter(organization=organization)
    if engagement:
        qs = qs.filter(engagement_id=engagement)
    today = timezone.now().date()
    final = list(_R.FINAL_STATUSES)

    summary = qs.aggregate(
        waiting=Count("id", filter=Q(status__in=[_S.SUBMITTED, _S.UNDER_REVIEW])),
        pending_reviews=Count("id", filter=Q(status=_S.UNDER_REVIEW)),
        accepted=Count("id", filter=Q(status=_S.ACCEPTED)),
        rejected=Count("id", filter=Q(status=_S.REJECTED)),
        overdue=Count("id", filter=Q(due_date__lt=today) & ~Q(status__in=final)),
        more_evidence=Count("id", filter=Q(status=_S.MORE_EVIDENCE_REQUIRED)),
    )

    # Average review time = reviewed_at − submitted_at over reviewed requests.
    reviewed = qs.filter(reviewed_at__isnull=False, submitted_at__isnull=False)
    avg = reviewed.aggregate(
        avg=Avg(F("reviewed_at") - F("submitted_at")))["avg"]
    summary["avg_review_hours"] = round(avg.total_seconds() / 3600, 1) if avg else None
    summary["avg_review_display"] = (
        f"{summary['avg_review_hours']} h" if summary["avg_review_hours"] is not None else "—")
    return summary


# ─────────────────────────────────────────────────────────────────────────────
# Access control helpers (shared by API + frontend)
# ─────────────────────────────────────────────────────────────────────────────
def is_auditor(user) -> bool:
    try:
        return bool(user.has_role_capability("approve_invoices"))
    except Exception:
        return False


def can_access_attachment(user, attachment) -> bool:
    """Auditors, or the client assigned to the attachment's request, may read it.

    Organization is checked by the caller's scoped lookup; this is the second
    layer (assigned-client-only visibility).
    """
    if getattr(user, "organization_id", None) != attachment.organization_id:
        return False
    if is_auditor(user):
        return True
    return attachment.evidence_request.assigned_client_user_id == getattr(user, "pk", None)


def scoped_attachment(user, pk):
    """Organization-scoped attachment lookup honouring client visibility."""
    org = getattr(user, "organization", None)
    if org is None or not pk:
        return None
    att = (AuditEvidenceAttachment.objects
           .filter(pk=pk, organization=org)
           .select_related("evidence_request", "uploaded_by", "organization")
           .first())
    if att is None or not can_access_attachment(user, att):
        return None  # 404 — never leak existence
    return att
