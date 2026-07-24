"""Auditor Evidence Queue — frontend page (TADGEEG-FIN-AUDIT-6C).

The auditor-side working queue: bucketed counts, filters, search, sorting, and
bulk reviewer assignment in one transaction. Organization-scoped and auditor+
only. Read-only over requests except for the explicit bulk-assign action, which
goes through the shared service (so the append-only trail is identical).
"""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse

from apps.audit.evidence_models import AuditEvidenceRequest
from apps.audit.services import evidence_lifecycle as lc
from apps.authentication.models import User
from apps.frontend.page_views import _ctx

_R = AuditEvidenceRequest

QUEUE_BUCKETS = [
    ("", "All"),
    ("waiting_review", "Waiting review"),
    ("overdue", "Overdue"),
    ("due_today", "Due today"),
    ("accepted_today", "Accepted today"),
    ("rejected", "Rejected"),
    ("more_evidence", "More evidence required"),
    ("high_priority", "High priority"),
]


def _org(request):
    return getattr(request.user, "organization", None)


@login_required(login_url="/login/")
def evidence_queue(request):
    """Auditor review queue + bulk assignment."""
    if not lc.is_auditor(request.user):
        return render(request, "403.html", _ctx(request, "audit"), status=403)

    org = _org(request)
    error = notice = None

    if request.method == "POST" and request.POST.get("action") == "bulk_assign":
        reviewer_id = request.POST.get("reviewer") or None
        reviewer = User.objects.filter(pk=reviewer_id, organization=org).first() \
            if reviewer_id else None
        if reviewer_id and reviewer is None:
            error = "Reviewer not found in your organization."
        else:
            ids = request.POST.getlist("request_ids")
            if not ids:
                error = "Select at least one request."
            else:
                try:
                    result = lc.bulk_assign_reviewer(
                        organization=org, request_ids=ids, reviewer=reviewer,
                        actor=request.user)
                    notice = (f"Assigned {result['assigned_count']} request(s)."
                              + (f" Skipped {len(result['skipped_final'])} final."
                                 if result["skipped_final"] else ""))
                except Exception as exc:
                    error = str(exc)

    q = request.GET
    queue = lc.auditor_queue(
        organization=org, engagement=q.get("engagement"), status=q.get("status"),
        priority=q.get("priority"), assigned_to=q.get("assigned_to"),
        search=q.get("q", ""), bucket=q.get("bucket", ""),
        sort=q.get("sort", "-created")) if org else []
    counts = lc.queue_counts(organization=org) if org else {}
    summary = lc.dashboard_summary(organization=org) if org else {}
    reviewers = list(User.objects.filter(organization=org)[:200]) if org else []

    return render(request, "audit/evidence/queue.html", _ctx(
        request, "audit",
        requests=list(queue[:200]),
        counts=counts,
        summary=summary,
        reviewers=reviewers,
        buckets=QUEUE_BUCKETS,
        status_choices=_R.Status.choices,
        priority_choices=_R.Priority.choices,
        active_bucket=q.get("bucket", ""),
        active_status=q.get("status", ""),
        active_priority=q.get("priority", ""),
        active_sort=q.get("sort", "-created"),
        search=q.get("q", ""),
        error=error,
        notice=notice,
    ))
