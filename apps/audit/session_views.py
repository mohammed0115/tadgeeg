"""AuditSession API Views — Phase 3"""

import logging
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import serializers as drf_serializers
from drf_spectacular.utils import extend_schema, OpenApiParameter

from .models import AuditSession, AuditFinding
from .session_service import AuditSessionService, InvalidStateTransition

logger = logging.getLogger("finai")


# ── Serializers ───────────────────────────────────────────────────────────────

class AuditSessionSerializer(drf_serializers.ModelSerializer):
    progress_pct  = drf_serializers.ReadOnlyField()
    is_terminal   = drf_serializers.ReadOnlyField()
    created_by_name = drf_serializers.SerializerMethodField()

    class Meta:
        model = AuditSession
        fields = [
            "id", "session_name", "state", "progress_pct", "is_terminal",
            "total_count", "processed_count", "success_count", "failed_count",
            "review_required_count", "duplicate_count", "compliance_issues", "high_risk_count",
            "overall_risk_score", "overall_risk_level",
            "executive_summary", "error_log",
            "started_at", "completed_at", "created_at", "updated_at",
            "created_by_name",
        ]
        read_only_fields = fields

    def get_created_by_name(self, obj):
        return obj.created_by.full_name if obj.created_by else None


class AuditFindingSerializer(drf_serializers.ModelSerializer):
    class Meta:
        model = AuditFinding
        fields = [
            "id", "session", "invoice", "document",
            "rule_code", "category", "severity", "status",
            "title", "description", "evidence", "remediation",
            "reviewed_by", "reviewed_at", "created_at",
        ]
        read_only_fields = ["id", "created_at"]


# ── Views ─────────────────────────────────────────────────────────────────────

class AuditSessionListView(APIView):
    """List audit sessions for the current organisation."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Audit Sessions"],
        summary="List audit sessions",
        parameters=[
            OpenApiParameter("state", description="Filter by state"),
            OpenApiParameter("limit", description="Max results (default 20)"),
        ],
    )
    def get(self, request):
        org = request.user.organization
        qs = (
            AuditSession.objects
            .filter(organization=org)
            .select_related("created_by")   # avoid N+1 in get_created_by_name
            .order_by("-created_at")
        )
        if state := request.query_params.get("state"):
            qs = qs.filter(state=state)
        limit = min(int(request.query_params.get("limit", 20)), 100)
        sessions = list(qs[:limit])
        data = AuditSessionSerializer(sessions, many=True).data
        return Response({"count": qs.count(), "results": data})


class AuditSessionDetailView(APIView):
    """Retrieve a single audit session with its findings."""
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Audit Sessions"], summary="Get session detail")
    def get(self, request, pk):
        try:
            session = AuditSession.objects.get(pk=pk, organization=request.user.organization)
        except AuditSession.DoesNotExist:
            return Response({"error": "Not found."}, status=404)

        findings = AuditFinding.objects.filter(session=session).order_by("-severity", "-created_at")[:50]
        return Response({
            "session": AuditSessionSerializer(session).data,
            "findings": AuditFindingSerializer(findings, many=True).data,
        })


class AuditSessionProgressView(APIView):
    """Lightweight polling endpoint for session progress."""
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Audit Sessions"], summary="Poll session progress (lightweight)")
    def get(self, request, pk):
        try:
            session = AuditSession.objects.get(pk=pk, organization=request.user.organization)
        except AuditSession.DoesNotExist:
            return Response({"error": "Not found."}, status=404)

        return Response({
            "id":               str(session.id),
            "state":            session.state,
            "progress_pct":     session.progress_pct,
            "total_count":      session.total_count,
            "processed_count":  session.processed_count,
            "success_count":    session.success_count,
            "failed_count":     session.failed_count,
            "review_required":  session.review_required_count,
            "is_terminal":      session.is_terminal,
        })


class AuditSessionRetryView(APIView):
    """Retry failed documents in a session."""
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Audit Sessions"], summary="Retry failed documents in session")
    def post(self, request, pk):
        try:
            session = AuditSession.objects.get(pk=pk, organization=request.user.organization)
        except AuditSession.DoesNotExist:
            return Response({"error": "Not found."}, status=404)

        if session.failed_count == 0:
            return Response({"detail": "No failed documents to retry."})

        from .tasks import retry_session_failed_docs
        retry_session_failed_docs.delay(session_id=str(session.id))
        return Response({"detail": "Retry dispatched.", "session_id": str(session.id)})


class AuditSessionSummaryView(APIView):
    """Trigger or retrieve the AI executive summary for a session."""
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Audit Sessions"], summary="Get or regenerate session AI summary")
    def get(self, request, pk):
        try:
            session = AuditSession.objects.get(pk=pk, organization=request.user.organization)
        except AuditSession.DoesNotExist:
            return Response({"error": "Not found."}, status=404)
        return Response({"session_id": str(session.id), "executive_summary": session.executive_summary})

    def post(self, request, pk):
        try:
            session = AuditSession.objects.get(pk=pk, organization=request.user.organization)
        except AuditSession.DoesNotExist:
            return Response({"error": "Not found."}, status=404)

        language = request.data.get("language", "ar")
        from .tasks import generate_session_summary
        generate_session_summary.delay(session_id=str(session.id), language=language)
        return Response({"detail": "Summary generation queued.", "session_id": str(session.id)})


class AuditSessionResultsView(APIView):
    """
    Paginated endpoint returning the full analysis results for every Document
    in an AuditSession.

    Design:
      - Cursor-based pagination: clients pass `cursor` (last seen document PK)
        instead of offset, so pages remain stable as new documents are added.
      - Single query with select_related / prefetch_related — zero N+1.
      - Returns both document metadata AND its DocumentAnalysisResult in one
        response so the frontend never needs a second request.
      - Supports filtering by risk_level, processing_status, and requires_review.

    GET /audit/sessions/<pk>/results/?page_size=20&cursor=<uuid>&risk_level=high
    """
    permission_classes = [IsAuthenticated]

    _DEFAULT_PAGE_SIZE = 20
    _MAX_PAGE_SIZE     = 100

    @extend_schema(
        tags=["Audit Sessions"],
        summary="Paginated document results for a session",
        parameters=[
            OpenApiParameter("page_size",     description="Items per page (max 100, default 20)"),
            OpenApiParameter("cursor",        description="UUID of the last document on the previous page"),
            OpenApiParameter("risk_level",    description="Filter: low|medium|high|critical"),
            OpenApiParameter("status",        description="Filter: pending|processing|completed|failed|needs_review"),
            OpenApiParameter("requires_review", description="Filter: true|false"),
            OpenApiParameter("ordering",      description="Order field: created_at|-created_at|risk_score|-risk_score"),
        ],
    )
    def get(self, request, pk):
        # ── 1. Load + authorise session ────────────────────────────────────────
        try:
            session = AuditSession.objects.get(pk=pk, organization=request.user.organization)
        except AuditSession.DoesNotExist:
            return Response({"error": "Not found."}, status=404)

        p = request.query_params

        # ── 2. Parse pagination params ─────────────────────────────────────────
        try:
            page_size = min(int(p.get("page_size", self._DEFAULT_PAGE_SIZE)), self._MAX_PAGE_SIZE)
        except (ValueError, TypeError):
            page_size = self._DEFAULT_PAGE_SIZE

        cursor      = p.get("cursor")           # UUID string or None
        risk_level  = p.get("risk_level")
        status_f    = p.get("status")
        req_review  = p.get("requires_review")
        ordering    = p.get("ordering", "-created_at")

        # Whitelist ordering fields to prevent arbitrary column injection
        allowed_orderings = {
            "created_at", "-created_at",
            "risk_score", "-risk_score",
        }
        if ordering not in allowed_orderings:
            ordering = "-created_at"

        # ── 3. Build query — single round-trip, no N+1 ────────────────────────
        # Documents linked to this session via AuditFinding
        from apps.documents.models import Document, DocumentAnalysisResult
        from apps.audit.models import AuditFinding

        doc_ids_in_session = (
            AuditFinding.objects
            .filter(session=session)
            .values_list("document_id", flat=True)
            .distinct()
        )

        qs = (
            DocumentAnalysisResult.objects
            .filter(document_id__in=doc_ids_in_session)
            .select_related("document", "document__uploaded_by")
            .order_by(ordering, "document_id")   # secondary sort for stable pages
        )

        # ── 4. Apply filters ───────────────────────────────────────────────────
        if risk_level:
            qs = qs.filter(risk_level=risk_level)
        if status_f:
            qs = qs.filter(document__processing_status=status_f)
        if req_review and req_review.lower() == "true":
            qs = qs.filter(requires_review=True)
        elif req_review and req_review.lower() == "false":
            qs = qs.filter(requires_review=False)

        # Total count before cursor (for the frontend progress bar)
        total_count = qs.count()

        # ── 5. Cursor-based pagination ─────────────────────────────────────────
        if cursor:
            # The cursor is the document_id of the last item on the prev page.
            # For descending created_at we want items "older" than the cursor;
            # for ascending we want items "newer".  We use the PK as tiebreaker.
            try:
                import uuid as _uuid
                cursor_uuid = _uuid.UUID(cursor)
                if ordering.startswith("-"):
                    # Descending: items after cursor have smaller PK (uuid sort)
                    qs = qs.filter(document_id__lt=cursor_uuid)
                else:
                    qs = qs.filter(document_id__gt=cursor_uuid)
            except (ValueError, AttributeError):
                pass  # Invalid cursor — ignore and return from start

        results = list(qs[:page_size + 1])   # Fetch one extra to determine has_more
        has_more       = len(results) > page_size
        page_results   = results[:page_size]
        next_cursor    = str(page_results[-1].document_id) if has_more and page_results else None

        # ── 6. Fetch findings counts in one query (avoid N+1) ─────────────────
        page_doc_ids     = [r.document_id for r in page_results]
        findings_by_doc  = {}

        if page_doc_ids:
            from django.db.models import Count
            findings_qs = (
                AuditFinding.objects
                .filter(
                    session=session,
                    document_id__in=page_doc_ids,
                )
                .values("document_id", "severity")
                .annotate(count=Count("id"))
            )
            for row in findings_qs:
                doc_id = str(row["document_id"])
                findings_by_doc.setdefault(doc_id, {})
                findings_by_doc[doc_id][row["severity"]] = row["count"]

        # ── 7. Fetch state history counts in one query ─────────────────────────
        state_history_by_doc: dict = {}
        try:
            from apps.documents.models import DocumentStateHistory
            history_qs = (
                DocumentStateHistory.objects
                .filter(document_id__in=page_doc_ids)
                .values("document_id", "to_state")
                .annotate(count=Count("id"))
            )
            for row in history_qs:
                doc_id = str(row["document_id"])
                state_history_by_doc.setdefault(doc_id, {})[row["to_state"]] = row["count"]
        except Exception:
            pass  # DocumentStateHistory table may not exist yet in dev

        # ── 8. Serialise ───────────────────────────────────────────────────────
        items = []
        for ar in page_results:
            doc    = ar.document
            doc_id = str(doc.pk)
            items.append({
                "document_id":       doc_id,
                "original_filename": doc.original_filename,
                "file_size":         doc.file_size,
                "mime_type":         doc.mime_type,
                "document_type":     doc.document_type,
                "processing_status": doc.processing_status,
                "uploaded_by":       doc.uploaded_by.email if doc.uploaded_by_id else None,
                "created_at":        doc.created_at.isoformat(),
                "analysis": {
                    "ai_document_type":          ar.ai_document_type,
                    "classification_confidence": ar.classification_confidence,
                    "vendor_name":               ar.vendor_name,
                    "document_number":           ar.document_number,
                    "doc_date":                  str(ar.doc_date) if ar.doc_date else None,
                    "currency":                  ar.currency,
                    "total_amount":              str(ar.total_amount) if ar.total_amount else None,
                    "tax_amount":                str(ar.tax_amount) if ar.tax_amount else None,
                    "risk_score":                ar.risk_score,
                    "risk_level":                ar.risk_level,
                    "fraud_score":               ar.fraud_score,
                    "duplicate_score":           ar.duplicate_score,
                    "compliance_score":          ar.compliance_score,
                    "is_duplicate":              ar.is_duplicate,
                    "requires_review":           ar.requires_review,
                    "escalate":                  ar.escalate,
                    "pipeline_version":          ar.pipeline_version,
                    "processing_time_ms":        ar.processing_time_ms,
                },
                "findings_summary":  findings_by_doc.get(doc_id, {}),
                "state_transitions": state_history_by_doc.get(doc_id, {}),
            })

        return Response({
            "session_id":  str(session.id),
            "total_count": total_count,
            "page_size":   page_size,
            "has_more":    has_more,
            "next_cursor": next_cursor,
            "results":     items,
        })


class AuditSessionRiskSummaryView(APIView):
    """
    Aggregated risk distribution for a session — used by dashboard charts.
    Returns counts grouped by risk_level and processing_status.
    Single DB query via aggregation — no N+1.

    GET /audit/sessions/<pk>/risk-summary/
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Audit Sessions"], summary="Risk distribution summary for a session")
    def get(self, request, pk):
        try:
            session = AuditSession.objects.get(pk=pk, organization=request.user.organization)
        except AuditSession.DoesNotExist:
            return Response({"error": "Not found."}, status=404)

        from django.db.models import Count, Avg, Max
        from apps.documents.models import DocumentAnalysisResult
        from apps.audit.models import AuditFinding

        # Documents in this session
        doc_ids = (
            AuditFinding.objects
            .filter(session=session)
            .values_list("document_id", flat=True)
            .distinct()
        )

        # Single aggregation query
        agg = (
            DocumentAnalysisResult.objects
            .filter(document_id__in=doc_ids)
            .aggregate(
                avg_risk_score=Avg("risk_score"),
                max_risk_score=Max("risk_score"),
                avg_fraud_score=Avg("fraud_score"),
                avg_compliance_score=Avg("compliance_score"),
                total_documents=Count("id"),
                total_duplicates=Count("id", filter=__import__("django.db.models", fromlist=["Q"]).Q(is_duplicate=True)),
                total_escalated=Count("id", filter=__import__("django.db.models", fromlist=["Q"]).Q(escalate=True)),
                total_review=Count("id", filter=__import__("django.db.models", fromlist=["Q"]).Q(requires_review=True)),
            )
        )

        # Risk level distribution — single query, then fan out into dict
        from django.db.models import Q
        risk_dist = {"low": 0, "medium": 0, "high": 0, "critical": 0}
        for row in (
            DocumentAnalysisResult.objects
            .filter(document_id__in=doc_ids)
            .values("risk_level")
            .annotate(count=Count("id"))
        ):
            if row["risk_level"] in risk_dist:
                risk_dist[row["risk_level"]] = row["count"]

        # Findings by severity
        findings_dist = {}
        for row in (
            AuditFinding.objects
            .filter(session=session)
            .values("severity")
            .annotate(count=Count("id"))
        ):
            findings_dist[row["severity"]] = row["count"]

        return Response({
            "session_id":           str(session.id),
            "session_state":        session.state,
            "overall_risk_score":   session.overall_risk_score,
            "overall_risk_level":   session.overall_risk_level,
            "aggregates": {
                "avg_risk_score":       round(agg["avg_risk_score"] or 0, 1),
                "max_risk_score":       agg["max_risk_score"] or 0,
                "avg_fraud_score":      round(agg["avg_fraud_score"] or 0, 3),
                "avg_compliance_score": round(agg["avg_compliance_score"] or 1, 3),
                "total_documents":      agg["total_documents"],
                "total_duplicates":     agg["total_duplicates"],
                "total_escalated":      agg["total_escalated"],
                "total_review":         agg["total_review"],
            },
            "risk_distribution":    risk_dist,
            "findings_by_severity": findings_dist,
        })


class AuditFindingListView(APIView):
    """List findings — optionally filtered by session or severity."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Audit Sessions"],
        summary="List audit findings",
        parameters=[
            OpenApiParameter("session", description="Filter by session UUID"),
            OpenApiParameter("severity", description="Filter by severity"),
            OpenApiParameter("status", description="Filter by status"),
            OpenApiParameter("category", description="Filter by category"),
        ],
    )
    def get(self, request):
        org = request.user.organization
        qs = AuditFinding.objects.filter(organization=org).select_related("session", "invoice", "document")

        p = request.query_params
        if v := p.get("session"):     qs = qs.filter(session_id=v)
        if v := p.get("severity"):    qs = qs.filter(severity=v)
        if v := p.get("status"):      qs = qs.filter(status=v)
        if v := p.get("category"):    qs = qs.filter(category=v)

        limit = min(int(p.get("limit", 50)), 200)
        data = AuditFindingSerializer(qs[:limit], many=True).data
        return Response({"count": qs.count(), "results": data})


class AuditFindingResolveView(APIView):
    """Mark a finding as reviewed or resolved."""
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Audit Sessions"], summary="Update finding status")
    def patch(self, request, pk):
        try:
            finding = AuditFinding.objects.get(pk=pk, organization=request.user.organization)
        except AuditFinding.DoesNotExist:
            return Response({"error": "Not found."}, status=404)

        new_status = request.data.get("status")
        if new_status not in AuditFinding.Status.values:
            return Response({"error": f"Invalid status. Choose from {AuditFinding.Status.values}"}, status=400)

        finding.status = new_status
        finding.reviewed_by = request.user
        finding.reviewed_at = timezone.now()
        finding.save(update_fields=["status", "reviewed_by", "reviewed_at", "updated_at"])
        return Response(AuditFindingSerializer(finding).data)
