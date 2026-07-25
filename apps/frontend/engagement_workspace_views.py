"""Engagement Workspace — frontend pages (TADGEEG-FIN-AUDIT-8A).

A unified, auditor-facing hub for one ``AuditEngagement`` that AGGREGATES the
capabilities already built across phases 1A–7A and deep-links into their
existing pages. This phase adds NO new backend logic — it surfaces:

  * the engagement lifecycle stage (ISA 300),
  * materiality (3A ``resolve_materiality``),
  * GL risk findings (2B) counts by status,
  * the Summary of Audit Differences (4A/4B),
  * evidence status + coverage/integrity (6B/6D),
  * journal analytics highlights (7A),
  * audit-readiness workpaper status (5A/5D).

Every data source is read defensively so one missing piece can never break the
workspace. Auditor-only, organization-scoped, advisory (no opinion, no ledger).
"""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.audit.engagement_models import AuditEngagement
from apps.audit.general_ledger_models import GeneralLedgerRiskFinding
from apps.audit.services import evidence_lifecycle as lc  # reuse is_auditor
from apps.frontend.page_views import _ctx

_Eng = AuditEngagement
_FS = GeneralLedgerRiskFinding.Status

# Linear lifecycle order for the progress bar (WITHDRAWN is handled separately).
_STAGE_ORDER = [
    _Eng.Stage.ACCEPTANCE, _Eng.Stage.PLANNING, _Eng.Stage.RISK_ASSESSMENT,
    _Eng.Stage.FIELDWORK, _Eng.Stage.REVIEW, _Eng.Stage.EQR,
    _Eng.Stage.REPORTING, _Eng.Stage.ARCHIVED,
]


def _org(request):
    return getattr(request.user, "organization", None)


def _guard(request):
    """Auditor-only. Returns a 403 response, or None when allowed."""
    if not lc.is_auditor(request.user):
        return render(request, "403.html", _ctx(request, "audit"), status=403)
    return None


def _stage_steps(engagement) -> list[dict]:
    """Ordered stage list with done/current flags for the progress bar."""
    try:
        current = _STAGE_ORDER.index(engagement.stage)
    except ValueError:
        current = -1  # WITHDRAWN or unknown → nothing marked current
    steps = []
    for i, stage in enumerate(_STAGE_ORDER):
        steps.append({
            "code": stage,
            "label": _Eng.Stage(stage).label,
            "done": current >= 0 and i < current,
            "current": current >= 0 and i == current,
        })
    return steps


def _safe(fn, default):
    try:
        return fn()
    except Exception:  # pragma: no cover - defensive; a widget must never 500
        return default


def _engagement_overview(engagement) -> dict:
    """Aggregate every phase's data for one engagement (all defensive reads)."""
    org = engagement.organization

    # Materiality (3A) — reused, not recomputed.
    def _materiality():
        from apps.audit.services.gl_finding_materiality import resolve_materiality
        return resolve_materiality(engagement)
    materiality = _safe(_materiality, None)

    # GL risk findings (2B) counts by status.
    def _gl():
        from django.db.models import Count
        rows = (GeneralLedgerRiskFinding.objects
                .filter(engagement=engagement, organization=org)
                .values("status").annotate(n=Count("id")))
        counts = {s.value: 0 for s in _FS}
        for r in rows:
            counts[r["status"]] = r["n"]
        counts["total"] = sum(counts[s.value] for s in _FS)
        counts["open"] = counts[_FS.CANDIDATE] + counts[_FS.NEEDS_EVIDENCE] + counts[_FS.ESCALATED]
        return counts
    gl_findings = _safe(_gl, {})

    # SAD (4A/4B) — latest summary for the engagement.
    def _sad():
        s = engagement.difference_summaries.order_by("-created_at").first()
        if s is None:
            return None
        return {
            "id": str(s.id),
            "conclusion_status": s.conclusion_status,
            "conclusion_display": s.get_conclusion_status_display(),
            "total_absolute_impact": str(s.total_absolute_impact),
            "exceeds_performance_materiality": s.exceeds_performance_materiality,
            "exceeds_overall_materiality": s.exceeds_overall_materiality,
            "item_count": s.items.count(),
        }
    sad = _safe(_sad, None)

    # Evidence (6B) status counts + (6D) assurance.
    def _evidence():
        from apps.audit.services import evidence_request as ev
        return ev.status_counts(organization=org, engagement=engagement)
    evidence = _safe(_evidence, {})

    def _assurance():
        from apps.audit.services import evidence_assurance as ea
        return ea.assurance_dashboard(organization=org, engagement=engagement)
    assurance = _safe(_assurance, {})

    # Journal analytics (7A) highlights.
    def _analytics():
        from apps.audit.services import journal_analytics as ja
        return ja.dashboard(organization=org, engagement=engagement)
    analytics = _safe(_analytics, {})

    # Readiness workpaper (5A/5D) — latest.
    def _readiness():
        wp = engagement.readiness_workpapers.order_by("-created_at").first()
        if wp is None:
            return None
        return {
            "id": str(wp.id),
            "status": wp.status,
            "status_display": wp.get_status_display(),
            "conclusion": wp.readiness_conclusion,
            "conclusion_display": wp.get_readiness_conclusion_display(),
            "direction_display": wp.get_suggested_opinion_direction_display(),
        }
    readiness = _safe(_readiness, None)

    return {
        "materiality": materiality,
        "gl_findings": gl_findings,
        "sad": sad,
        "evidence": evidence,
        "assurance": assurance,
        "analytics": analytics,
        "readiness": readiness,
        "stage_steps": _stage_steps(engagement),
    }


@login_required(login_url="/login/")
def engagement_list(request):
    """List the organization's audit engagements with lifecycle stage."""
    denied = _guard(request)
    if denied:
        return denied
    org = _org(request)
    qs = AuditEngagement.objects.filter(organization=org) if org else AuditEngagement.objects.none()
    stage = request.GET.get("stage", "")
    if stage:
        qs = qs.filter(stage=stage)
    engagements = list(qs.select_related("engagement_partner", "engagement_manager")[:200])

    # A light per-engagement badge: open GL findings + evidence coverage.
    rows = []
    for e in engagements:
        rows.append({"e": e, "overview": _engagement_overview(e)})

    return render(request, "audit/engagements/list.html", _ctx(
        request, "audit",
        rows=rows,
        stage_choices=_Eng.Stage.choices,
        active_stage=stage,
    ))


@login_required(login_url="/login/")
def engagement_workspace(request, pk):
    """The unified engagement hub. POST advances/sets the lifecycle stage."""
    denied = _guard(request)
    if denied:
        return denied
    org = _org(request)
    engagement = (AuditEngagement.objects.filter(pk=pk, organization=org)
                  .select_related("engagement_partner", "engagement_manager",
                                  "eqr_partner").first()) if org else None
    if engagement is None:
        from django.http import Http404
        raise Http404

    notice = error = None
    if request.method == "POST" and request.POST.get("action") == "set_stage":
        new_stage = request.POST.get("stage", "")
        valid = {s.value for s in _Eng.Stage}
        if new_stage not in valid:
            error = "Invalid stage."
        elif engagement.locked_at:
            error = "This engagement is archived and locked; its stage cannot change."
        else:
            engagement.stage = new_stage
            fields = ["stage", "updated_at"]
            if new_stage == _Eng.Stage.ACCEPTANCE and not engagement.accepted_at:
                engagement.accepted_at = timezone.now()
                fields.append("accepted_at")
            engagement.save(update_fields=fields)
            notice = f"Stage set to {engagement.get_stage_display()}."

    overview = _engagement_overview(engagement)
    # Deep links into the pages that already exist (filtered by engagement).
    links = {
        "analytics": f"{reverse('frontend:analytics_dashboard')}?engagement={engagement.id}",
        "analytics_runs": reverse("frontend:analytics_runs"),
        "evidence_queue": reverse("frontend:evidence_queue"),
        "assurance_coverage": f"{reverse('frontend:assurance_coverage')}?engagement={engagement.id}",
        "assurance_overview": f"{reverse('frontend:assurance_overview')}?engagement={engagement.id}",
        "working_papers": reverse("frontend:working_papers"),
        "audit_tools": reverse("frontend:audit_tools"),
    }
    if overview.get("readiness"):
        links["readiness"] = reverse(
            "frontend:readiness_evidence_summary", args=[overview["readiness"]["id"]])
    if overview.get("sad"):
        links["sad_item_example"] = None  # SAD list page arrives in 8D

    return render(request, "audit/engagements/workspace.html", _ctx(
        request, "audit",
        engagement=engagement,
        overview=overview,
        links=links,
        stage_choices=_Eng.Stage.choices,
        notice=notice,
        error=error,
    ))
