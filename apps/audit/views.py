"""Audit Case Views"""

from django.utils import timezone
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, OpenApiParameter
from apps.authentication.models import User
from apps.authentication.permissions import IsSeniorAuditorOrAbove
from .models import AuditCase, CaseComment
from .serializers import AuditCaseSerializer, CaseCommentSerializer


class AuditCaseListCreateView(generics.ListCreateAPIView):
    serializer_class = AuditCaseSerializer
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Audit"],
        summary="List audit cases",
        parameters=[
            OpenApiParameter("status", description="Filter by status"),
            OpenApiParameter("priority", description="Filter by priority"),
            OpenApiParameter("case_type", description="Filter by type"),
            OpenApiParameter("assigned_to", description="Filter by assignee ID"),
        ],
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        qs = AuditCase.objects.filter(organization=self.request.user.organization).select_related(
            "assigned_to", "created_by", "transaction", "invoice"
        )
        p = self.request.query_params
        if v := p.get("status"):
            qs = qs.filter(status=v)
        if v := p.get("priority"):
            qs = qs.filter(priority=v)
        if v := p.get("case_type"):
            qs = qs.filter(case_type=v)
        if v := p.get("assigned_to"):
            qs = qs.filter(assigned_to_id=v)
        return qs

    def perform_create(self, serializer):
        serializer.save(
            organization=self.request.user.organization,
            created_by=self.request.user,
        )


class AuditCaseDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = AuditCaseSerializer
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Audit"], summary="Get or update an audit case")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        return AuditCase.objects.filter(organization=self.request.user.organization).select_related(
            "assigned_to", "created_by", "resolved_by", "transaction", "invoice"
        ).prefetch_related("comments")


class UpdateCaseStatusView(APIView):
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    @extend_schema(
        tags=["Audit"],
        summary="Update the status of an audit case",
        request={"type": "object", "properties": {
            "status": {"type": "string"},
            "resolution_notes": {"type": "string"},
        }},
    )
    def patch(self, request, pk):
        try:
            case = AuditCase.objects.get(pk=pk, organization=request.user.organization)
        except AuditCase.DoesNotExist:
            return Response({"error": "Case not found."}, status=404)

        new_status = request.data.get("status")
        if new_status not in AuditCase.CaseStatus.values:
            return Response({"error": f"Invalid status. Choose from: {AuditCase.CaseStatus.values}"}, status=400)

        case.status = new_status
        if notes := request.data.get("resolution_notes"):
            case.resolution_notes = notes
        if new_status in [AuditCase.CaseStatus.RESOLVED, AuditCase.CaseStatus.CLOSED]:
            case.resolved_at = timezone.now()
            case.resolved_by = request.user
        case.save()

        return Response(AuditCaseSerializer(case).data)


class CaseCommentView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Audit"], summary="List comments on a case")
    def get(self, request, pk):
        try:
            case = AuditCase.objects.get(pk=pk, organization=request.user.organization)
        except AuditCase.DoesNotExist:
            return Response({"error": "Case not found."}, status=404)
        comments = case.comments.select_related("author").all()
        return Response(CaseCommentSerializer(comments, many=True).data)

    @extend_schema(tags=["Audit"], summary="Add a comment to a case")
    def post(self, request, pk):
        try:
            case = AuditCase.objects.get(pk=pk, organization=request.user.organization)
        except AuditCase.DoesNotExist:
            return Response({"error": "Case not found."}, status=404)

        comment = CaseComment.objects.create(
            case=case,
            author=request.user,
            text=request.data.get("text", ""),
            is_internal=request.data.get("is_internal", False),
        )
        return Response(CaseCommentSerializer(comment).data, status=201)


class AssignCaseView(APIView):
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    @extend_schema(
        tags=["Audit"],
        summary="Assign an audit case to a user",
        request={"type": "object", "properties": {
            "user_id": {"type": "string", "format": "uuid"},
        }},
    )
    def post(self, request, pk):
        try:
            case = AuditCase.objects.get(pk=pk, organization=request.user.organization)
        except AuditCase.DoesNotExist:
            return Response({"error": "Case not found."}, status=404)

        user_id = request.data.get("user_id")
        if not user_id:
            return Response({"error": "user_id is required."}, status=400)

        try:
            assignee = User.objects.get(
                pk=user_id,
                organization=request.user.organization,
                is_active=True,
            )
        except User.DoesNotExist:
            return Response({"error": "Assignee not found."}, status=404)

        case.assigned_to = assignee
        case.save(update_fields=["assigned_to", "updated_at"])

        return Response({
            "id": str(case.id),
            "assigned_to": str(assignee.id),
            "assigned_to_id": str(assignee.id),
            "assigned_to_name": assignee.full_name,
        })
