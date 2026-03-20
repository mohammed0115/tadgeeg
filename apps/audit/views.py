"""Audit Case Views"""

from django.utils import timezone
from django.utils.translation import gettext as _
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
from .models import AuditCase, AuditFinding, AuditSession, CaseComment, CustomRuleDefinition
from .serializers import (
    AuditCaseSerializer,
    AuditFindingSerializer,
    AuditSessionSerializer,
    CaseCommentSerializer,
    CustomRuleDefinitionSerializer,
)
from .services import AuditSessionSummaryService


RULE_GROUP_META = {
    "INV": {"label": _("Invoice Header"), "color": "#2563eb"},
    "DUP": {"label": _("Duplicates"), "color": "#f59e0b"},
    "VAT": {"label": _("VAT"), "color": "#7c3aed"},
    "ANO": {"label": _("Anomalies"), "color": "#ef4444"},
    "CTL": {"label": _("Controls"), "color": "#06b6d4"},
    "DOC": {"label": _("Document"), "color": "#16a34a"},
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
            return Response({"error": _("Case not found.")}, status=404)

        new_status = request.data.get("status")
        if new_status not in AuditCase.CaseStatus.values:
            return Response({"error": _("Invalid status. Choose from: %(statuses)s") % {"statuses": AuditCase.CaseStatus.values}}, status=400)

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
            return Response({"error": _("Case not found.")}, status=404)
        comments = case.comments.select_related("author").all()
        return Response(CaseCommentSerializer(comments, many=True).data)

    @extend_schema(tags=["Audit"], summary="Add a comment to a case")
    def post(self, request, pk):
        try:
            case = AuditCase.objects.get(pk=pk, organization=request.user.organization)
        except AuditCase.DoesNotExist:
            return Response({"error": _("Case not found.")}, status=404)

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
            return Response({"error": _("Case not found.")}, status=404)

        user_id = request.data.get("user_id")
        if not user_id:
            return Response({"error": _("user_id is required.")}, status=400)

        try:
            assignee = User.objects.get(
                pk=user_id,
                organization=request.user.organization,
                is_active=True,
            )
        except User.DoesNotExist:
            return Response({"error": _("Assignee not found.")}, status=404)

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
            return Response({"error": _("Audit session not found.")}, status=404)

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
            return Response({"error": _("Audit session not found.")}, status=404)

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
            return Response({"error": _("Audit session not found.")}, status=404)

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


class BigFourComplianceView(APIView):
    """
    FR-2 gap fix: Big Four standards compliance breakdown.
    Maps existing rule groups to KPMG / Deloitte / PwC / EY methodologies
    and returns per-firm pass rates.
    """
    permission_classes = [IsAuthenticated]

    # Design decision: map rule group codes → Big Four firm
    BIG_FOUR_MAPPING = {
        "KPMG": {
            "label": "KPMG — Invoice Completeness & Accuracy",
            "description": "KPMG audit procedures validate that all mandatory invoice fields are present and accurate.",
            "groups": ["INV"],
            "standard": "ISA 500 — Audit Evidence",
        },
        "Deloitte": {
            "label": "Deloitte — Risk Assessment & Anomaly Detection",
            "description": "Deloitte risk assessment methodology focuses on amount anomalies and unusual transaction patterns.",
            "groups": ["ANO", "DUP"],
            "standard": "ISA 315 — Identifying and Assessing Risks",
        },
        "PwC": {
            "label": "PwC — Internal Control Testing",
            "description": "PwC control testing frameworks verify that financial controls are operating effectively.",
            "groups": ["CTL"],
            "standard": "ISA 330 — Auditor's Responses to Assessed Risks",
        },
        "EY": {
            "label": "EY — Compliance Verification",
            "description": "EY compliance procedures verify adherence to ZATCA e-invoicing and documentation standards.",
            "groups": ["VAT", "DOC"],
            "standard": "ISA 250 — Consideration of Laws and Regulations",
        },
    }

    @extend_schema(tags=["Audit"], summary="Big Four standards compliance breakdown (FR-2)")
    def get(self, request):
        from apps.invoices.models import InvoiceValidationResult
        org = request.user.organization
        if not org:
            return Response({"error": "No organization."}, status=400)

        validation_qs = InvoiceValidationResult.objects.filter(invoice__organization=org)
        rule_groups = _build_rule_group_summary(validation_qs)

        # Index rule groups by code for quick lookup
        group_by_code = {g["code"]: g for g in rule_groups}

        results = []
        for firm, meta in self.BIG_FOUR_MAPPING.items():
            firm_passed = firm_failed = firm_total = 0
            group_details = []
            for code in meta["groups"]:
                g = group_by_code.get(code, {"passed": 0, "failed": 0, "total": 0, "pct": 0.0})
                firm_passed += g["passed"]
                firm_failed += g["failed"]
                firm_total += g["total"]
                group_details.append({
                    "code": code,
                    "passed": g["passed"],
                    "failed": g["failed"],
                    "total": g["total"],
                    "pass_rate": g["pct"],
                })
            firm_pass_rate = round((firm_passed / firm_total) * 100, 1) if firm_total else 0.0
            status = "compliant" if firm_pass_rate >= 90 else "at_risk" if firm_pass_rate >= 70 else "non_compliant"
            results.append({
                "firm": firm,
                "label": meta["label"],
                "description": meta["description"],
                "standard": meta["standard"],
                "pass_rate": firm_pass_rate,
                "passed": firm_passed,
                "failed": firm_failed,
                "total": firm_total,
                "status": status,
                "groups": group_details,
            })

        overall_passed = sum(r["passed"] for r in results)
        overall_total = sum(r["total"] for r in results)
        overall_rate = round((overall_passed / overall_total) * 100, 1) if overall_total else 0.0

        return Response({
            "overall_pass_rate": overall_rate,
            "overall_status": "compliant" if overall_rate >= 90 else "at_risk" if overall_rate >= 70 else "non_compliant",
            "firms": results,
        })


class BulkCaseActionView(APIView):
    """
    Bulk remediation endpoint (FR-4 gap fix).
    POST /api/v1/audit/cases/bulk/
    Body: {"ids": ["uuid", ...], "action": "resolve|close|archive|assign", "note": "", "assigned_to": "uuid"}
    """
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    @extend_schema(
        tags=["Audit"],
        summary="Bulk update audit case status",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "ids": {"type": "array", "items": {"type": "string"}},
                    "action": {"type": "string", "enum": ["resolve", "close", "archive", "assign"]},
                    "note": {"type": "string"},
                    "assigned_to": {"type": "string"},
                },
                "required": ["ids", "action"],
            }
        },
    )
    def post(self, request):
        ids = request.data.get("ids", [])
        action = request.data.get("action", "")
        note = request.data.get("note", "")
        assigned_to_id = request.data.get("assigned_to")

        if not ids or not action:
            return Response({"error": "ids and action are required."}, status=400)

        allowed_actions = {"resolve", "close", "archive", "assign"}
        if action not in allowed_actions:
            return Response({"error": f"Invalid action. Choose from: {', '.join(allowed_actions)}"}, status=400)

        qs = AuditCase.objects.filter(
            id__in=ids, organization=request.user.organization
        )
        count = qs.count()
        if count == 0:
            return Response({"error": "No matching cases found."}, status=404)

        now = timezone.now()
        if action == "resolve":
            qs.update(
                status=AuditCase.Status.RESOLVED,
                resolved_by=request.user,
                resolved_at=now,
                resolution_notes=note or "Bulk resolved",
            )
        elif action == "close":
            qs.update(status=AuditCase.Status.CLOSED)
        elif action == "archive":
            qs.update(status=AuditCase.Status.CLOSED)
        elif action == "assign":
            if not assigned_to_id:
                return Response({"error": "assigned_to is required for assign action."}, status=400)
            try:
                assignee = User.objects.get(id=assigned_to_id, organization=request.user.organization)
            except User.DoesNotExist:
                return Response({"error": "Assignee not found in organization."}, status=404)
            qs.update(assigned_to=assignee, status=AuditCase.Status.IN_PROGRESS)

        return Response({"updated": count, "action": action})


# ── FR-9: Custom Rule Definitions CRUD ───────────────────────────────────────

class CustomRuleListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/v1/audit/rules/        — list all active custom rules for the org
    POST /api/v1/audit/rules/        — create a new custom rule
    """
    serializer_class = CustomRuleDefinitionSerializer
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Audit"], summary="List custom audit rules (FR-9)")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(tags=["Audit"], summary="Create a custom audit rule (FR-9)")
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)

    def get_queryset(self):
        qs = CustomRuleDefinition.objects.filter(organization=self.request.user.organization)
        if self.request.query_params.get("active_only", "true").lower() != "false":
            qs = qs.filter(is_active=True)
        if standard := self.request.query_params.get("standard"):
            qs = qs.filter(standard=standard)
        return qs

    def perform_create(self, serializer):
        serializer.save(
            organization=self.request.user.organization,
            created_by=self.request.user,
        )


class CustomRuleDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET    /api/v1/audit/rules/<uuid>/  — retrieve a rule
    PATCH  /api/v1/audit/rules/<uuid>/  — update a rule (auto-increments version)
    DELETE /api/v1/audit/rules/<uuid>/  — delete a rule
    """
    serializer_class = CustomRuleDefinitionSerializer
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    @extend_schema(tags=["Audit"], summary="Get / update / delete a custom rule (FR-9)")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        return CustomRuleDefinition.objects.filter(organization=self.request.user.organization)


class CustomRuleTestView(APIView):
    """
    POST /api/v1/audit/rules/<uuid>/test/
    Test a custom rule against a sample invoice payload.
    Body: {"invoice": {...invoice fields...}}
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Audit"],
        summary="Test a custom rule against a sample invoice (FR-9)",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "invoice": {"type": "object", "description": "Invoice data to test against"},
                },
                "required": ["invoice"],
            }
        },
    )
    def post(self, request, pk):
        try:
            rule = CustomRuleDefinition.objects.get(pk=pk, organization=request.user.organization)
        except CustomRuleDefinition.DoesNotExist:
            return Response({"error": "Rule not found."}, status=404)

        invoice = request.data.get("invoice", {})
        if not isinstance(invoice, dict):
            return Response({"error": "invoice must be a JSON object."}, status=400)

        result = rule.evaluate(invoice)
        return Response({
            "rule": {"id": str(rule.id), "name": rule.name, "severity": rule.severity},
            "invoice_tested": invoice,
            "result": result,
        })
