"""Journal Analytics API (TADGEEG-FIN-AUDIT-7A).

ADDITIVE endpoints only. Organization-scoped and auditor-gated. Analytics are
ADVISORY: no endpoint accepts a finding, creates a ``GeneralLedgerRiskFinding``,
writes to ``apps.ledger``, or issues an opinion.
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from apps.authentication.permissions import IsSeniorAuditorOrAbove

from .engagement_models import AuditEngagement
from .general_ledger_models import GeneralLedgerImport
from .journal_analytics_models import (
    JournalAnalyticsResult,
    JournalAnalyticsRule,
    JournalAnalyticsRun,
)
from .services import journal_analytics as ja


def _org(request):
    return getattr(request.user, "organization", None)


def _scoped_run(request, pk):
    org = _org(request)
    if org is None or not pk:
        return None
    return (JournalAnalyticsRun.objects.filter(pk=pk, organization=org)
            .select_related("engagement", "general_ledger_import", "summary")
            .first())


def _run_payload(run) -> dict:
    summary = getattr(run, "summary", None)
    return {
        "id": str(run.id),
        "status": run.status,
        "engagement": str(run.engagement_id),
        "general_ledger_import": str(run.general_ledger_import_id),
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "execution_ms": run.execution_ms,
        "rules_executed": run.rules_executed,
        "rows_analyzed": run.rows_analyzed,
        "journals_analyzed": run.journals_analyzed,
        "findings_count": run.findings_count,
        "warnings": run.warnings,
        "errors": run.errors,
        "metadata": run.metadata,
        "created_at": run.created_at.isoformat(),
        "summary": {
            "flagged_journals": summary.flagged_journals,
            "high_risk_journals": summary.high_risk_journals,
            "medium_risk_journals": summary.medium_risk_journals,
            "low_risk_journals": summary.low_risk_journals,
            "by_rule": summary.by_rule,
            "by_severity": summary.by_severity,
            "top_accounts": summary.top_accounts,
            "top_users": summary.top_users,
        } if summary else None,
        "advisory_only": True,
    }


def _result_payload(r) -> dict:
    return {
        "id": str(r.id), "rule_code": r.rule_code, "rule_name": r.rule_name,
        "severity": r.severity, "score": r.score,
        "journal_number": r.journal_number, "account_code": r.account_code,
        "account_name": r.account_name, "entered_by": r.entered_by,
        "description": r.description, "recommendation": r.recommendation,
        "amount": str(r.amount), "affected_rows": r.affected_rows,
        "execution_ms": r.execution_ms, "evidence": r.evidence,
    }


class AnalyticsRunListCreateView(APIView):
    """GET: list runs. POST: execute analytics over a GL import (auditor+)."""
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    @extend_schema(tags=["Audit · Journal Analytics"], summary="List analytics runs")
    def get(self, request):
        org = _org(request)
        if org is None:
            return Response({"error": "no organization."},
                            status=status.HTTP_400_BAD_REQUEST)
        qs = JournalAnalyticsRun.objects.filter(organization=org).select_related("summary")
        engagement = request.query_params.get("engagement")
        if engagement:
            qs = qs.filter(engagement_id=engagement)
        gl_import = request.query_params.get("import")
        if gl_import:
            qs = qs.filter(general_ledger_import_id=gl_import)
        return Response({"results": [_run_payload(r) for r in qs[:100]]})

    @extend_schema(tags=["Audit · Journal Analytics"], summary="Run journal analytics")
    def post(self, request):
        org = _org(request)
        gl_import = GeneralLedgerImport.objects.filter(
            pk=request.data.get("general_ledger_import"), organization=org).first()
        if gl_import is None:
            return Response({"error": "general ledger import not found in your organization."},
                            status=status.HTTP_404_NOT_FOUND)
        try:
            run = ja.run_analytics(gl_import, actor=request.user,
                                   rule_codes=request.data.get("rules") or None)
        except Exception as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(_run_payload(run), status=status.HTTP_201_CREATED)


class AnalyticsRunDetailView(APIView):
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    @extend_schema(tags=["Audit · Journal Analytics"], summary="Analytics run detail")
    def get(self, request, pk):
        run = _scoped_run(request, pk)
        if run is None:
            return Response({"error": "not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(_run_payload(run))


class AnalyticsRunResultsView(APIView):
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    @extend_schema(tags=["Audit · Journal Analytics"], summary="Analytics results for a run")
    def get(self, request, pk):
        run = _scoped_run(request, pk)
        if run is None:
            return Response({"error": "not found."}, status=status.HTTP_404_NOT_FOUND)
        qs = run.results.all()
        rule_code = request.query_params.get("rule")
        if rule_code:
            qs = qs.filter(rule_code=rule_code)
        severity = request.query_params.get("severity")
        if severity:
            qs = qs.filter(severity=severity)
        journal = request.query_params.get("journal")
        if journal:
            qs = qs.filter(journal_number__icontains=journal)
        return Response({"results": [_result_payload(r) for r in qs[:500]]})


class AnalyticsRunReportView(APIView):
    """JSON analytics report (no PDF in this phase)."""
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    @extend_schema(tags=["Audit · Journal Analytics"], summary="Analytics JSON report")
    def get(self, request, pk):
        run = _scoped_run(request, pk)
        if run is None:
            return Response({"error": "not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(ja.report(run=run))


class AnalyticsDashboardView(APIView):
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    @extend_schema(tags=["Audit · Journal Analytics"], summary="Analytics dashboard")
    def get(self, request):
        org = _org(request)
        if org is None:
            return Response({"error": "no organization."},
                            status=status.HTTP_400_BAD_REQUEST)
        engagement = None
        eid = request.query_params.get("engagement")
        if eid:
            engagement = AuditEngagement.objects.filter(pk=eid, organization=org).first()
            if engagement is None:
                return Response({"error": "engagement not found in your organization."},
                                status=status.HTTP_404_NOT_FOUND)
        return Response(ja.dashboard(organization=org, engagement=engagement))


class AnalyticsRuleListView(APIView):
    """GET: the rule registry. POST: enable/disable a rule (auditor+)."""
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    @extend_schema(tags=["Audit · Journal Analytics"], summary="List analytics rules")
    def get(self, request):
        org = _org(request)
        if org is None:
            return Response({"error": "no organization."},
                            status=status.HTTP_400_BAD_REQUEST)
        ja.ensure_rules(org)
        rules = JournalAnalyticsRule.objects.filter(organization=org)
        return Response({"rules": [{
            "id": str(r.id), "rule_code": r.rule_code, "name": r.name,
            "description": r.description, "recommendation": r.recommendation,
            "category": r.category, "is_enabled": r.is_enabled, "weight": r.weight,
        } for r in rules]})

    @extend_schema(tags=["Audit · Journal Analytics"], summary="Enable/disable a rule")
    def post(self, request):
        org = _org(request)
        try:
            rule = ja.set_rule_enabled(
                organization=org, rule_code=request.data.get("rule_code", ""),
                enabled=bool(request.data.get("is_enabled", True)))
        except ja.AnalyticsError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"rule_code": rule.rule_code, "is_enabled": rule.is_enabled})
