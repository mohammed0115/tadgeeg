"""Evidence delivery & lifecycle API (TADGEEG-FIN-AUDIT-6C).

ADDITIVE endpoints only — nothing from 6A/6B is replaced. Every lookup is
organization-scoped and honours assigned-client visibility (404, never a
disclosure). Attachments are never deleted and never overwritten.
"""
from __future__ import annotations

from django.http import HttpResponse
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import BaseRenderer, JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from apps.authentication.models import User
from apps.authentication.permissions import IsSeniorAuditorOrAbove

from .evidence_models import AuditEvidenceRequest
from .serializers import (
    AuditEvidenceAttachmentSerializer,
    AuditEvidenceRequestListSerializer,
)
from .services import evidence_lifecycle as lc


def _user_org(request):
    return getattr(request.user, "organization", None)


class _BinaryRenderer(BaseRenderer):
    """Lets DRF negotiate a binary response (the view returns HttpResponse)."""
    media_type = "application/octet-stream"
    format = "bin"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return data


class EvidenceAttachmentDownloadView(APIView):
    """GET the attachment bytes — SHA-256 is re-verified BEFORE serving."""
    permission_classes = [IsAuthenticated]
    renderer_classes = [JSONRenderer, _BinaryRenderer]

    @extend_schema(tags=["Audit · Evidence"], summary="Download evidence (integrity-checked)")
    def get(self, request, pk):
        att = lc.scoped_attachment(request.user, pk)
        if att is None:
            return Response({"error": "not found."}, status=status.HTTP_404_NOT_FOUND)
        try:
            data = lc.read_for_download(att, actor=request.user)
        except lc.EvidenceIntegrityError as exc:
            # 409: the object exists but its bytes are not trustworthy.
            return Response({"error": str(exc), "integrity": "failed"},
                            status=status.HTTP_409_CONFLICT)
        except lc.EvidenceLifecycleError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        resp = HttpResponse(data, content_type=att.content_type or "application/octet-stream")
        filename = att.original_filename or f"evidence-{att.id}"
        resp["Content-Disposition"] = f'attachment; filename="{filename}"'
        resp["X-Evidence-SHA256"] = att.file_sha256
        resp["X-Evidence-Version"] = str(att.version)
        return resp


class EvidenceAttachmentVerifyView(APIView):
    """POST/GET: recompute and compare the SHA-256 without downloading."""
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Audit · Evidence"], summary="Verify evidence integrity")
    def get(self, request, pk):
        att = lc.scoped_attachment(request.user, pk)
        if att is None:
            return Response({"error": "not found."}, status=status.HTTP_404_NOT_FOUND)
        result = lc.verify_attachment(att, actor=request.user)
        return Response({**result, "attachment": str(att.id),
                         "badge": att.integrity_badge})

    post = get


class EvidenceAttachmentLifecycleView(APIView):
    """POST archive / restore / freeze on an attachment (auditor+)."""
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    ACTIONS = {
        "archive": lc.archive_attachment,
        "restore": lc.restore_attachment,
        "freeze": lc.freeze_attachment,
    }

    @extend_schema(tags=["Audit · Evidence"], summary="Archive/restore/freeze evidence")
    def post(self, request, pk, action):
        att = lc.scoped_attachment(request.user, pk)
        if att is None:
            return Response({"error": "not found."}, status=status.HTTP_404_NOT_FOUND)
        fn = self.ACTIONS.get(action)
        if fn is None:
            return Response({"error": "unknown action."},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            att = fn(attachment=att, actor=request.user,
                     note=request.data.get("note", ""))
        except lc.EvidenceLifecycleError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(AuditEvidenceAttachmentSerializer(att).data)


class EvidenceRequestVersionsView(APIView):
    """GET the full version history of a request's evidence (incl. archived)."""
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Audit · Evidence"], summary="Evidence version history")
    def get(self, request, pk):
        org = _user_org(request)
        req = AuditEvidenceRequest.objects.filter(pk=pk, organization=org).first() if org else None
        if req is None:
            return Response({"error": "not found."}, status=status.HTTP_404_NOT_FOUND)
        if not lc.is_auditor(request.user) and \
                req.assigned_client_user_id != getattr(request.user, "pk", None):
            return Response({"error": "not found."}, status=status.HTTP_404_NOT_FOUND)
        versions = lc.version_history(req)
        return Response(AuditEvidenceAttachmentSerializer(versions, many=True).data)


class EvidenceQueueView(APIView):
    """GET the auditor review queue with filters, search, sorting + counts."""
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    @extend_schema(tags=["Audit · Evidence"], summary="Auditor evidence queue")
    def get(self, request):
        org = _user_org(request)
        if org is None:
            return Response({"error": "no organization."},
                            status=status.HTTP_400_BAD_REQUEST)
        q = request.query_params
        qs = lc.auditor_queue(
            organization=org, engagement=q.get("engagement"),
            status=q.get("status"), priority=q.get("priority"),
            assigned_to=q.get("assigned_to"), search=q.get("q", ""),
            bucket=q.get("bucket", ""), sort=q.get("sort", "-created"))
        return Response({
            "counts": lc.queue_counts(organization=org, engagement=q.get("engagement")),
            "results": AuditEvidenceRequestListSerializer(qs[:200], many=True).data,
        })


class EvidenceBulkAssignView(APIView):
    """POST: assign one reviewer to many requests in a single transaction."""
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    @extend_schema(tags=["Audit · Evidence"], summary="Bulk assign reviewer")
    def post(self, request):
        org = _user_org(request)
        reviewer_id = request.data.get("reviewer")
        reviewer = User.objects.filter(pk=reviewer_id, organization=org).first() \
            if reviewer_id else None
        if reviewer_id and reviewer is None:
            return Response({"error": "reviewer not found in your organization."},
                            status=status.HTTP_404_NOT_FOUND)
        try:
            result = lc.bulk_assign_reviewer(
                organization=org, request_ids=request.data.get("request_ids", []),
                reviewer=reviewer, actor=request.user)
        except Exception as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(result)


class EvidenceDashboardSummaryView(APIView):
    """GET dashboard cards (waiting / accepted / rejected / overdue / avg time)."""
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    @extend_schema(tags=["Audit · Evidence"], summary="Evidence dashboard summary")
    def get(self, request):
        org = _user_org(request)
        if org is None:
            return Response({"error": "no organization."},
                            status=status.HTTP_400_BAD_REQUEST)
        return Response(lc.dashboard_summary(
            organization=org, engagement=request.query_params.get("engagement")))
