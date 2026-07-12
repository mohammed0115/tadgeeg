"""Evidence Request workflow — frontend pages (TADGEEG-FIN-AUDIT-6A).

Minimal, server-rendered Django pages so auditors can use the evidence-request
workflow from the Tadgeeg UI: list, detail (with attachment upload + every
review action), and a standalone create page.

Every page is organization-scoped (a request in another org is a 404). Viewing
is open to any authenticated org member; creating, uploading, submitting, and
reviewing require auditor+ (the same capability as the API). Nothing here posts
to the ledger or issues an opinion — all state changes go through the
``evidence_request`` service.
"""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse

from apps.audit.audit_difference_models import AuditDifferenceItem
from apps.audit.engagement_models import AuditEngagement
from apps.audit.evidence_models import AuditEvidenceRequest
from apps.audit.general_ledger_models import GeneralLedgerRiskFinding
from apps.audit.services import evidence_request as ev_service
from apps.frontend.page_views import _ctx

_R = AuditEvidenceRequest
_FS = GeneralLedgerRiskFinding.Status


def _org(request):
    return getattr(request.user, "organization", None)


def _is_auditor(user) -> bool:
    """auditor+ — same capability the API's IsSeniorAuditorOrAbove checks."""
    try:
        return bool(user.has_role_capability("approve_invoices"))
    except Exception:
        return False


def _get_scoped_request(request, pk):
    org = _org(request)
    if org is None:
        raise Http404
    obj = (AuditEvidenceRequest.objects
           .filter(pk=pk, organization=org)
           .select_related("engagement", "gl_finding", "sad_item",
                           "requested_by", "assigned_to", "reviewed_by")
           .first())
    if obj is None:
        raise Http404
    return obj


@login_required(login_url="/login/")
def evidence_list(request):
    """List the organization's evidence requests."""
    org = _org(request)
    requests = []
    open_count = 0
    if org is not None:
        qs = (AuditEvidenceRequest.objects
              .filter(organization=org)
              .select_related("engagement", "requested_by", "assigned_to"))
        status_filter = request.GET.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        requests = list(qs[:200])
        open_count = ev_service.open_evidence_request_count(organization=org)

    return render(request, "audit/evidence/list.html", _ctx(
        request, "audit",
        evidence_requests=requests,
        open_count=open_count,
        can_manage=_is_auditor(request.user),
        status_choices=_R.Status.choices,
        active_status=request.GET.get("status", ""),
    ))


@login_required(login_url="/login/")
def evidence_create(request):
    """Standalone create page: pick a GL finding or SAD item + request details."""
    org = _org(request)
    if not _is_auditor(request.user):
        return render(request, "403.html", _ctx(request, "audit"), status=403)

    error = None
    if request.method == "POST":
        engagement_id = request.POST.get("engagement")
        gl_finding_id = request.POST.get("gl_finding") or None
        sad_item_id = request.POST.get("sad_item") or None
        engagement = AuditEngagement.objects.filter(
            pk=engagement_id, organization=org).first() if engagement_id else None
        if engagement is None:
            error = "Please choose an engagement in your organization."
        else:
            gl_finding = None
            if gl_finding_id:
                gl_finding = GeneralLedgerRiskFinding.objects.filter(
                    pk=gl_finding_id, organization=org, engagement=engagement).first()
            sad_item = None
            if sad_item_id:
                sad_item = AuditDifferenceItem.objects.filter(
                    pk=sad_item_id, organization=org, engagement=engagement).first()
            try:
                req = ev_service.create_evidence_request(
                    engagement=engagement, actor=request.user,
                    title=request.POST.get("title", ""),
                    gl_finding=gl_finding, sad_item=sad_item,
                    description=request.POST.get("description", ""),
                    request_reason=request.POST.get(
                        "request_reason", _R.RequestReason.SUPPORT_FINDING),
                    priority=request.POST.get("priority", _R.Priority.MEDIUM),
                    due_date=request.POST.get("due_date") or None)
                return redirect(reverse("frontend:evidence_detail", args=[req.id]))
            except Exception as exc:
                error = str(exc)

    engagements, findings, sad_items = [], [], []
    if org is not None:
        engagements = list(AuditEngagement.objects.filter(organization=org)[:100])
        findings = list(GeneralLedgerRiskFinding.objects.filter(
            organization=org,
            status__in=[_FS.NEEDS_EVIDENCE, _FS.ESCALATED])
            .select_related("engagement")[:200])
        sad_items = list(AuditDifferenceItem.objects.filter(
            organization=org).select_related("engagement")[:200])

    return render(request, "audit/evidence/create.html", _ctx(
        request, "audit",
        engagements=engagements,
        findings=findings,
        sad_items=sad_items,
        reason_choices=_R.RequestReason.choices,
        priority_choices=_R.Priority.choices,
        error=error,
    ))


@login_required(login_url="/login/")
def evidence_detail(request, pk):
    """Detail page + POST handler for upload and every review action."""
    obj = _get_scoped_request(request, pk)
    error = notice = None

    if request.method == "POST":
        if not _is_auditor(request.user):
            return render(request, "403.html", _ctx(request, "audit"), status=403)
        action = request.POST.get("action", "")
        note = request.POST.get("note", "")
        try:
            if action == "upload":
                ev_service.add_attachment(
                    request=obj, actor=request.user,
                    uploaded_file=request.FILES.get("file"),
                    description=request.POST.get("description", ""))
                notice = "Attachment uploaded."
            elif action == "submit":
                ev_service.submit_evidence(request=obj, actor=request.user)
                notice = "Evidence submitted for review."
            elif action in ("under_review", "accept", "reject", "more_evidence", "cancel"):
                ev_service.review_evidence_request(
                    request=obj, actor=request.user, action=action, note=note)
                notice = "Request updated."
            else:
                error = "Unknown action."
        except ev_service.EvidenceRequestError as exc:
            error = str(exc)
        except Exception as exc:
            error = str(exc)
        obj.refresh_from_db()

    attachments = list(obj.attachments.filter(is_active=True)
                       .select_related("uploaded_by"))
    events = list(obj.events.select_related("actor").all())

    # Which review actions are valid from the current status (drives the buttons).
    allowed = ev_service.ALLOWED_TRANSITIONS.get(obj.status, set())
    action_flags = {
        "can_submit": _R.Status.SUBMITTED in allowed,
        "can_under_review": _R.Status.UNDER_REVIEW in allowed,
        "can_accept": _R.Status.ACCEPTED in allowed,
        "can_reject": _R.Status.REJECTED in allowed,
        "can_more_evidence": _R.Status.MORE_EVIDENCE_REQUIRED in allowed,
        "can_cancel": _R.Status.CANCELLED in allowed,
        "can_upload": not obj.is_final,
    }

    return render(request, "audit/evidence/detail.html", _ctx(
        request, "audit",
        req=obj,
        attachments=attachments,
        events=events,
        can_manage=_is_auditor(request.user),
        flags=action_flags,
        error=error,
        notice=notice,
    ))
