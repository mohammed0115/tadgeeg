"""Substantive Testing API (TADGEEG-FIN-AUDIT-9D · ISA 501 / assets / payroll).

Additive, organization-scoped, auditor-only endpoints for substantive-test
items (book vs independently-tested value) and a per-area summary. Deterministic
recompute; a variance is flagged, never auto-corrected; no ledger writes.
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from apps.authentication.permissions import IsSeniorAuditorOrAbove

from .engagement_models import AuditEngagement
from .serializers import SubstantiveTestItemSerializer
from .services import substantive_testing as st
from .substantive_test_models import SubstantiveTestItem


def _org(request):
    return getattr(request.user, "organization", None)


def _scoped(request, pk):
    org = _org(request)
    if org is None or not pk:
        return None
    return SubstantiveTestItem.objects.filter(pk=pk, organization=org).first()


class SubstantiveItemListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    @extend_schema(tags=["Audit · Substantive Testing"], summary="List substantive-test items")
    def get(self, request):
        org = _org(request)
        if org is None:
            return Response({"error": "no organization."}, status=status.HTTP_400_BAD_REQUEST)
        qs = SubstantiveTestItem.objects.filter(organization=org)
        eng = request.query_params.get("engagement")
        if eng:
            qs = qs.filter(engagement_id=eng)
        area = request.query_params.get("area")
        if area:
            qs = qs.filter(area=area)
        return Response(SubstantiveTestItemSerializer(qs[:500], many=True).data)

    @extend_schema(tags=["Audit · Substantive Testing"], summary="Create a substantive-test item")
    def post(self, request):
        org = _org(request)
        d = request.data
        engagement = AuditEngagement.objects.filter(
            pk=d.get("engagement"), organization=org).first()
        if engagement is None:
            return Response({"error": "engagement not found in your organization."},
                            status=status.HTTP_404_NOT_FOUND)
        try:
            obj = st.create_item(
                engagement=engagement, actor=request.user,
                area=d.get("area", SubstantiveTestItem.Area.INVENTORY),
                book_value=d.get("book_value", 0),
                item_reference=d.get("item_reference", ""),
                description=d.get("description", ""),
                tested_value=d.get("tested_value"),
                tolerance=d.get("tolerance", 0),
                inputs=d.get("inputs") or {},
                quantity_book=d.get("quantity_book"),
                quantity_counted=d.get("quantity_counted"))
        except Exception as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(SubstantiveTestItemSerializer(obj).data,
                        status=status.HTTP_201_CREATED)


class SubstantiveItemDetailView(APIView):
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    @extend_schema(tags=["Audit · Substantive Testing"], summary="Item detail")
    def get(self, request, pk):
        obj = _scoped(request, pk)
        if obj is None:
            return Response({"error": "not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(SubstantiveTestItemSerializer(obj).data)

    def post(self, request, pk):
        """Record the tested value, or cancel the item."""
        obj = _scoped(request, pk)
        if obj is None:
            return Response({"error": "not found."}, status=status.HTTP_404_NOT_FOUND)
        action = request.data.get("action", "record")
        try:
            if action == "cancel":
                st.cancel(item=obj, actor=request.user)
            else:
                if request.data.get("tested_value") is None:
                    return Response({"error": "tested_value required."},
                                    status=status.HTTP_400_BAD_REQUEST)
                st.record_tested(item=obj, actor=request.user,
                                 tested_value=request.data.get("tested_value"),
                                 note=request.data.get("note", ""))
        except st.SubstantiveTestError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(SubstantiveTestItemSerializer(obj).data)


class EngagementSubstantiveSummaryView(APIView):
    """Per-area counts + net variance for an engagement."""
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    @extend_schema(tags=["Audit · Substantive Testing"], summary="Substantive area summary")
    def get(self, request, pk):
        org = _org(request)
        engagement = AuditEngagement.objects.filter(pk=pk, organization=org).first()
        if engagement is None:
            return Response({"error": "engagement not found in your organization."},
                            status=status.HTTP_404_NOT_FOUND)
        return Response(st.area_summary(organization=org, engagement=engagement))
