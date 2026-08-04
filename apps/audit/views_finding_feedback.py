"""Endpoints for the finding feedback loop.

    POST /api/v1/audit/findings/<uuid>/verdict/   record a judgement
    GET  /api/v1/audit/rule-precision/            what the judgements add up to

The precision endpoint deliberately reports coverage alongside the numbers. A
precision of 1.0 from two judged findings is not a fact about the engine, and
serving the ratio without the sample size invites exactly the unsourced
accuracy claim this work removed from the marketing pages.
"""

from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import status as drf_status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import AuditFinding
from apps.audit.services.finding_feedback import FeedbackError, FindingFeedbackService


class FindingVerdictView(APIView):
    """POST a verdict on one finding."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        organization = getattr(request.user, "organization", None)
        if organization is None:
            return Response({"detail": "User is not attached to an organization."},
                            status=drf_status.HTTP_400_BAD_REQUEST)

        # Scoped by organisation in the lookup, so a finding belonging to
        # another tenant is a 404 rather than a 403 — a 403 would confirm the
        # id exists.
        finding = get_object_or_404(AuditFinding, pk=pk, organization=organization)

        try:
            finding = FindingFeedbackService().record_verdict(
                finding=finding,
                user=request.user,
                verdict=request.data.get("verdict", ""),
                note=request.data.get("note", ""),
            )
        except FeedbackError as exc:
            # FeedbackError messages are written to be read by the person who
            # made the request; nothing internal travels in them.
            return Response({"detail": str(exc)}, status=drf_status.HTTP_400_BAD_REQUEST)

        return Response({
            "id": str(finding.id),
            "verdict": finding.verdict,
            "verdict_at": finding.verdict_at,
            # Name, not email — matching AuditFindingSerializer, so the UI
            # renders the same thing whether a finding came from the list or
            # from this response. An email address is more than the card needs.
            "verdict_by_name": getattr(finding.verdict_by, "full_name", "") or "",
            "note": finding.verdict_note,
        })


class RulePrecisionView(APIView):
    """GET measured precision per rule for the caller's organisation."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        organization = getattr(request.user, "organization", None)
        if organization is None:
            return Response({"detail": "User is not attached to an organization."},
                            status=drf_status.HTTP_400_BAD_REQUEST)

        service = FindingFeedbackService()
        return Response({
            "coverage": service.coverage(organization),
            "rules": service.rule_precision(
                organization, rule_code=request.query_params.get("rule_code") or None
            ),
        })
