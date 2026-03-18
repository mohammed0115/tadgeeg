"""Audit Case Views"""

from django.utils import timezone
from rest_framework import generics, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication
from drf_spectacular.utils import extend_schema, OpenApiParameter
from django.db.models import Avg, Count, Q, Sum
from apps.authentication.models import User
from apps.authentication.permissions import IsSeniorAuditorOrAbove
from apps.invoices.models import Invoice, InvoiceValidationResult
from apps.invoices.serializers import InvoiceBatchSerializer
from .models import AuditCase, AuditFinding, AuditSession, CaseComment
from .serializers import (
    AuditCaseSerializer,
    AuditFindingSerializer,
    AuditSessionSerializer,
    CaseCommentSerializer,
)
from .services import AuditSessionSummaryService


RULE_GROUP_META = {
    "INV": {"label": "رأس الفاتورة", "color": "#2563eb"},
    "DUP": {"label": "التكرار", "color": "#f59e0b"},
    "VAT": {"label": "الضريبة", "color": "#7c3aed"},
    "ANO": {"label": "الشذوذ", "color": "#ef4444"},
    "CTL": {"label": "الرقابة", "color": "#06b6d4"},
    "DOC": {"label": "المستند", "color": "#16a34a"},
}


def _build_rule_group_summary(validation_qs):
    counters = {
        code: {"passed": 0, "failed": 0, "total": 0}
        for code in RULE_GROUP_META
    }

    for detail_payload in validation_qs.values_list("validation_details", flat=True):
        if not isinstance(detail_payload, dict):
            continue
        for rule_code, detail in detail_payload.items():
            group_code = str(rule_code or "").split("-", 1)[0]
            if group_code not in counters:
                continue
            counters[group_code]["total"] += 1
            if detail.get("passed") is True:
                counters[group_code]["passed"] += 1
            elif detail.get("passed") is False:
                counters[group_code]["failed"] += 1

    summary = []
    for code, meta in RULE_GROUP_META.items():
        total = counters[code]["total"]
        passed = counters[code]["passed"]
        pct = round((passed / total) * 100, 1) if total else 0.0
        summary.append(
            {
                "code": code,
                "label": meta["label"],
                "color": meta["color"],
                "pct": pct,
                "passed": passed,
                "failed": counters[code]["failed"],
                "total": total,
            }
        )
    return summary


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


class AuditSessionDetailView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication, SessionAuthentication]

    @extend_schema(tags=["Audit"], summary="Get audit session detail with progress and invoice rollup")
    def get(self, request, pk):
        try:
            session = AuditSession.objects.get(pk=pk, organization=request.user.organization)
        except AuditSession.DoesNotExist:
            return Response({"error": "Audit session not found."}, status=404)

        invoices_qs = Invoice.objects.filter(audit_session=session).order_by("-created_at")
        stats = invoices_qs.aggregate(
            total_amount=Sum("total_amount"),
            avg_score=Avg("ocr_confidence"),
            flagged=Count("id", filter=Q(status="flagged")),
            approved=Count("id", filter=Q(status="approved")),
            duplicates=Count("id", filter=Q(is_duplicate=True)),
            critical=Count("id", filter=Q(risk_level="critical")),
        )
        batch = session.invoice_batches.order_by("-created_at").first()
        findings_qs = session.findings.select_related("invoice").order_by("-last_detected_at")
        summary_payload = AuditSessionSummaryService.generate_summary(session, language=request.query_params.get("lang", "ar"))
        finding_totals = findings_qs.filter(status=AuditFinding.Status.OPEN).aggregate(
            critical=Count("id", filter=Q(severity=AuditFinding.Severity.CRITICAL)),
            high=Count("id", filter=Q(severity=AuditFinding.Severity.HIGH)),
            medium=Count("id", filter=Q(severity=AuditFinding.Severity.MEDIUM)),
            low=Count("id", filter=Q(severity=AuditFinding.Severity.LOW)),
        )

        return Response({
            "session": AuditSessionSerializer(session).data,
            "batch": InvoiceBatchSerializer(batch).data if batch else None,
            "stats": stats,
            "summary": summary_payload,
            "finding_totals": finding_totals,
            "findings": AuditFindingSerializer(findings_qs[:20], many=True).data,
            "invoices": list(
                invoices_qs.values(
                    "id",
                    "original_filename",
                    "vendor_name",
                    "invoice_number",
                    "total_amount",
                    "currency",
                    "invoice_date",
                    "status",
                    "risk_level",
                    "risk_score",
                    "is_duplicate",
                    "ocr_confidence",
                )
            ),
        })


class AuditSessionProgressView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication, SessionAuthentication]

    @extend_schema(tags=["Audit"], summary="Get machine-readable audit session progress")
    def get(self, request, pk):
        try:
            session = AuditSession.objects.get(pk=pk, organization=request.user.organization)
        except AuditSession.DoesNotExist:
            return Response({"error": "Audit session not found."}, status=404)

        data = AuditSessionSerializer(session).data
        data["ready_for_summary"] = (
            session.status in {
                AuditSession.Status.COMPLETED,
                AuditSession.Status.REVIEW_REQUIRED,
                AuditSession.Status.ACTION_REQUIRED,
            }
            and session.processed_count >= session.total_count
        )
        return Response(data)


class AuditSessionFindingsView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication, SessionAuthentication]

    @extend_schema(tags=["Audit"], summary="List findings for an audit session")
    def get(self, request, pk):
        try:
            session = AuditSession.objects.get(pk=pk, organization=request.user.organization)
        except AuditSession.DoesNotExist:
            return Response({"error": "Audit session not found."}, status=404)

        findings = session.findings.select_related("invoice").order_by("-last_detected_at")
        if severity := request.query_params.get("severity"):
            findings = findings.filter(severity=severity)
        if status_value := request.query_params.get("status"):
            findings = findings.filter(status=status_value)
        return Response({"results": AuditFindingSerializer(findings[:100], many=True).data, "count": findings.count()})


class AuditDashboardOverviewView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication, SessionAuthentication]

    @extend_schema(tags=["Audit"], summary="Dashboard overview of recent audit sessions and findings")
    def get(self, request):
        sessions = AuditSession.objects.filter(organization=request.user.organization).order_by("-created_at")[:5]
        recent_sessions = []
        latest_summary = None
        for index, session in enumerate(sessions):
            serialized = AuditSessionSerializer(session).data
            serialized["open_findings"] = session.findings.filter(status=AuditFinding.Status.OPEN).count()
            serialized["critical_findings"] = session.findings.filter(
                status=AuditFinding.Status.OPEN,
                severity=AuditFinding.Severity.CRITICAL,
            ).count()
            recent_sessions.append(serialized)
            if index == 0:
                latest_summary = AuditSessionSummaryService.generate_summary(
                    session,
                    language=request.query_params.get("lang", "ar"),
                )

        open_findings = AuditFinding.objects.filter(
            organization=request.user.organization,
            status=AuditFinding.Status.OPEN,
        ).select_related("invoice", "audit_session").order_by("-last_detected_at")

        finding_totals = open_findings.aggregate(
            critical=Count("id", filter=Q(severity=AuditFinding.Severity.CRITICAL)),
            high=Count("id", filter=Q(severity=AuditFinding.Severity.HIGH)),
            medium=Count("id", filter=Q(severity=AuditFinding.Severity.MEDIUM)),
            low=Count("id", filter=Q(severity=AuditFinding.Severity.LOW)),
        )
        rule_groups = _build_rule_group_summary(
            InvoiceValidationResult.objects.filter(invoice__organization=request.user.organization)
        )
        return Response(
            {
                "recent_sessions": recent_sessions,
                "latest_summary": latest_summary,
                "finding_totals": finding_totals,
                "recent_findings": AuditFindingSerializer(open_findings[:6], many=True).data,
                "rule_groups": rule_groups,
            }
        )
