"""External Confirmations API (TADGEEG-FIN-AUDIT-9C · ISA 505).

Additive, organization-scoped, auditor-only endpoints over the confirmation
workflow. Advisory: a discrepancy is flagged, never auto-posted; no ledger
writes.
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from apps.authentication.permissions import IsSeniorAuditorOrAbove

from .confirmation_models import AuditConfirmationRequest
from .engagement_models import AuditEngagement
from .serializers import AuditConfirmationRequestSerializer
from .services import confirmation_request as cs


def _org(request):
    return getattr(request.user, "organization", None)


def _scoped(request, pk):
    org = _org(request)
    if org is None or not pk:
        return None
    return AuditConfirmationRequest.objects.filter(pk=pk, organization=org).first()


class ConfirmationListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    @extend_schema(tags=["Audit · Confirmations"], summary="List confirmations")
    def get(self, request):
        org = _org(request)
        if org is None:
            return Response({"error": "no organization."}, status=status.HTTP_400_BAD_REQUEST)
        qs = AuditConfirmationRequest.objects.filter(organization=org)
        eng = request.query_params.get("engagement")
        if eng:
            qs = qs.filter(engagement_id=eng)
        st = request.query_params.get("status")
        if st:
            qs = qs.filter(status=st)
        return Response(AuditConfirmationRequestSerializer(qs[:300], many=True).data)

    @extend_schema(tags=["Audit · Confirmations"], summary="Create a confirmation")
    def post(self, request):
        org = _org(request)
        d = request.data
        engagement = AuditEngagement.objects.filter(
            pk=d.get("engagement"), organization=org).first()
        if engagement is None:
            return Response({"error": "engagement not found in your organization."},
                            status=status.HTTP_404_NOT_FOUND)
        try:
            req = cs.create_confirmation(
                engagement=engagement, actor=request.user,
                party_name=d.get("party_name", ""),
                recorded_amount=d.get("recorded_amount", 0),
                confirmation_type=d.get("confirmation_type",
                                        AuditConfirmationRequest.ConfirmationType.RECEIVABLE),
                currency=d.get("currency", "SAR"),
                party_reference=d.get("party_reference", ""),
                party_email=d.get("party_email", ""),
                tolerance=d.get("tolerance", 0))
        except Exception as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(AuditConfirmationRequestSerializer(req).data,
                        status=status.HTTP_201_CREATED)


class ConfirmationDetailView(APIView):
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    @extend_schema(tags=["Audit · Confirmations"], summary="Confirmation detail")
    def get(self, request, pk):
        req = _scoped(request, pk)
        if req is None:
            return Response({"error": "not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(AuditConfirmationRequestSerializer(req).data)


class ConfirmationActionView(APIView):
    """POST an action: send / record / reconcile / no_reply / cancel."""
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    @extend_schema(tags=["Audit · Confirmations"], summary="Act on a confirmation")
    def post(self, request, pk, action):
        req = _scoped(request, pk)
        if req is None:
            return Response({"error": "not found."}, status=status.HTTP_404_NOT_FOUND)
        try:
            if action == "send":
                cs.send(request=req, actor=request.user)
            elif action == "record":
                cs.record_response(request=req, actor=request.user,
                                   confirmed_amount=request.data.get("confirmed_amount"),
                                   note=request.data.get("note", ""))
            elif action == "reconcile":
                cs.reconcile(request=req, actor=request.user)
            elif action == "no_reply":
                cs.mark_no_reply(request=req, actor=request.user)
            elif action == "cancel":
                cs.cancel(request=req, actor=request.user)
            else:
                return Response({"error": "unknown action."},
                                status=status.HTTP_400_BAD_REQUEST)
        except cs.ConfirmationError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(AuditConfirmationRequestSerializer(req).data)
