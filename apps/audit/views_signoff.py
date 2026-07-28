"""Engagement sign-off API (TADGEEG-G3 · ISA 220/230).

Auditor-only, organization-scoped. Junior -> 403; cross-org -> 404. Enforces the
preparer != reviewer segregation rule via the service. No ledger writes.
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from apps.authentication.permissions import IsSeniorAuditorOrAbove

from .engagement_models import AuditEngagement
from .services import signoff as so


def _org(request):
    return getattr(request.user, "organization", None)


class EngagementSignoffView(APIView):
    """GET sign-offs for an artifact (?artifact_type=&artifact_id=), POST a sign-off."""
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    def _engagement(self, request, pk):
        return AuditEngagement.objects.filter(pk=pk, organization=_org(request)).first()

    @extend_schema(tags=["Audit · Sign-off"], summary="Sign-offs for an artifact / status")
    def get(self, request, pk):
        engagement = self._engagement(request, pk)
        if engagement is None:
            return Response({"error": "engagement not found in your organization."},
                            status=status.HTTP_404_NOT_FOUND)
        at = request.query_params.get("artifact_type", "")
        ai = request.query_params.get("artifact_id", "")
        if not at or not ai:
            return Response({"error": "artifact_type and artifact_id are required."},
                            status=status.HTTP_400_BAD_REQUEST)
        rows = so.signoffs_for(engagement=engagement, artifact_type=at, artifact_id=ai)
        return Response({
            "status": so.status_for(engagement=engagement, artifact_type=at, artifact_id=ai),
            "signoffs": [{
                "id": str(r.id), "role": r.role,
                "signed_by": str(r.signed_by_id) if r.signed_by_id else None,
                "signed_by_name": getattr(r.signed_by, "full_name", "") or "",
                "note": r.note, "signed_at": r.signed_at,
            } for r in rows],
        })

    @extend_schema(tags=["Audit · Sign-off"], summary="Record a sign-off")
    def post(self, request, pk):
        engagement = self._engagement(request, pk)
        if engagement is None:
            return Response({"error": "engagement not found in your organization."},
                            status=status.HTTP_404_NOT_FOUND)
        d = request.data
        try:
            row = so.sign(engagement=engagement, actor=request.user,
                          artifact_type=d.get("artifact_type", ""),
                          artifact_id=d.get("artifact_id", ""),
                          role=d.get("role", ""), note=d.get("note", ""))
        except so.SignoffError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"id": str(row.id), "role": row.role,
                         "artifact_type": row.artifact_type,
                         "artifact_id": row.artifact_id},
                        status=status.HTTP_201_CREATED)
