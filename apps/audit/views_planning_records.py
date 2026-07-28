"""Engagement planning records API (TADGEEG-FIN-AUDIT-9H).

Read/delete the saved ISA 300/330/240 artifacts for an engagement. Additive,
organization-scoped, auditor-only; no ledger writes.
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from apps.authentication.permissions import IsSeniorAuditorOrAbove

from .engagement_models import AuditEngagement
from .planning_record_models import EngagementPlanningRecord
from .serializers import EngagementPlanningRecordSerializer
from .services import planning_records as pr


def _org(request):
    return getattr(request.user, "organization", None)


class EngagementPlanningRecordsView(APIView):
    """List saved planning records for an engagement (filter by ?kind=)."""
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    @extend_schema(tags=["Audit · Planning Records"], summary="List planning records")
    def get(self, request, pk):
        org = _org(request)
        engagement = AuditEngagement.objects.filter(pk=pk, organization=org).first()
        if engagement is None:
            return Response({"error": "engagement not found in your organization."},
                            status=status.HTTP_404_NOT_FOUND)
        records = pr.list_records(engagement=engagement,
                                  kind=request.query_params.get("kind"))
        return Response(EngagementPlanningRecordSerializer(records, many=True).data)


class PlanningRecordDetailView(APIView):
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    @extend_schema(tags=["Audit · Planning Records"], summary="Planning record detail")
    def get(self, request, pk):
        org = _org(request)
        rec = EngagementPlanningRecord.objects.filter(pk=pk, organization=org).first()
        if rec is None:
            return Response({"error": "not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(EngagementPlanningRecordSerializer(rec).data)

    def delete(self, request, pk):
        org = _org(request)
        rec = EngagementPlanningRecord.objects.filter(pk=pk, organization=org).first()
        if rec is None:
            return Response({"error": "not found."}, status=status.HTTP_404_NOT_FOUND)
        pr.delete_record(record=rec, actor=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)
