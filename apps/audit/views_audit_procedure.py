"""Audit Procedure API (TADGEEG-G2.2 · ISA 330 — Risk->Procedure link).

Additive, organization-scoped, auditor-only. Junior -> 403; cross-org -> 404.
No ledger writes.
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
from .procedure_models import AuditProcedure
from .serializers import AuditProcedureSerializer
from .services import audit_procedure as ap


def _org(request):
    return getattr(request.user, "organization", None)


def _scoped(request, pk):
    org = _org(request)
    if org is None or not pk:
        return None
    return AuditProcedure.objects.filter(pk=pk, organization=org).first()


class ProcedureListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    @extend_schema(tags=["Audit · Procedures"], summary="List audit procedures")
    def get(self, request):
        org = _org(request)
        if org is None:
            return Response({"error": "no organization."}, status=status.HTTP_400_BAD_REQUEST)
        qs = (AuditProcedure.objects.filter(organization=org)
              .select_related("assessed_risk", "created_by", "performed_by"))
        eng = request.query_params.get("engagement")
        if eng:
            qs = qs.filter(engagement_id=eng)
        risk = request.query_params.get("assessed_risk")
        if risk:
            qs = qs.filter(assessed_risk_id=risk)
        return Response(AuditProcedureSerializer(qs[:500], many=True).data)

    @extend_schema(tags=["Audit · Procedures"], summary="Create an audit procedure")
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
            if risk is None:
                return Response({"error": "assessed_risk not found in this engagement."},
                                status=status.HTTP_404_NOT_FOUND)
        try:
            obj = ap.create_procedure(
                engagement=engagement, actor=request.user, title=d.get("title", ""),
                assessed_risk=risk, nature=d.get("nature"), timing=d.get("timing"),
                extent=d.get("extent"), description=d.get("description", ""))
        except ap.AuditProcedureError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:  # noqa: BLE001
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(AuditProcedureSerializer(obj).data, status=status.HTTP_201_CREATED)


class ProcedureDetailView(APIView):
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    @extend_schema(tags=["Audit · Procedures"], summary="Procedure detail / status / link")
    def get(self, request, pk):
        obj = _scoped(request, pk)
        if obj is None:
            return Response({"error": "not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(AuditProcedureSerializer(obj).data)

    def post(self, request, pk):
        """Set status/conclusion, or (re)link an assessed risk."""
        obj = _scoped(request, pk)
        if obj is None:
            return Response({"error": "not found."}, status=status.HTTP_404_NOT_FOUND)
        try:
            if "assessed_risk" in request.data:
                rid = request.data.get("assessed_risk")
                risk = None
                if rid:
                    risk = AssessedRisk.objects.filter(
                        pk=rid, organization=obj.organization,
                        engagement=obj.engagement).first()
                    if risk is None:
                        return Response({"error": "assessed_risk not found."},
                                        status=status.HTTP_404_NOT_FOUND)
                ap.link_risk(procedure=obj, assessed_risk=risk, actor=request.user)
            if request.data.get("status"):
                ap.set_status(procedure=obj, actor=request.user,
                              status=request.data.get("status"),
                              conclusion=request.data.get("conclusion", ""))
        except ap.AuditProcedureError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(AuditProcedureSerializer(obj).data)


class EngagementProcedureSummaryView(APIView):
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    @extend_schema(tags=["Audit · Procedures"], summary="Procedure summary")
    def get(self, request, pk):
        org = _org(request)
        engagement = AuditEngagement.objects.filter(pk=pk, organization=org).first()
        if engagement is None:
            return Response({"error": "engagement not found in your organization."},
                            status=status.HTTP_404_NOT_FOUND)
        return Response(ap.summary(organization=org, engagement=engagement))
