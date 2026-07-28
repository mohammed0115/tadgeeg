"""Audit Issue API (TADGEEG-G3.2). Auditor-only, org-scoped. No ledger writes."""
from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from apps.authentication.permissions import IsSeniorAuditorOrAbove

from .assessed_risk_models import AssessedRisk
from .engagement_models import AuditEngagement
from .issue_models import AuditIssue
from .serializers import AuditIssueSerializer
from .services import audit_issue as ai


def _org(request):
    return getattr(request.user, "organization", None)


def _scoped(request, pk):
    org = _org(request)
    if org is None or not pk:
        return None
    return AuditIssue.objects.filter(pk=pk, organization=org).first()


class IssueListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    @extend_schema(tags=["Audit · Issues"], summary="List audit issues")
    def get(self, request):
        org = _org(request)
        if org is None:
            return Response({"error": "no organization."}, status=status.HTTP_400_BAD_REQUEST)
        qs = AuditIssue.objects.filter(organization=org).select_related(
            "assessed_risk", "gl_finding")
        eng = request.query_params.get("engagement")
        if eng:
            qs = qs.filter(engagement_id=eng)
        if request.query_params.get("status"):
            qs = qs.filter(status=request.query_params["status"])
        return Response(AuditIssueSerializer(qs[:500], many=True).data)

    @extend_schema(tags=["Audit · Issues"], summary="Raise an audit issue")
    def post(self, request):
        org = _org(request)
        d = request.data
        engagement = AuditEngagement.objects.filter(
            pk=d.get("engagement"), organization=org).first()
        if engagement is None:
            return Response({"error": "engagement not found in your organization."},
                            status=status.HTTP_404_NOT_FOUND)
        risk = None
        if d.get("assessed_risk"):
            risk = AssessedRisk.objects.filter(
                pk=d.get("assessed_risk"), organization=org, engagement=engagement).first()
        # G5 bridge — promote a GL risk finding into an engagement issue.
        if d.get("gl_finding"):
            from .general_ledger_models import GeneralLedgerRiskFinding
            finding = GeneralLedgerRiskFinding.objects.filter(
                pk=d.get("gl_finding"), organization=org, engagement=engagement).first()
            if finding is None:
                return Response({"error": "gl_finding not found in this engagement."},
                                status=status.HTTP_404_NOT_FOUND)
            obj = ai.promote_from_gl_finding(finding=finding, actor=request.user,
                                             assessed_risk=risk,
                                             due_date=d.get("due_date") or None)
            return Response(AuditIssueSerializer(obj).data, status=status.HTTP_201_CREATED)
        try:
            obj = ai.create_issue(
                engagement=engagement, actor=request.user, title=d.get("title", ""),
                description=d.get("description", ""), severity=d.get("severity"),
                assessed_risk=risk, owner=d.get("owner", ""),
                due_date=d.get("due_date") or None,
                remediation_plan=d.get("remediation_plan", ""))
        except ai.AuditIssueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:  # noqa: BLE001
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(AuditIssueSerializer(obj).data, status=status.HTTP_201_CREATED)


class IssueDetailView(APIView):
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    @extend_schema(tags=["Audit · Issues"], summary="Issue detail / status / remediation")
    def get(self, request, pk):
        obj = _scoped(request, pk)
        if obj is None:
            return Response({"error": "not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(AuditIssueSerializer(obj).data)

    def post(self, request, pk):
        obj = _scoped(request, pk)
        if obj is None:
            return Response({"error": "not found."}, status=status.HTTP_404_NOT_FOUND)
        d = request.data
        try:
            if d.get("action") == "remediation":
                ai.record_remediation(issue=obj, actor=request.user,
                                      remediation_plan=d.get("remediation_plan", ""),
                                      owner=d.get("owner", ""),
                                      due_date=d.get("due_date") or None)
            if d.get("status"):
                ai.set_status(issue=obj, actor=request.user, status=d.get("status"),
                              note=d.get("note", ""))
        except ai.AuditIssueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(AuditIssueSerializer(obj).data)


class EngagementIssueSummaryView(APIView):
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    @extend_schema(tags=["Audit · Issues"], summary="Issue summary")
    def get(self, request, pk):
        org = _org(request)
        engagement = AuditEngagement.objects.filter(pk=pk, organization=org).first()
        if engagement is None:
            return Response({"error": "engagement not found in your organization."},
                            status=status.HTTP_404_NOT_FOUND)
        return Response(ai.summary(organization=org, engagement=engagement))
