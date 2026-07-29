"""Engagement Member API (TADGEEG-G3.3). Auditor-only, org-scoped. No ledger writes."""
from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from apps.authentication.models import User
from apps.authentication.permissions import IsSeniorAuditorOrAbove

from .engagement_models import AuditEngagement
from .member_models import EngagementMember
from .services import engagement_member as em


def _org(request):
    return getattr(request.user, "organization", None)


def _row(m: EngagementMember) -> dict:
    return {"id": str(m.id), "user": str(m.user_id), "role": m.role,
            "user_name": getattr(m.user, "full_name", "") or "",
            "responsibilities": m.responsibilities, "due_date": m.due_date,
            "is_active": m.is_active}


class EngagementMemberListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    @extend_schema(tags=["Audit · Members"], summary="List / assign engagement members")
    def get(self, request, pk):
        eng = AuditEngagement.objects.filter(pk=pk, organization=_org(request)).first()
        if eng is None:
            return Response({"error": "engagement not found in your organization."},
                            status=status.HTTP_404_NOT_FOUND)
        return Response([_row(m) for m in em.list_members(engagement=eng)])

    @extend_schema(tags=["Audit · Members"], summary="Assign a member")
    def post(self, request, pk):
        org = _org(request)
        eng = AuditEngagement.objects.filter(pk=pk, organization=org).first()
        if eng is None:
            return Response({"error": "engagement not found in your organization."},
                            status=status.HTTP_404_NOT_FOUND)
        user = User.objects.filter(pk=request.data.get("user"), organization=org).first()
        if user is None:
            return Response({"error": "user not found in your organization."},
                            status=status.HTTP_404_NOT_FOUND)
        try:
            obj = em.assign(engagement=eng, actor=request.user, user=user,
                            role=request.data.get("role"),
                            responsibilities=request.data.get("responsibilities", ""),
                            due_date=request.data.get("due_date") or None)
        except em.EngagementMemberError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(_row(obj), status=status.HTTP_201_CREATED)


class EngagementMemberDetailView(APIView):
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    @extend_schema(tags=["Audit · Members"], summary="Remove (deactivate) a member")
    def delete(self, request, pk):
        m = EngagementMember.objects.filter(pk=pk, organization=_org(request)).first()
        if m is None:
            return Response({"error": "not found."}, status=status.HTTP_404_NOT_FOUND)
        em.remove(member=m, actor=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)
