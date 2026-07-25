"""Management Letter API (TADGEEG-FIN-AUDIT-9B · ISA 265).

Additive, organization-scoped, auditor-only endpoints for control deficiencies
and the generated Management Letter (JSON or HTML). Advisory: not an opinion,
no ledger writes.
"""
from __future__ import annotations

from django.http import HttpResponse
from django.template.loader import render_to_string
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import BaseRenderer, JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from apps.authentication.permissions import IsSeniorAuditorOrAbove

from .control_deficiency_models import AuditControlDeficiency
from .engagement_models import AuditEngagement
from .general_ledger_models import GeneralLedgerRiskFinding
from .serializers import AuditControlDeficiencySerializer
from .services import management_letter as ml


def _org(request):
    return getattr(request.user, "organization", None)


def _scoped(request, pk):
    org = _org(request)
    if org is None or not pk:
        return None
    return AuditControlDeficiency.objects.filter(pk=pk, organization=org).first()


class DeficiencyListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    @extend_schema(tags=["Audit · Management Letter"], summary="List control deficiencies")
    def get(self, request):
        org = _org(request)
        if org is None:
            return Response({"error": "no organization."}, status=status.HTTP_400_BAD_REQUEST)
        qs = AuditControlDeficiency.objects.filter(organization=org)
        eng = request.query_params.get("engagement")
        if eng:
            qs = qs.filter(engagement_id=eng)
        return Response(AuditControlDeficiencySerializer(qs[:300], many=True).data)

    @extend_schema(tags=["Audit · Management Letter"], summary="Record a deficiency")
    def post(self, request):
        org = _org(request)
        d = request.data
        engagement = AuditEngagement.objects.filter(
            pk=d.get("engagement"), organization=org).first()
        if engagement is None:
            return Response({"error": "engagement not found in your organization."},
                            status=status.HTTP_404_NOT_FOUND)
        gl_finding = None
        if d.get("gl_finding"):
            gl_finding = GeneralLedgerRiskFinding.objects.filter(
                pk=d.get("gl_finding"), organization=org, engagement=engagement).first()
        try:
            obj = ml.create_deficiency(
                engagement=engagement, actor=request.user, title=d.get("title", ""),
                classification=d.get("classification",
                                     AuditControlDeficiency.Classification.OTHER_DEFICIENCY),
                area=d.get("area", AuditControlDeficiency.Area.OTHER),
                description=d.get("description", ""),
                potential_effect=d.get("potential_effect", ""),
                recommendation=d.get("recommendation", ""), gl_finding=gl_finding)
        except Exception as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(AuditControlDeficiencySerializer(obj).data,
                        status=status.HTTP_201_CREATED)


class DeficiencyDetailView(APIView):
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    @extend_schema(tags=["Audit · Management Letter"], summary="Deficiency detail / response")
    def get(self, request, pk):
        d = _scoped(request, pk)
        if d is None:
            return Response({"error": "not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(AuditControlDeficiencySerializer(d).data)

    def post(self, request, pk):
        """Record management response or set status."""
        d = _scoped(request, pk)
        if d is None:
            return Response({"error": "not found."}, status=status.HTTP_404_NOT_FOUND)
        try:
            if request.data.get("management_response") is not None:
                ml.record_management_response(
                    deficiency=d, actor=request.user,
                    response=request.data.get("management_response", ""),
                    owner=request.data.get("management_action_owner", ""),
                    target_date=request.data.get("target_date") or None)
            if request.data.get("status"):
                ml.set_status(deficiency=d, actor=request.user,
                              status=request.data.get("status"))
        except ml.ManagementLetterError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(AuditControlDeficiencySerializer(d).data)


class _PassthroughHTMLRenderer(BaseRenderer):
    media_type = "text/html"
    format = "html"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return data


class EngagementManagementLetterView(APIView):
    """GET the generated management letter as JSON (default) or HTML."""
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]
    renderer_classes = [JSONRenderer, _PassthroughHTMLRenderer]

    @extend_schema(tags=["Audit · Management Letter"], summary="Generate management letter")
    def get(self, request, pk):
        org = _org(request)
        engagement = AuditEngagement.objects.filter(pk=pk, organization=org).first()
        if engagement is None:
            return Response({"error": "engagement not found in your organization."},
                            status=status.HTTP_404_NOT_FOUND)
        letter = ml.build_management_letter(engagement=engagement)
        if (request.query_params.get("format") or "json").lower() == "html":
            html = render_to_string("audit/management_letter/letter.html", {"L": letter})
            return HttpResponse(html, content_type="text/html; charset=utf-8")
        return Response(letter)
