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

    # Substantive testing (9D) — per-area totals.
    def _substantive():
        from apps.audit.services import substantive_testing as st
        t = st.area_summary(organization=org, engagement=engagement).get("_totals", {})
        return {"total": t.get("total", 0), "variance": t.get("variance", 0),
                "matched": t.get("matched", 0)}
    substantive = _safe(_substantive, {})

    # External confirmations (9C) — status counts.
    def _confirmations():
        from apps.audit.services import confirmation_request as cs
        c = cs.status_counts(organization=org, engagement=engagement)
        return {"total": c.get("total", 0), "discrepancy": c.get("discrepancy", 0),
                "outstanding": c.get("outstanding", 0), "matched": c.get("matched", 0)}
    confirmations = _safe(_confirmations, {})

    # Management letter (9B) — control-deficiency counts.
    def _deficiencies():
        from apps.audit.services import management_letter as ml
        c = ml.status_counts(organization=org, engagement=engagement)
        return {"total": c.get("total", 0),
                "material_weakness": c.get("material_weakness", 0)}
    deficiencies = _safe(_deficiencies, {})

    # Saved planning records (9H) — per-kind counts.
    def _planning_records():
        from apps.audit.services import planning_records as pr
        return pr.counts(organization=org, engagement=engagement)
    planning_records = _safe(_planning_records, {})

    # Assessed risks + procedures (G2 traceability spine).
    def _risks():
        from apps.audit.services import assessed_risk as ar
        from apps.audit.services import audit_procedure as ap
        r = ar.summary(organization=org, engagement=engagement)
        p = ap.summary(organization=org, engagement=engagement)
        return {"total": r.get("total", 0), "significant": r.get("significant", 0),
                "fraud": r.get("fraud", 0), "procedures": p.get("total", 0),
                "linked_procedures": p.get("linked", 0)}
    risks = _safe(_risks, {})

    # Issues (G3.2) — remediation → closure loop.
    def _issues():
        from apps.audit.services import audit_issue as ai
        c = ai.summary(organization=org, engagement=engagement)
        return {"total": c.get("total", 0), "open": c.get("open", 0),
                "overdue": c.get("overdue", 0), "critical": c.get("critical", 0)}
    issues = _safe(_issues, {})

    # Findings register (G2.3) — normalized across finding types.
    def _findings():
        from apps.audit.services import findings_register as fr
        return fr.summary(organization=org, engagement=engagement)
    findings = _safe(_findings, {})

    # Engagement team (G3.3).
    def _members():
        from apps.audit.services import engagement_member as em
        return em.summary(organization=org, engagement=engagement)
    members = _safe(_members, {})

    # Engagement reports (G6) — latest snapshot status.
    def _reports():
        from apps.audit.services import report_builder as rb
        rows = rb.list_reports(engagement=engagement, limit=1)
        if not rows:
            return None
        r = rows[0]
        return {"reference": r.reference, "version": r.version,
                "status_display": r.get_status_display()}
    reports = _safe(_reports, None)

    return {
        "materiality": materiality,
        "gl_findings": gl_findings,
        "sad": sad,
        "evidence": evidence,
        "assurance": assurance,
        "analytics": analytics,
        "readiness": readiness,
        "substantive": substantive,
        "confirmations": confirmations,
        "deficiencies": deficiencies,
        "planning_records": planning_records,
        "risks": risks,
        "issues": issues,
        "findings": findings,
        "members": members,
        "reports": reports,
        "stage_steps": _stage_steps(engagement),
    }


def _list_rows(engagements, org):
    """Light per-row badges for the engagement list (G9 — bulk, not N×full).

    Returns rows shaped exactly like the template expects
    (``row.overview.gl_findings.open`` + ``row.overview.assurance.coverage_percent``),
    but computes open GL findings for ALL engagements in a single grouped query.
    """
    if not engagements or org is None:
        return [{"e": e, "overview": {"gl_findings": {"open": 0},
                                      "assurance": {"coverage_percent": 0}}}
                for e in engagements]
    from django.db.models import Count, Q
    ids = [e.id for e in engagements]
    open_statuses = [_FS.CANDIDATE, _FS.NEEDS_EVIDENCE, _FS.ESCALATED]
    gl_open = {r["engagement_id"]: r["n"] for r in (
        GeneralLedgerRiskFinding.objects
        .filter(engagement_id__in=ids, organization=org)
        .values("engagement_id")
        .annotate(n=Count("id", filter=Q(status__in=open_statuses))))}

    def _coverage(e):
        def _cov():
            from apps.audit.services import evidence_assurance as ea
            return ea.assurance_dashboard(organization=org, engagement=e).get(
                "coverage_percent", 0)
        return _safe(_cov, 0)

    return [{"e": e, "overview": {
        "gl_findings": {"open": gl_open.get(e.id, 0)},
        "assurance": {"coverage_percent": _coverage(e)}}} for e in engagements]


@login_required(login_url="/login/")
def engagement_list(request):
    """List the organization's audit engagements + create a new one."""
    denied = _guard(request)
    if denied:
        return denied
    org = _org(request)
    error = notice = None

    # Create an engagement — the entry point for the whole audit workflow.
    if request.method == "POST" and request.POST.get("action") == "create" and org:
        p = request.POST
        code = (p.get("engagement_code") or "").strip()
        title = (p.get("title") or "").strip()
        period_start = (p.get("period_start") or "").strip()
        period_end = (p.get("period_end") or "").strip()
        if not code or not title:
            error = "Engagement code and title are required."
        elif not period_start or not period_end:
            # period_start/period_end are NOT NULL on the model — validate here so
            # a missing date is a friendly message, never a broken transaction.
            error = "Period start and end dates are required."
        elif AuditEngagement.objects.filter(organization=org, engagement_code=code).exists():
            error = f"Engagement code '{code}' already exists."
        else:
            try:
                eng = AuditEngagement.objects.create(
                    organization=org, engagement_code=code, title=title,
                    description=p.get("description", ""),
                    engagement_type=p.get("engagement_type") or _Eng.EngagementType.FINANCIAL_STATEMENT,
                    period_start=period_start, period_end=period_end,
                    created_by=request.user if getattr(request.user, "pk", None) else None)
                from apps.audit.services import audit_trail
                audit_trail.record(
                    organization=org, actor=request.user,
                    action="engagement_stage_changed", entity_type="audit_engagement",
                    entity_id=eng.pk, description=f"Engagement {code} created",
                    metadata={"engagement_code": code, "event": "created"})
                return redirect("frontend:engagement_workspace", pk=eng.id)
            except Exception as exc:  # noqa: BLE001
                error = str(exc)

    qs = AuditEngagement.objects.filter(organization=org) if org else AuditEngagement.objects.none()
    stage = request.GET.get("stage", "")
    if stage:
        qs = qs.filter(stage=stage)
    engagements = list(qs.select_related("engagement_partner", "engagement_manager")[:200])

    # G9 — the list template uses only two overview metrics (gl_findings.open +
    # assurance.coverage_percent). Building the FULL overview per row was ~15
    # queries × N engagements. Instead: ONE bulk query for open GL findings
    # across all engagements, and one assurance call per row.
    rows = _list_rows(engagements, org)

    return render(request, "audit/engagements/list.html", _ctx(
        request, "audit",
        rows=rows,
        stage_choices=_Eng.Stage.choices,
        type_choices=_Eng.EngagementType.choices,
        active_stage=stage,
        error=error, notice=notice,
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
            old_stage = engagement.stage
            engagement.stage = new_stage
            fields = ["stage", "updated_at"]
            if new_stage == _Eng.Stage.ACCEPTANCE and not engagement.accepted_at:
                engagement.accepted_at = timezone.now()
                fields.append("accepted_at")
            engagement.save(update_fields=fields)
            # G0 — record the transition in the tamper-evident audit trail
            # (defensive: a logging failure must never break the stage change).
            if old_stage != new_stage:
                from apps.audit.services import audit_trail
                audit_trail.record_stage_change(
                    engagement=engagement, actor=request.user,
                    old_stage=old_stage, new_stage=new_stage, request=request)
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
        # Newer modules (9B/9C/9D/9H) — engagement-filtered deep links.
        "risk_register": f"{reverse('frontend:risk_register')}?engagement={engagement.id}",
        "substantive": f"{reverse('frontend:substantive_testing')}?engagement={engagement.id}",
        "confirmations": f"{reverse('frontend:confirmations')}?engagement={engagement.id}",
        "management_letter": f"{reverse('frontend:management_letter')}?engagement={engagement.id}",
        "isa_planning": f"{reverse('frontend:isa_planning')}?engagement={engagement.id}",
        # Governance modules (G2.3/G3.2/G3.3/G6) — engagement-filtered deep links.
        "findings_register": f"{reverse('frontend:findings_register')}?engagement={engagement.id}",
        "issues": f"{reverse('frontend:issues')}?engagement={engagement.id}",
        "reports": f"{reverse('frontend:engagement_reports')}?engagement={engagement.id}",
        "team": f"{reverse('frontend:engagement_team')}?engagement={engagement.id}",
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
