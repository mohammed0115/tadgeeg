"""Auditor host pages for evidence integration (TADGEEG-FIN-AUDIT-6B).

The 6B spec requires evidence affordances "inside the GL Finding page", "inside
the SAD Item page" and in the "Audit Readiness" view. Those three pages did not
exist (findings/SAD/readiness were API-only plus the 5D export), so this module
adds MINIMAL, READ-ONLY auditor pages purely to host them:

  * GL finding detail   → "Request Evidence" button + its evidence requests
  * SAD item detail     → evidence requests, open count, latest upload
  * Readiness summary   → outstanding evidence (open/submitted/more/accepted/rejected)
                          shown BEFORE the auditor concludes readiness

These pages read existing models only. They never change a finding, a SAD item,
a readiness conclusion, the ledger, or any opinion.
"""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import render

from apps.audit.audit_difference_models import AuditDifferenceItem
from apps.audit.audit_readiness_models import AuditReadinessWorkpaper
from apps.audit.evidence_models import AuditEvidenceRequest
from apps.audit.general_ledger_models import GeneralLedgerRiskFinding
from apps.audit.services import evidence_request as ev_service
from apps.frontend.page_views import _ctx

_R = AuditEvidenceRequest


def _org(request):
    return getattr(request.user, "organization", None)


def _is_auditor(user) -> bool:
    try:
        return bool(user.has_role_capability("approve_invoices"))
    except Exception:
        return False


def _requests_for(org, *, gl_finding=None, sad_item=None):
    qs = AuditEvidenceRequest.objects.filter(organization=org).select_related(
        "requested_by", "assigned_to", "assigned_client_user")
    if gl_finding is not None:
        qs = qs.filter(gl_finding=gl_finding)
    if sad_item is not None:
        qs = qs.filter(sad_item=sad_item)
    return qs


@login_required(login_url="/login/")
def gl_finding_detail(request, pk):
    """Read-only GL risk finding page hosting the "Request Evidence" action."""
    org = _org(request)
    finding = GeneralLedgerRiskFinding.objects.filter(
        pk=pk, organization=org).select_related("engagement").first() if org else None
    if finding is None:
        raise Http404

    requests = list(_requests_for(org, gl_finding=finding))
    open_count = len([r for r in requests if not r.is_final])
    return render(request, "audit/findings/detail.html", _ctx(
        request, "audit",
        finding=finding,
        evidence_requests=requests,
        open_evidence_count=open_count,
        can_manage=_is_auditor(request.user),
    ))


@login_required(login_url="/login/")
def sad_item_detail(request, pk):
    """Read-only SAD item page showing its evidence requests + latest upload."""
    org = _org(request)
    item = AuditDifferenceItem.objects.filter(
        pk=pk, organization=org).select_related(
            "engagement", "summary", "gl_finding").first() if org else None
    if item is None:
        raise Http404

    requests = list(_requests_for(org, sad_item=item))
    open_count = len([r for r in requests if not r.is_final])
    latest_upload = None
    for r in requests:
        att = r.attachments.filter(is_active=True).order_by("-uploaded_at").first()
        if att and (latest_upload is None or att.uploaded_at > latest_upload.uploaded_at):
            latest_upload = att

    return render(request, "audit/sad/item_detail.html", _ctx(
        request, "audit",
        item=item,
        evidence_requests=requests,
        open_evidence_count=open_count,
        latest_upload=latest_upload,
        can_manage=_is_auditor(request.user),
    ))


@login_required(login_url="/login/")
def readiness_evidence_summary(request, pk):
    """Readiness workpaper summary with OUTSTANDING EVIDENCE shown up front.

    Read-only: it never generates or alters a readiness workpaper, and shows no
    audit opinion — the 5A/5B safe wording rules continue to apply.
    """
    org = _org(request)
    workpaper = AuditReadinessWorkpaper.objects.filter(
        pk=pk, organization=org).select_related(
            "engagement", "sad_summary").first() if org else None
    if workpaper is None:
        raise Http404

    counts = ev_service.status_counts(
        organization=org, engagement=workpaper.engagement)
    outstanding = list(
        _requests_for(org).filter(engagement=workpaper.engagement)
        .exclude(status__in=_R.FINAL_STATUSES)[:50])

    return render(request, "audit/readiness/summary.html", _ctx(
        request, "audit",
        workpaper=workpaper,
        counts=counts,
        outstanding=outstanding,
        can_manage=_is_auditor(request.user),
    ))
