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
    RiskScoreSummarySerializer, TriggerAuditSerializer
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
        from apps.rule_engine.executors.audit_pipeline import AuditPipeline
        pipeline = AuditPipeline()
        audit_run = pipeline.run(
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
