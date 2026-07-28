"""Assessed Risk API (TADGEEG-G2 · ISA 315 — traceability anchor).

Additive, organization-scoped, auditor-only endpoints for the assessed-risk
register. Junior → 403; cross-org → 404. No ledger writes.
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from apps.authentication.permissions import IsSeniorAuditorOrAbove

from .assessed_risk_models import AssessedRisk
from .engagement_models import AuditEngagement
from .serializers import AssessedRiskSerializer
from .services import assessed_risk as ar


def _org(request):
    return getattr(request.user, "organization", None)


def _scoped(request, pk):
    org = _org(request)
    if org is None or not pk:
        return None
    return AssessedRisk.objects.filter(pk=pk, organization=org).first()


class AssessedRiskListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    @extend_schema(tags=["Audit · Assessed Risks"], summary="List assessed risks")
    def get(self, request):
        org = _org(request)
        if org is None:
            return Response({"error": "no organization."}, status=status.HTTP_400_BAD_REQUEST)
        qs = AssessedRisk.objects.filter(organization=org).select_related("created_by")
        eng = request.query_params.get("engagement")
        if eng:
            qs = qs.filter(engagement_id=eng)
        if request.query_params.get("status"):
            qs = qs.filter(status=request.query_params["status"])
        return Response(AssessedRiskSerializer(qs[:500], many=True).data)

    @extend_schema(tags=["Audit · Assessed Risks"], summary="Record an assessed risk")
    def post(self, request):
        org = _org(request)
        d = request.data
        engagement = AuditEngagement.objects.filter(
            pk=d.get("engagement"), organization=org).first()
        if engagement is None:
            return Response({"error": "engagement not found in your organization."},
                            status=status.HTTP_404_NOT_FOUND)
        try:
            obj = ar.create_risk(
                engagement=engagement, actor=request.user, title=d.get("title", ""),
                assertion=d.get("assertion"), fs_area=d.get("fs_area", ""),
                inherent_risk=d.get("inherent_risk"), control_risk=d.get("control_risk"),
                is_significant=d.get("is_significant", False),
                is_fraud_risk=d.get("is_fraud_risk", False),
                description=d.get("description", ""), notes=d.get("notes", ""))
        except ar.AssessedRiskError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:  # noqa: BLE001
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(AssessedRiskSerializer(obj).data, status=status.HTTP_201_CREATED)


class AssessedRiskDetailView(APIView):
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    @extend_schema(tags=["Audit · Assessed Risks"], summary="Assessed risk detail / status")
    def get(self, request, pk):
        obj = _scoped(request, pk)
        if obj is None:
            return Response({"error": "not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(AssessedRiskSerializer(obj).data)

    def post(self, request, pk):
        """Transition status."""
        obj = _scoped(request, pk)
        if obj is None:
            return Response({"error": "not found."}, status=status.HTTP_404_NOT_FOUND)
        try:
            ar.set_status(risk=obj, actor=request.user, status=request.data.get("status"))
        except ar.AssessedRiskError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(AssessedRiskSerializer(obj).data)


class EngagementRiskSummaryView(APIView):
    """Per-engagement assessed-risk counts by status + significant/fraud."""
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    @extend_schema(tags=["Audit · Assessed Risks"], summary="Assessed-risk summary")
    def get(self, request, pk):
        org = _org(request)
        engagement = AuditEngagement.objects.filter(pk=pk, organization=org).first()
        if engagement is None:
            return Response({"error": "engagement not found in your organization."},
                            status=status.HTTP_404_NOT_FOUND)
        return Response(ar.summary(organization=org, engagement=engagement))


class EngagementFindingsRegisterView(APIView):
    """Unified findings register (G2.3) — GL findings + control deficiencies."""
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    @extend_schema(tags=["Audit · Findings"], summary="Unified findings register")
    def get(self, request, pk):
        org = _org(request)
        engagement = AuditEngagement.objects.filter(pk=pk, organization=org).first()
        if engagement is None:
            return Response({"error": "engagement not found in your organization."},
                            status=status.HTTP_404_NOT_FOUND)
        from apps.audit.services import findings_register as fr
        source = request.query_params.get("source")
        return Response({
            "summary": fr.summary(organization=org, engagement=engagement),
            "findings": fr.list_findings(organization=org, engagement=engagement,
                                         source=source),
        })
