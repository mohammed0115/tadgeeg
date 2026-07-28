"""Audit issue service (TADGEEG-G3.2) — issue → remediation → closure loop."""
from __future__ import annotations

from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.utils import timezone

from apps.audit.issue_models import AuditIssue

_I = AuditIssue
_St = _I.Status
_VALID_STATUS = {s.value for s in _St}


class AuditIssueError(Exception):
    """Invalid input or scoping violation."""


def _next_reference(organization) -> str:
    count = AuditIssue.objects.filter(organization=organization).count()
    return f"ISSUE-{count + 1:05d}"


def create_issue(*, engagement, actor, title, description="", severity=None,
                 assessed_risk=None, gl_finding=None, owner="", owner_user=None,
                 due_date=None, remediation_plan="") -> AuditIssue:
    if not (title or "").strip():
        raise AuditIssueError("title is required.")
    obj = AuditIssue(
        engagement=engagement, organization=engagement.organization,
        title=title.strip()[:255], description=description or "",
        severity=severity or _I.Severity.MEDIUM,
        assessed_risk=assessed_risk, gl_finding=gl_finding,
        owner=(owner or "")[:160], owner_user=owner_user, due_date=due_date or None,
        remediation_plan=remediation_plan or "",
        raised_by=actor if getattr(actor, "pk", None) else None,
        status=_St.OPEN)
    obj.full_clean(exclude=["raised_by", "reference", "owner_user"])
    with transaction.atomic():
        for attempt in range(5):
            obj.reference = _next_reference(engagement.organization)
            try:
                with transaction.atomic():
                    obj.save()
                break
            except IntegrityError:
                if attempt == 4:
                    raise
    return obj


def set_status(*, issue, actor, status, note="") -> AuditIssue:
    if status not in _VALID_STATUS:
        raise AuditIssueError(f"invalid status: {status!r}")
    issue.status = status
    fields = ["status", "updated_at"]
    if status in _I.CLOSED_STATUSES and issue.closed_at is None:
        issue.closed_at = timezone.now()
        fields.append("closed_at")
    if status not in _I.CLOSED_STATUSES and issue.closed_at is not None:
        issue.closed_at = None
        fields.append("closed_at")
    if note:
        issue.management_response = note
        fields.append("management_response")
    issue.save(update_fields=fields)
    return issue


def record_remediation(*, issue, actor, remediation_plan="", owner="",
                       due_date=None) -> AuditIssue:
    """Capture the remediation plan/owner/due date; move OPEN → IN_REMEDIATION."""
    fields = ["updated_at"]
    if remediation_plan:
        issue.remediation_plan = remediation_plan; fields.append("remediation_plan")
    if owner:
        issue.owner = owner[:160]; fields.append("owner")
    if due_date:
        issue.due_date = due_date; fields.append("due_date")
    if issue.status == _St.OPEN:
        issue.status = _St.IN_REMEDIATION; fields.append("status")
    issue.save(update_fields=fields)
    return issue


def list_issues(*, engagement, status=None, limit=500):
    qs = (AuditIssue.objects.filter(engagement=engagement)
          .select_related("assessed_risk", "gl_finding", "owner_user", "raised_by"))
    if status:
        qs = qs.filter(status=status)
    return list(qs[:limit])


def summary(*, organization, engagement=None) -> dict:
    qs = AuditIssue.objects.filter(organization=organization)
    if engagement is not None:
        qs = qs.filter(engagement=engagement)
    today = timezone.now().date()
    open_q = ~Q(status__in=list(_I.CLOSED_STATUSES))
    # Prefix the per-status counts (``c_*``) so they don't collide with the
    # semantic keys (``open`` = not-closed, etc.).
    agg = qs.aggregate(
        total=Count("id"),
        overdue=Count("id", filter=open_q & Q(due_date__lt=today)),
        critical=Count("id", filter=Q(severity="critical")),
        **{f"c_{s.value}": Count("id", filter=Q(status=s.value)) for s in _St})
    per_status = {s.value: (agg[f"c_{s.value}"] or 0) for s in _St}
    not_closed = sum(v for k, v in per_status.items()
                     if k not in {s.value for s in _I.CLOSED_STATUSES})
    return {
        "total": agg["total"] or 0,
        "open": not_closed,
        "overdue": agg["overdue"] or 0,
        "critical": agg["critical"] or 0,
        **per_status,
    }
