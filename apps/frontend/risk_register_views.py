"""Risk Register — frontend (TADGEEG-G2.2 · ISA 315/330).

Auditor-only, engagement-scoped page that makes the traceability spine usable:
record assessed risks (ISA 315), attach responsive procedures (ISA 330), and see
each procedure's linked evidence — so Risk -> Procedure -> Evidence is visible in
one place. Deterministic; advisory; no ledger writes.
"""
from __future__ import annotations

from apps.audit.assessed_risk_models import AssessedRisk
from apps.audit.engagement_models import AuditEngagement
from apps.audit.procedure_models import AuditProcedure
from apps.audit.services import assessed_risk as ar
from apps.audit.services import audit_procedure as ap
from apps.audit.services import evidence_lifecycle as lc  # reuse is_auditor
from apps.frontend.page_views import _ctx
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

_R = AssessedRisk
_P = AuditProcedure


def _org(request):
    return getattr(request.user, "organization", None)


def _guard(request):
    if not lc.is_auditor(request.user):
        return render(request, "403.html", _ctx(request, "audit"), status=403)
    return None


def _engagement(request):
    org = _org(request)
    eid = request.GET.get("engagement") or request.POST.get("engagement")
    if not eid or org is None:
        return None
    return AuditEngagement.objects.filter(pk=eid, organization=org).first()


@login_required(login_url="/login/")
def risk_register(request):
    """Assessed-risk register with linked procedures + evidence."""
    denied = _guard(request)
    if denied:
        return denied
    org = _org(request)
    engagement = _engagement(request)
    error = notice = None

    if request.method == "POST" and engagement is not None:
        action = request.POST.get("action", "")
        p = request.POST
        try:
            if action == "create_risk":
                ar.create_risk(
                    engagement=engagement, actor=request.user,
                    title=p.get("title", ""), fs_area=p.get("fs_area", ""),
                    assertion=p.get("assertion"), inherent_risk=p.get("inherent_risk"),
                    control_risk=p.get("control_risk"),
                    is_significant=p.get("is_significant") == "on",
                    is_fraud_risk=p.get("is_fraud_risk") == "on",
                    description=p.get("description", ""))
                notice = "Assessed risk recorded."
            elif action == "create_procedure":
                risk = AssessedRisk.objects.filter(
                    pk=p.get("assessed_risk"), organization=org, engagement=engagement).first()
                ap.create_procedure(
                    engagement=engagement, actor=request.user,
                    title=p.get("title", ""), assessed_risk=risk,
                    nature=p.get("nature"), timing=p.get("timing"),
                    extent=p.get("extent"), description=p.get("description", ""))
                notice = "Procedure recorded."
            elif action == "request_evidence":
                proc = AuditProcedure.objects.filter(
                    pk=p.get("procedure"), organization=org, engagement=engagement).first()
                if proc is None:
                    error = "Procedure not found."
                else:
                    ereq = ap.request_evidence(procedure=proc, actor=request.user)
                    notice = f"Evidence request {ereq.request_number} raised."
            elif action == "risk_status":
                risk = AssessedRisk.objects.filter(
                    pk=p.get("assessed_risk"), organization=org, engagement=engagement).first()
                if risk is not None:
                    ar.set_status(risk=risk, actor=request.user, status=p.get("status", ""))
                    notice = "Risk status updated."
            else:
                error = "Unknown action."
        except (ar.AssessedRiskError, ap.AuditProcedureError) as exc:
            error = str(exc)
        except Exception as exc:  # noqa: BLE001
            error = str(exc)

    risks, summary = [], {}
    if engagement is not None:
        risks = list(AssessedRisk.objects.filter(engagement=engagement)
                     .prefetch_related("procedures__evidence_requests")
                     .order_by("-created_at")[:200])
        summary = ar.summary(organization=org, engagement=engagement)

    return render(request, "audit/risk_register/register.html", _ctx(
        request, "audit",
        engagement=engagement,
        engagements=list(AuditEngagement.objects.filter(organization=org)[:200]) if org else [],
        risks=risks, summary=summary,
        assertion_choices=_R.Assertion.choices,
        inherent_choices=_R.InherentRisk.choices,
        control_choices=_R.ControlRisk.choices,
        risk_status_choices=_R.Status.choices,
        nature_choices=_P.Nature.choices,
        timing_choices=_P.Timing.choices,
        extent_choices=_P.Extent.choices,
        error=error, notice=notice,
    ))
