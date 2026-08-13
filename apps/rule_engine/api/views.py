"""
Rule Engine API Views.
All views require authentication and enforce organization-level isolation.
"""
import logging
from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.shortcuts import get_object_or_404

from apps.rule_engine.models import (
    RuleDefinition, RuleAssignment, AuditRun, AuditResult, RiskScoreSummary
)
from apps.rule_engine.serializers.audit_run_serializers import (
    RuleDefinitionSerializer, AuditRunSummarySerializer,
    RiskScoreSummarySerializer, TriggerAuditSerializer,
    DocumentCanonicalDataSerializer,
)

logger = logging.getLogger("rule_engine")


def get_organization(request):
    """Get organization from request user."""
    return getattr(request.user, "organization", None)


class RuleLibraryView(generics.ListAPIView):
    """GET /api/rule-engine/rules/ — List all active system rules."""
    permission_classes = [IsAuthenticated]
    serializer_class = RuleDefinitionSerializer

    def get_queryset(self):
        qs = RuleDefinition.objects.filter(is_active=True).prefetch_related("translations")
        category = self.request.query_params.get("category")
        rule_type = self.request.query_params.get("rule_type")
        scope = self.request.query_params.get("scope")
        if category:
            qs = qs.filter(category=category)
        if rule_type:
            qs = qs.filter(rule_type=rule_type)
        if scope:
            qs = qs.filter(scope=scope)
        return qs.order_by("rule_code")


class AuditRunListView(generics.ListAPIView):
    """GET /api/rule-engine/runs/?document_id=<uuid> — List audit runs for a document."""
    permission_classes = [IsAuthenticated]
    serializer_class = AuditRunSummarySerializer

    def get_queryset(self):
        org = get_organization(self.request)
        if not org:
            return AuditRun.objects.none()
        qs = AuditRun.objects.filter(organization=org).order_by("-started_at")
        document_id = self.request.query_params.get("document_id")
        document_type = self.request.query_params.get("document_type")
        if document_id:
            qs = qs.filter(document_id=document_id)
        if document_type:
            qs = qs.filter(document_type=document_type)
        return qs.prefetch_related(
            "results",
            "results__evidence_items",
            "results__rule_assignment__rule__translations",
            "results__manual_review",
        )[:50]


class AuditRunDetailView(generics.RetrieveAPIView):
    """GET /api/rule-engine/runs/<pk>/ — Full audit run details."""
    permission_classes = [IsAuthenticated]
    serializer_class = AuditRunSummarySerializer

    def get_queryset(self):
        org = get_organization(self.request)
        if not org:
            return AuditRun.objects.none()
        return AuditRun.objects.filter(organization=org).prefetch_related(
            "results",
            "results__evidence_items",
            "results__rule_assignment__rule__translations",
            "results__manual_review",
        )


class RiskSummaryView(generics.RetrieveAPIView):
    """GET /api/rule-engine/risk/<document_id>/ — Risk summary for a document."""
    permission_classes = [IsAuthenticated]
    serializer_class = RiskScoreSummarySerializer

    def get_object(self):
        org = get_organization(self.request)
        document_id = self.kwargs["document_id"]
        return get_object_or_404(RiskScoreSummary, document_id=document_id, organization=org)


class HighRiskDocumentsView(generics.ListAPIView):
    """GET /api/rule-engine/high-risk/ — Highest risk documents for the organization."""
    permission_classes = [IsAuthenticated]
    serializer_class = RiskScoreSummarySerializer

    def get_queryset(self):
        org = get_organization(self.request)
        if not org:
            return RiskScoreSummary.objects.none()
        limit = int(self.request.query_params.get("limit", 10))
        risk_level = self.request.query_params.get("risk_level", "high")
        return RiskScoreSummary.objects.filter(
            organization=org,
            risk_level__in=["critical", "high"] if risk_level == "high" else [risk_level],
        ).order_by("-risk_score")[:limit]


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def trigger_audit(request):
    """POST /api/rule-engine/trigger/ — Manually trigger an audit run."""
    serializer = TriggerAuditSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    org = get_organization(request)
    if not org:
        return Response({"error": "No organization found for user."}, status=status.HTTP_403_FORBIDDEN)

    data = serializer.validated_data
    document_id = str(data["document_id"])
    document_type = data["document_type"]
    triggered_by = data.get("triggered_by", "manual")

    try:
        # One production boundary for upload, manual re-audit and retry.  It
        # owns V1/V2 selection and, when enabled, the billing reserve/consume
        # cycle; importing AuditPipeline here bypassed both.
        from apps.rule_engine.pipeline.v2.compat import run_audit_compat
        audit_run = run_audit_compat(
            document_id=document_id,
            document_type=document_type,
            organization_id=str(org.id),
            triggered_by=triggered_by,
        )
        return Response(
            AuditRunSummarySerializer(audit_run).data,
            status=status.HTTP_201_CREATED,
        )
    except Exception as e:
        logger.exception(f"Failed to trigger audit for {document_id}: {e}")
        return Response(
            {"error": f"Audit pipeline failed: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def canonical_data_view(request, document_id):
    """
    GET /api/rule-engine/canonical/<document_id>/
    Returns the canonical data snapshot for any document by its typed_object_id (UUID).
    Organization isolation is enforced via RiskScoreSummary lookup.
    """
    org = get_organization(request)
    if not org:
        return Response({"error": "No organization found for user."}, status=status.HTTP_403_FORBIDDEN)

    try:
        from apps.documents.canonical_models import DocumentCanonicalData

        # Verify the document belongs to this org by checking RiskScoreSummary
        if not RiskScoreSummary.objects.filter(
            organization=org, document_id=str(document_id)
        ).exists():
            return Response(
                {"error": "Document not found or not accessible."},
                status=status.HTTP_404_NOT_FOUND,
            )

        rec = DocumentCanonicalData.objects.filter(
            typed_object_id=str(document_id)
        ).first()

        if rec is None:
            return Response(
                {"error": "Canonical data has not been generated for this document yet."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = DocumentCanonicalDataSerializer({
            "document_type":    rec.document_type,
            "typed_model_name": rec.typed_model_name,
            "typed_object_id":  rec.typed_object_id,
            "canonical_data":   rec.canonical_data,
            "raw_ai_output":    rec.raw_ai_output,
            "version":          rec.version,
            "created_at":       rec.created_at,
            "updated_at":       rec.updated_at,
        })
        return Response(serializer.data)

    except Exception as e:
        logger.exception(f"canonical_data_view error for {document_id}: {e}")
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def canonical_cross_query(request):
    """
    GET /api/rule-engine/canonical/?field=<field_code>&value=<value>&doc_type=<type>
    Find all documents in the org where canonical_data[field] == value.
    Useful for cross-document reconciliation queries.
    """
    org = get_organization(request)
    if not org:
        return Response({"error": "No organization."}, status=status.HTTP_403_FORBIDDEN)

    field_code = request.query_params.get("field")
    value      = request.query_params.get("value")
    doc_type   = request.query_params.get("doc_type", "")

    if not field_code or value is None:
        return Response(
            {"error": "Query params 'field' and 'value' are required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        from apps.documents.canonical_models import DocumentCanonicalData

        # Get document_ids that belong to this org via RiskScoreSummary
        org_doc_ids = list(
            RiskScoreSummary.objects.filter(organization=org)
            .values_list("document_id", flat=True)
        )

        qs = DocumentCanonicalData.objects.filter(
            typed_object_id__in=org_doc_ids
        )
        if doc_type:
            qs = qs.filter(document_type=doc_type)

        # JSONField filter: canonical_data[field] == value
        matches = [
            {
                "typed_object_id": str(rec.typed_object_id),
                "document_type":   rec.document_type,
                "field_value":     rec.canonical_data.get(field_code),
                "version":         rec.version,
            }
            for rec in qs
            if str(rec.canonical_data.get(field_code, "")) == str(value)
        ]

        return Response({"field": field_code, "value": value, "matches": matches})

    except Exception as e:
        logger.exception(f"canonical_cross_query error: {e}")
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def top_failed_rules(request):
    """GET /api/rule-engine/analytics/top-failures/ — Top failed rules across org."""
    org = get_organization(request)
    if not org:
        return Response([])

    days = int(request.query_params.get("days", 7))
    from django.utils import timezone
    from datetime import timedelta
    from django.db.models import Count

    since = timezone.now() - timedelta(days=days)
    top = (
        AuditResult.objects.filter(
            audit_run__organization=org,
            audit_run__started_at__gte=since,
            status="fail",
        )
        .values("rule_code", "applied_severity")
        .annotate(fail_count=Count("id"))
        .order_by("-fail_count")[:10]
    )
    return Response(list(top))
