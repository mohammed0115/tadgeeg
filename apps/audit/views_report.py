"""Engagement Report API (TADGEEG-G6). Auditor-only, org-scoped. No ledger writes."""
from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from apps.authentication.permissions import IsSeniorAuditorOrAbove

from .engagement_models import AuditEngagement
from .report_models import EngagementReport
from .services import report_builder as rb


def _org(request):
    return getattr(request.user, "organization", None)


def _row(r: EngagementReport) -> dict:
    return {"id": str(r.id), "reference": r.reference, "title": r.title,
            "version": r.version, "status": r.status,
            "not_an_opinion": r.not_an_opinion, "content": r.content,
            "created_at": r.created_at, "finalized_at": r.finalized_at}


class EngagementReportListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    @extend_schema(tags=["Audit · Reports"], summary="List / build engagement reports")
    def get(self, request, pk):
        eng = AuditEngagement.objects.filter(pk=pk, organization=_org(request)).first()
        if eng is None:
            return Response({"error": "engagement not found in your organization."},
                            status=status.HTTP_404_NOT_FOUND)
        return Response([_row(r) for r in rb.list_reports(engagement=eng)])

    @extend_schema(tags=["Audit · Reports"], summary="Build a draft report")
    def post(self, request, pk):
        eng = AuditEngagement.objects.filter(pk=pk, organization=_org(request)).first()
        if eng is None:
            return Response({"error": "engagement not found in your organization."},
                            status=status.HTTP_404_NOT_FOUND)
        obj = rb.create_report(engagement=eng, actor=request.user,
                               title=request.data.get("title", ""))
        return Response(_row(obj), status=status.HTTP_201_CREATED)


class EngagementReportDetailView(APIView):
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    def _scoped(self, request, pk):
        org = _org(request)
        if org is None or not pk:
            return None
        return EngagementReport.objects.filter(pk=pk, organization=org).first()

    @extend_schema(tags=["Audit · Reports"], summary="Report detail / status / new-version")
    def get(self, request, pk):
        r = self._scoped(request, pk)
        if r is None:
            return Response({"error": "not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(_row(r))

    def post(self, request, pk):
        r = self._scoped(request, pk)
        if r is None:
            return Response({"error": "not found."}, status=status.HTTP_404_NOT_FOUND)
        try:
            if request.data.get("action") == "new_version":
                r = rb.new_version(report=r, actor=request.user)
            elif request.data.get("status"):
                r = rb.set_status(report=r, actor=request.user,
                                  status=request.data.get("status"))
        except rb.ReportBuilderError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(_row(r))
