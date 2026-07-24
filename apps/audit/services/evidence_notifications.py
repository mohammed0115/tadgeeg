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
