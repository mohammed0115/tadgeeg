"""Journal Analytics — frontend pages (TADGEEG-FIN-AUDIT-7A).

Auditor-only, organization-scoped, server-rendered pages surfacing every 7A
backend capability: the analytics dashboard (with charts), the run list +
execution history, per-run results, and the rule registry with enable/disable.

Advisory only — no page here accepts a finding, creates a
``GeneralLedgerRiskFinding``, writes to the ledger, or issues an opinion.
"""
from __future__ import annotations

import json

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse

from apps.audit.engagement_models import AuditEngagement
from apps.audit.general_ledger_models import GeneralLedgerImport
from apps.audit.journal_analytics_models import (
    JournalAnalyticsResult,
    JournalAnalyticsRule,
    JournalAnalyticsRun,
)
from apps.audit.services import evidence_lifecycle as lc  # reused is_auditor
from apps.audit.services import journal_analytics as ja
from apps.frontend.page_views import _ctx

_Run = JournalAnalyticsRun
_Res = JournalAnalyticsResult


def _org(request):
    return getattr(request.user, "organization", None)


def _guard(request):
    """Auditor-only. Returns a 403 response, or None when allowed."""
    if not lc.is_auditor(request.user):
        return render(request, "403.html", _ctx(request, "audit"), status=403)
    return None


def _selected_engagement(request, org):
    eid = request.GET.get("engagement") or request.POST.get("engagement")
    if not eid or org is None:
        return None
    return AuditEngagement.objects.filter(pk=eid, organization=org).first()


@login_required(login_url="/login/")
def analytics_dashboard(request):
    """Analytics dashboard with Chart.js charts (reuses the bundled library)."""
    denied = _guard(request)
    if denied:
        return denied
    org = _org(request)
    engagement = _selected_engagement(request, org)
    data = ja.dashboard(organization=org, engagement=engagement) if org else {}

    charts = {
        "by_severity": data.get("by_severity", {}),
        "top_rules": data.get("top_rules", []),
        "top_accounts": data.get("top_accounts", []),
    }
    return render(request, "audit/analytics/dashboard.html", _ctx(
        request, "audit",
        data=data,
        charts_json=json.dumps(charts, default=str),
        engagements=list(AuditEngagement.objects.filter(organization=org)[:200]) if org else [],
        selected_engagement=engagement,
    ))


@login_required(login_url="/login/")
def analytics_runs(request):
    """Run list / execution history; POST starts a new run for a GL import."""
    denied = _guard(request)
    if denied:
        return denied
    org = _org(request)
    error = notice = None

    if request.method == "POST":
        gl_import = GeneralLedgerImport.objects.filter(
            pk=request.POST.get("general_ledger_import"), organization=org).first()
        if gl_import is None:
            error = "Choose a general ledger import from your organization."
        else:
            try:
                run = ja.run_analytics(gl_import, actor=request.user)
                return redirect(reverse("frontend:analytics_run_detail", args=[run.id]))
            except Exception as exc:
                error = str(exc)

    runs = list(_Run.objects.filter(organization=org)
                .select_related("engagement", "general_ledger_import", "summary")[:100]) if org else []
    imports = list(GeneralLedgerImport.objects.filter(organization=org)
                   .select_related("engagement")[:200]) if org else []

    return render(request, "audit/analytics/runs.html", _ctx(
        request, "audit",
        runs=runs, imports=imports, error=error, notice=notice,
    ))


@login_required(login_url="/login/")
def analytics_run_detail(request, pk):
    """Per-run results with rule/severity filters, plus the JSON report link."""
    denied = _guard(request)
    if denied:
        return denied
    org = _org(request)
    run = (_Run.objects.filter(pk=pk, organization=org)
           .select_related("engagement", "general_ledger_import", "summary").first()) if org else None
    if run is None:
        from django.http import Http404
        raise Http404

    results = run.results.all()
    rule_filter = request.GET.get("rule", "")
    severity_filter = request.GET.get("severity", "")
    journal_filter = (request.GET.get("journal") or "").strip()
    if rule_filter:
        results = results.filter(rule_code=rule_filter)
    if severity_filter:
        results = results.filter(severity=severity_filter)
    if journal_filter:
        results = results.filter(journal_number__icontains=journal_filter)

    summary = getattr(run, "summary", None)
    return render(request, "audit/analytics/run_detail.html", _ctx(
        request, "audit",
        run=run,
        summary=summary,
        results=list(results[:500]),
        rules=ja.RULES,
        severity_choices=_Res.Severity.choices,
        active_rule=rule_filter,
        active_severity=severity_filter,
        journal_filter=journal_filter,
        charts_json=json.dumps({
            "by_rule": summary.by_rule if summary else {},
            "by_severity": summary.by_severity if summary else {},
        }, default=str),
    ))


@login_required(login_url="/login/")
def analytics_rules(request):
    """Rule registry: descriptions, recommendations and enable/disable."""
    denied = _guard(request)
    if denied:
        return denied
    org = _org(request)
    error = notice = None

    if request.method == "POST" and org is not None:
        try:
            rule = ja.set_rule_enabled(
                organization=org, rule_code=request.POST.get("rule_code", ""),
                enabled=request.POST.get("is_enabled") == "1")
            notice = f"{rule.rule_code} {'enabled' if rule.is_enabled else 'disabled'}."
        except ja.AnalyticsError as exc:
            error = str(exc)

    if org is not None:
        ja.ensure_rules(org)
    rules = list(JournalAnalyticsRule.objects.filter(organization=org)) if org else []
    specs = {s.code: s for s in ja.RULES}

    return render(request, "audit/analytics/rules.html", _ctx(
        request, "audit",
        rules=rules, specs=specs, error=error, notice=notice,
    ))
