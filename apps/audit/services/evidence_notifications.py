"""Evidence-request system notifications (TADGEEG-FIN-AUDIT-6B).

Thin, additive wrapper over the EXISTING ``apps.notifications`` service — no
parallel notification model or delivery channel is introduced. In-app/system
notifications only (no email/SMS/push here).

Notification matrix:
  * request created            → assigned CLIENT user
  * evidence files uploaded    → assigned AUDITOR (+ requester)
  * accepted / rejected /
    more evidence required     → assigned CLIENT user

Every helper is best-effort: ``notifications.services.notify`` already swallows
and logs its own failures, so a notification problem can never break the
evidence workflow.
"""
from __future__ import annotations

from apps.notifications.models import Notification
from apps.notifications.services import notify

_SOURCE_TYPE = "audit_evidence_request"


def _link(request) -> str:
    """Deep link to the auditor-side detail page for this request."""
    return f"/audit/evidence/{request.id}/"


def _client_link(request) -> str:
    """Deep link to the client-portal detail page for this request."""
    return f"/audit/client-evidence/{request.id}/"


def _label(request) -> str:
    return request.request_number or str(request.id)


def notify_request_created(request):
    """Tell the assigned client user that evidence has been requested."""
    if not request.assigned_client_user_id:
        return None
    return notify(
        request.assigned_client_user,
        title=f"Evidence requested: {_label(request)}",
        message=request.title,
        severity=Notification.Severity.INFO,
        category=Notification.Category.AUDIT,
        link=_client_link(request),
        source_type=_SOURCE_TYPE,
        source_id=str(request.id),
        organization=request.organization,
    )


def notify_evidence_uploaded(request, *, actor=None, count=1):
    """Tell the auditor side that the client uploaded evidence."""
    recipients = []
    for user in (request.assigned_to, request.requested_by):
        if user and user.pk and user.pk not in [u.pk for u in recipients]:
            recipients.append(user)
    # Don't notify the actor about their own upload.
    recipients = [u for u in recipients if not (actor and u.pk == getattr(actor, "pk", None))]

    out = []
    for user in recipients:
        out.append(notify(
            user,
            title=f"Evidence uploaded: {_label(request)}",
            message=f"{count} file(s) uploaded for “{request.title}”.",
            severity=Notification.Severity.INFO,
            category=Notification.Category.UPLOAD,
            link=_link(request),
            source_type=_SOURCE_TYPE,
            source_id=str(request.id),
            organization=request.organization,
        ))
    return out


_REVIEW_TITLES = {
    "accepted": ("Evidence accepted", Notification.Severity.SUCCESS),
    "rejected": ("Evidence rejected", Notification.Severity.WARNING),
    "more_evidence_required": ("More evidence required", Notification.Severity.WARNING),
}


def notify_review_outcome(request, *, to_status, note=""):
    """Tell the assigned client user the outcome of the auditor's review."""
    entry = _REVIEW_TITLES.get(to_status)
    if entry is None or not request.assigned_client_user_id:
        return None
    title, severity = entry
    return notify(
        request.assigned_client_user,
        title=f"{title}: {_label(request)}",
        message=note or request.title,
        severity=severity,
        category=Notification.Category.AUDIT,
        link=_client_link(request),
        source_type=_SOURCE_TYPE,
        source_id=str(request.id),
        organization=request.organization,
    )


# ── TADGEEG-FIN-AUDIT-6C — lifecycle notifications ───────────────────────────
def notify_assignment_changed(request, *, actor=None):
    """Tell the newly assigned auditor that a request is now theirs."""
    reviewer = request.assigned_to
    if not reviewer or not reviewer.pk:
        return None
    if actor is not None and reviewer.pk == getattr(actor, "pk", None):
        return None  # don't notify someone about their own action
    return notify(
        reviewer,
        title=f"Evidence assigned to you: {_label(request)}",
        message=request.title,
        severity=Notification.Severity.INFO,
        category=Notification.Category.AUDIT,
        link=_link(request),
        source_type=_SOURCE_TYPE,
        source_id=str(request.id),
        organization=request.organization,
    )


def notify_due_tomorrow(request):
    """Remind the client (and reviewer) that evidence is due tomorrow."""
    sent = None
    for user, link in ((request.assigned_client_user, _client_link(request)),
                       (request.assigned_to, _link(request))):
        if not user or not user.pk:
            continue
        sent = notify(
            user,
            title=f"Evidence due tomorrow: {_label(request)}",
            message=request.title,
            severity=Notification.Severity.WARNING,
            category=Notification.Category.AUDIT,
            link=link,
            source_type=_SOURCE_TYPE,
            source_id=str(request.id),
            organization=request.organization,
        ) or sent
    return sent


def notify_overdue(request):
    """Escalation notice: the request passed its due date."""
    sent = None
    for user, link in ((request.assigned_client_user, _client_link(request)),
                       (request.assigned_to, _link(request))):
        if not user or not user.pk:
            continue
        sent = notify(
            user,
            title=f"Evidence OVERDUE: {_label(request)}",
            message=request.title,
            severity=Notification.Severity.DANGER,
            category=Notification.Category.AUDIT,
            link=link,
            source_type=_SOURCE_TYPE,
            source_id=str(request.id),
            organization=request.organization,
        ) or sent
    return sent


# ── TADGEEG-FIN-AUDIT-6D — assurance notifications (AUDITORS ONLY) ───────────
# These are internal quality signals; clients are never notified.
_AUDITOR_CAPABILITY = "approve_invoices"


def _org_auditors(organization):
    """Users in the organization holding the auditor review capability."""
    from apps.authentication.models import User
    out = []
    for user in User.objects.filter(organization=organization, is_active=True):
        try:
            if user.has_role_capability(_AUDITOR_CAPABILITY):
                out.append(user)
        except Exception:  # pragma: no cover - defensive
            continue
    return out


def notify_integrity_failure(attachment, *, result="", error=""):
    """Alert auditors that an attachment failed integrity verification."""
    req = attachment.evidence_request
    label = req.request_number or str(req.id) if req else str(attachment.id)
    sent = []
    for user in _org_auditors(attachment.organization):
        sent.append(notify(
            user,
            title=f"Evidence integrity FAILED: {label}",
            message=(f"{attachment.original_filename or attachment.id}: "
                     f"{result} {error}").strip(),
            severity=Notification.Severity.DANGER,
            category=Notification.Category.SECURITY,
            link=_link(req) if req else "",
            source_type=_SOURCE_TYPE,
            source_id=str(attachment.id),
            organization=attachment.organization,
        ))
    return sent


def notify_coverage_below_threshold(organization, *, coverage_percent,
                                    threshold, engagement=None):
    """Alert auditors that evidence coverage dropped below the threshold."""
    scope = f" for {engagement}" if engagement is not None else ""
    sent = []
    for user in _org_auditors(organization):
        sent.append(notify(
            user,
            title=f"Evidence coverage below {threshold}%",
            message=f"Current evidence coverage is {coverage_percent}%{scope}.",
            severity=Notification.Severity.WARNING,
            category=Notification.Category.AUDIT,
            link="/audit/assurance/coverage/",
            source_type=_SOURCE_TYPE,
            source_id="coverage",
            organization=organization,
        ))
    return sent


def notify_evidence_expired(organization, *, count):
    """Alert auditors that evidence has passed its retention date."""
    sent = []
    for user in _org_auditors(organization):
        sent.append(notify(
            user,
            title="Evidence retention expired",
            message=(f"{count} evidence file(s) passed their retention date. "
                     "Nothing was deleted — auditor review required."),
            severity=Notification.Severity.WARNING,
            category=Notification.Category.AUDIT,
            link="/audit/assurance/retention/",
            source_type=_SOURCE_TYPE,
            source_id="retention",
            organization=organization,
        ))
    return sent


def notify_verification_completed(organization, *, stats):
    """Tell auditors an integrity sweep finished, with its headline numbers."""
    sent = []
    for user in _org_auditors(organization):
        sent.append(notify(
            user,
            title="Evidence integrity sweep completed",
            message=(f"Checked {stats.get('checked', 0)} · "
                     f"verified {stats.get('ok', 0)} · "
                     f"failed {stats.get('failed', 0)}."),
            severity=(Notification.Severity.WARNING if stats.get("failed")
                      else Notification.Severity.SUCCESS),
            category=Notification.Category.AUDIT,
            link="/audit/assurance/integrity/",
            source_type=_SOURCE_TYPE,
            source_id="sweep",
            organization=organization,
        ))
    return sent
