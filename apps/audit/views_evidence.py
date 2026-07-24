"""Evidence Request workflow API (TADGEEG-FIN-AUDIT-6A).

Organization-scoped DRF endpoints over the evidence-request workflow. Every
query is scoped to ``request.user.organization``; a request in another org is
simply not found (404, no existence leak). Create/review/cancel and, in this
phase, submit/upload require auditor+ (``IsSeniorAuditorOrAbove``). Nothing here
posts to the ledger or issues an opinion.
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from apps.authentication.models import User
from apps.authentication.permissions import IsSeniorAuditorOrAbove

from .audit_difference_models import AuditDifferenceItem
from .engagement_models import AuditEngagement
from .evidence_models import AuditEvidenceRequest
from .general_ledger_models import GeneralLedgerRiskFinding
from .serializers import (
    AuditEvidenceAttachmentSerializer,
    AuditEvidenceRequestEventSerializer,
    AuditEvidenceRequestListSerializer,
    AuditEvidenceRequestSerializer,
)
from .services import evidence_request as ev_service


def _user_org(request):
    return getattr(request.user, "organization", None)


def _scoped_request(request, pk):
    org = _user_org(request)
    if not org or not pk:
        return None
    return (AuditEvidenceRequest.objects
            .filter(pk=pk, organization=org)
            .select_related("engagement", "gl_finding", "sad_item",
                            "requested_by", "assigned_to", "assigned_client_user",
                            "reviewed_by")
            .first())


def _is_auditor(user) -> bool:
    """auditor+ (the same capability IsSeniorAuditorOrAbove checks)."""
    try:
        return bool(user.has_role_capability("approve_invoices"))
    except Exception:
        return False


def _is_assigned_client(user, req) -> bool:
    """TADGEEG-FIN-AUDIT-6B — client access is per-request, not role-based."""
    return bool(req.assigned_client_user_id
                and req.assigned_client_user_id == getattr(user, "pk", None))


def _can_upload(user, req) -> bool:
    """Auditors may upload; so may the client user assigned to THIS request."""
    return _is_auditor(user) or _is_assigned_client(user, req)


def _can_view(user, req) -> bool:
    """A client sees ONLY the requests assigned to them; auditors see the org."""
    return _is_auditor(user) or _is_assigned_client(user, req)


def _visible_request(request, pk):
    """Org-scoped lookup that also hides other users' requests from a client."""
    req = _scoped_request(request, pk)
    if req is None or not _can_view(request.user, req):
        return None  # 404 — never leak existence to a non-entitled user
    return req


class EvidenceRequestListCreateView(APIView):
    """GET: list evidence requests in the user's org. POST: create one (auditor+)."""

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticated(), IsSeniorAuditorOrAbove()]
        return [IsAuthenticated()]

    @extend_schema(tags=["Audit · Evidence"], summary="List evidence requests")
    def get(self, request):
        org = _user_org(request)
        if org is None:
            return Response({"error": "no organization."}, status=status.HTTP_400_BAD_REQUEST)
        qs = (AuditEvidenceRequest.objects
              .filter(organization=org)
              .select_related("requested_by", "assigned_to", "assigned_client_user"))
        # 6B: a non-auditor only ever sees requests assigned to them as client.
        if not _is_auditor(request.user):
            qs = qs.filter(assigned_client_user=request.user)
        # Optional filters.
        eng_id = request.query_params.get("engagement")
        if eng_id:
            qs = qs.filter(engagement_id=eng_id)
        st = request.query_params.get("status")
        if st:
            qs = qs.filter(status=st)
        finding_id = request.query_params.get("gl_finding")
        if finding_id:
            qs = qs.filter(gl_finding_id=finding_id)
        return Response(AuditEvidenceRequestListSerializer(qs, many=True).data)

    @extend_schema(tags=["Audit · Evidence"], summary="Create an evidence request")
    def post(self, request):
        org = _user_org(request)
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
            if gl_finding is None:
                return Response({"error": "gl_finding not found in this engagement."},
                                status=status.HTTP_404_NOT_FOUND)
        sad_item = None
        if d.get("sad_item"):
            sad_item = AuditDifferenceItem.objects.filter(
                pk=d.get("sad_item"), organization=org, engagement=engagement).first()
            if sad_item is None:
                return Response({"error": "sad_item not found in this engagement."},
                                status=status.HTTP_404_NOT_FOUND)

        try:
            req = ev_service.create_evidence_request(
                engagement=engagement, actor=request.user, title=d.get("title", ""),
                gl_finding=gl_finding, sad_item=sad_item,
                description=d.get("description", ""),
                request_reason=d.get("request_reason", AuditEvidenceRequest.RequestReason.SUPPORT_FINDING),
                priority=d.get("priority", AuditEvidenceRequest.Priority.MEDIUM),
                due_date=d.get("due_date") or None,
                assigned_to=User.objects.filter(
                    pk=d.get("assigned_to"), organization=org).first()
                    if d.get("assigned_to") else None,
                assigned_client_user=User.objects.filter(
                    pk=d.get("assigned_client_user"), organization=org).first()
                    if d.get("assigned_client_user") else None)
        except Exception as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(AuditEvidenceRequestSerializer(req).data,
                        status=status.HTTP_201_CREATED)


class EvidenceRequestDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Audit · Evidence"], summary="Evidence request detail")
    def get(self, request, pk):
        req = _visible_request(request, pk)
        if req is None:
            return Response({"error": "not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(AuditEvidenceRequestSerializer(req).data)


class EvidenceRequestSubmitView(APIView):
    """Submit evidence for review — auditor+ or the assigned client user."""
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Audit · Evidence"], summary="Submit evidence for review")
    def post(self, request, pk):
        req = _scoped_request(request, pk)
        if req is None:
            return Response({"error": "not found."}, status=status.HTTP_404_NOT_FOUND)
        if not _can_upload(request.user, req):
            return Response({"error": "forbidden."}, status=status.HTTP_403_FORBIDDEN)
        try:
            req = ev_service.submit_evidence(request=req, actor=request.user)
        except ev_service.EvidenceRequestError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(AuditEvidenceRequestSerializer(req).data)


class EvidenceRequestReviewView(APIView):
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    @extend_schema(tags=["Audit · Evidence"],
                   summary="Review an evidence request (accept/reject/etc.)")
    def post(self, request, pk):
        req = _scoped_request(request, pk)
        if req is None:
            return Response({"error": "not found."}, status=status.HTTP_404_NOT_FOUND)
        try:
            req = ev_service.review_evidence_request(
                request=req, actor=request.user,
                action=request.data.get("action", ""),
                note=request.data.get("note", ""))
        except ev_service.EvidenceRequestError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(AuditEvidenceRequestSerializer(req).data)


class EvidenceRequestAttachmentsView(APIView):
    """Attachments. Auditors, and the assigned CLIENT user, may read/upload.

    Client access is authorized per-request via ``assigned_client_user`` (6B),
    so no role/authentication change is required.
    """
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Audit · Evidence"], summary="List evidence attachments")
    def get(self, request, pk):
        req = _scoped_request(request, pk)
        if req is None:
            return Response({"error": "not found."}, status=status.HTTP_404_NOT_FOUND)
        if not _can_upload(request.user, req):
            return Response({"error": "forbidden."}, status=status.HTTP_403_FORBIDDEN)
        return Response(AuditEvidenceAttachmentSerializer(
            req.attachments.all(), many=True).data)

    @extend_schema(tags=["Audit · Evidence"], summary="Upload an evidence attachment")
    def post(self, request, pk):
        req = _scoped_request(request, pk)
        if req is None:
            return Response({"error": "not found."}, status=status.HTTP_404_NOT_FOUND)
        if not _can_upload(request.user, req):
            return Response({"error": "forbidden."}, status=status.HTTP_403_FORBIDDEN)
        client_upload = _is_assigned_client(request.user, req)
        try:
            att = ev_service.add_attachment(
                request=req, actor=request.user,
                uploaded_file=request.FILES.get("file"),
                description=request.data.get("description", ""),
                notify_auditor=client_upload)
        except ev_service.EvidenceRequestError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(AuditEvidenceAttachmentSerializer(att).data,
                        status=status.HTTP_201_CREATED)


class EvidenceRequestAssignView(APIView):
    """Assign/reassign the auditor and/or client user (auditor+ only)."""
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    @extend_schema(tags=["Audit · Evidence"], summary="Assign auditor / client user")
    def post(self, request, pk):
        req = _scoped_request(request, pk)
        if req is None:
            return Response({"error": "not found."}, status=status.HTTP_404_NOT_FOUND)
        org = _user_org(request)
        kwargs = {}
        if "assigned_to" in request.data:
            value = request.data.get("assigned_to")
            kwargs["assigned_to"] = User.objects.filter(
                pk=value, organization=org).first() if value else None
            if value and kwargs["assigned_to"] is None:
                return Response({"error": "assigned_to not found in your organization."},
                                status=status.HTTP_404_NOT_FOUND)
        if "assigned_client_user" in request.data:
            value = request.data.get("assigned_client_user")
            kwargs["assigned_client_user"] = User.objects.filter(
                pk=value, organization=org).first() if value else None
            if value and kwargs["assigned_client_user"] is None:
                return Response({"error": "assigned_client_user not found in your organization."},
                                status=status.HTTP_404_NOT_FOUND)
        try:
            req = ev_service.assign_users(request=req, actor=request.user, **kwargs)
        except ev_service.EvidenceRequestError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(AuditEvidenceRequestSerializer(req).data)


class EvidenceRequestManagementExplanationView(APIView):
    """Client (or auditor) records the management explanation."""
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Audit · Evidence"], summary="Submit management explanation")
    def post(self, request, pk):
        req = _scoped_request(request, pk)
        if req is None:
            return Response({"error": "not found."}, status=status.HTTP_404_NOT_FOUND)
        if not _can_upload(request.user, req):
            return Response({"error": "forbidden."}, status=status.HTTP_403_FORBIDDEN)
        try:
            req = ev_service.record_management_explanation(
                request=req, actor=request.user,
                explanation=request.data.get("management_explanation", ""))
        except ev_service.EvidenceRequestError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(AuditEvidenceRequestSerializer(req).data)


class EvidenceRequestEventsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Audit · Evidence"], summary="Evidence request event history")
    def get(self, request, pk):
        req = _visible_request(request, pk)
        if req is None:
            return Response({"error": "not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(AuditEvidenceRequestEventSerializer(
            req.events.all(), many=True).data)
