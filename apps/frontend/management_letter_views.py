"""Management Letter — frontend (TADGEEG-FIN-AUDIT-9B · ISA 265).

Auditor-only, engagement-scoped page to record internal-control deficiencies,
capture management's response, change status, and preview / export the generated
Management Letter (grouped by significance). Advisory only — communicates
deficiencies (ISA 265), not an opinion; no ledger writes.
"""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.audit.control_deficiency_models import AuditControlDeficiency
from apps.audit.engagement_models import AuditEngagement
from apps.audit.services import evidence_lifecycle as lc  # reuse is_auditor
from apps.audit.services import management_letter as ml
from apps.frontend.page_views import _ctx

_D = AuditControlDeficiency


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
def management_letter(request):
    """Deficiency register + management letter preview."""
    denied = _guard(request)
    if denied:
        return denied
    org = _org(request)
    engagement = _engagement(request)
    error = notice = None

    if request.method == "POST" and engagement is not None:
        action = request.POST.get("action", "")
        try:
            if action == "create":
                ml.create_deficiency(
                    engagement=engagement, actor=request.user,
                    title=request.POST.get("title", ""),
                    classification=request.POST.get("classification", "other_deficiency"),
                    area=request.POST.get("area", "other"),
                    description=request.POST.get("description", ""),
                    potential_effect=request.POST.get("potential_effect", ""),
                    recommendation=request.POST.get("recommendation", ""))
                notice = "Deficiency recorded."
            elif action in ("respond", "status"):
                d = AuditControlDeficiency.objects.filter(
                    pk=request.POST.get("deficiency"), organization=org,
                    engagement=engagement).first()
                if d is None:
                    error = "Deficiency not found."
                elif action == "respond":
                    ml.record_management_response(
                        deficiency=d, actor=request.user,
                        response=request.POST.get("management_response", ""),
                        owner=request.POST.get("owner", ""),
                        target_date=request.POST.get("target_date") or None)
                    notice = "Management response recorded."
                elif action == "status":
                    ml.set_status(deficiency=d, actor=request.user,
                                  status=request.POST.get("status", ""))
                    notice = "Status updated."
            else:
                error = "Unknown action."
        except ml.ManagementLetterError as exc:
            error = str(exc)
        except Exception as exc:
            error = str(exc)

    deficiencies, letter, counts = [], None, {}
    if engagement is not None:
        deficiencies = list(AuditControlDeficiency.objects.filter(engagement=engagement)
                            .select_related("identified_by")
                            .order_by("classification", "-created_at")[:300])
        letter = ml.build_management_letter(engagement=engagement)
        counts = ml.status_counts(organization=org, engagement=engagement)

    return render(request, "audit/management_letter/register.html", _ctx(
        request, "audit",
        engagement=engagement,
        engagements=list(AuditEngagement.objects.filter(organization=org)[:200]) if org else [],
        deficiencies=deficiencies, letter=letter, counts=counts,
        classification_choices=_D.Classification.choices,
        area_choices=_D.Area.choices,
        status_choices=_D.Status.choices,
        error=error, notice=notice,
    ))
