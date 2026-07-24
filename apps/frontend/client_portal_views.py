"""Client Evidence Portal — frontend pages (TADGEEG-FIN-AUDIT-6B).

Server-rendered pages for the CLIENT side of the evidence workflow. Access is
granted per-request via ``AuditEvidenceRequest.assigned_client_user`` (no role or
authentication change), so a client user sees ONLY the requests assigned to them
within their own organization.

A client may: view their requests, upload evidence (allowlisted formats),
provide a management explanation, and submit for review.
A client may NOT: review evidence, change findings/SAD, delete attachments, or
see any other user's requests. All history is append-only.
"""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.audit.evidence_models import AuditEvidenceRequest
from apps.audit.services import evidence_request as ev_service
from apps.frontend.page_views import _ctx

_R = AuditEvidenceRequest


def _org(request):
    return getattr(request.user, "organization", None)


def _client_qs(request):
    """Requests this user may see as a client: own org AND assigned to them."""
    org = _org(request)
    if org is None:
        return AuditEvidenceRequest.objects.none()
    return (AuditEvidenceRequest.objects
            .filter(organization=org, assigned_client_user=request.user)
            .select_related("engagement", "gl_finding", "sad_item",
                            "requested_by", "assigned_to"))


def _get_client_request(request, pk):
    obj = _client_qs(request).filter(pk=pk).first()
    if obj is None:
        raise Http404
    return obj


@login_required(login_url="/login/")
def client_evidence_list(request):
    """Client portal list with status/priority/engagement/overdue filters + search."""
    qs = _client_qs(request)

    status_f = request.GET.get("status", "")
    priority_f = request.GET.get("priority", "")
    engagement_f = request.GET.get("engagement", "")
    overdue_f = request.GET.get("overdue", "")
    search = (request.GET.get("q") or "").strip()

    if status_f:
        qs = qs.filter(status=status_f)
    if priority_f:
        qs = qs.filter(priority=priority_f)
    if engagement_f:
        qs = qs.filter(engagement_id=engagement_f)
    if overdue_f:
        qs = qs.filter(due_date__lt=timezone.now().date()).exclude(
            status__in=_R.FINAL_STATUSES)
    if search:
        from django.db.models import Q
        qs = qs.filter(
            Q(title__icontains=search)
            | Q(request_number__icontains=search)
            | Q(gl_finding__risk_code__icontains=search)
            | Q(gl_finding__account_code__icontains=search)
            | Q(sad_item__account_code__icontains=search))

    requests = list(qs[:200])
    counts = ev_service.status_counts(
        organization=_org(request), client_user=request.user) if _org(request) else {}
    engagements = sorted(
        {(r.engagement_id, str(r.engagement)) for r in _client_qs(request)},
        key=lambda t: t[1])

    return render(request, "audit/client_portal/list.html", _ctx(
        request, "audit",
        evidence_requests=requests,
        counts=counts,
        status_choices=_R.Status.choices,
        priority_choices=_R.Priority.choices,
        engagement_choices=engagements,
        active_status=status_f,
        active_priority=priority_f,
        active_engagement=engagement_f,
        active_overdue=bool(overdue_f),
        search=search,
    ))


@login_required(login_url="/login/")
def client_evidence_detail(request, pk):
    """Client portal detail: info, attachments, timeline, upload, explanation."""
    obj = _get_client_request(request, pk)
    error = notice = None

    if request.method == "POST":
        action = request.POST.get("action", "")
        try:
            if action == "upload":
                files = request.FILES.getlist("files") or (
                    [request.FILES["file"]] if "file" in request.FILES else [])
                if not files:
                    raise ev_service.EvidenceRequestError("choose at least one file.")
                # Validate every file BEFORE storing any, so a rejected batch
                # never leaves a partial upload behind.
                for f in files:
                    ev_service.validate_evidence_file(f, getattr(f, "name", ""))
                for f in files:
                    ev_service.add_attachment(
                        request=obj, actor=request.user, uploaded_file=f,
                        description=request.POST.get("description", ""),
                        validate=False, notify_auditor=False)
                ev_service.notify_evidence_uploaded(
                    request=obj, actor=request.user, count=len(files))
                notice = f"{len(files)} file(s) uploaded."
            elif action == "explain":
                ev_service.record_management_explanation(
                    request=obj, actor=request.user,
                    explanation=request.POST.get("management_explanation", ""))
                notice = "Management explanation saved."
            elif action == "submit":
                ev_service.submit_evidence(request=obj, actor=request.user)
                notice = "Submitted for auditor review."
            else:
                error = "Unknown action."
        except ev_service.EvidenceRequestError as exc:
            error = str(exc)
        except Exception as exc:
            error = str(exc)
        obj.refresh_from_db()

    allowed = ev_service.ALLOWED_TRANSITIONS.get(obj.status, set())
    return render(request, "audit/client_portal/detail.html", _ctx(
        request, "audit",
        req=obj,
        attachments=list(obj.attachments.filter(is_active=True)
                         .select_related("uploaded_by")),
        events=list(obj.events.select_related("actor").all()),
        can_upload=not obj.is_final,
        can_submit=_R.Status.SUBMITTED in allowed,
        allowed_extensions=sorted(ev_service.ALLOWED_EVIDENCE_EXTENSIONS),
        error=error,
        notice=notice,
    ))
