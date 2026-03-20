"""
Documents Views — Upload, OCR, AI Processing, Full Pipeline Analysis

Endpoint overview:
  POST   /api/documents/upload/            — Upload a document → async full pipeline
  GET    /api/documents/                   — List documents for the organisation
  GET    /api/documents/{pk}/              — Document detail + analysis summary
  DELETE /api/documents/{pk}/              — Delete document
  POST   /api/documents/{pk}/process/      — (Re-)trigger legacy OCR+AI processing
  POST   /api/documents/{pk}/analyse/      — Trigger or return full pipeline analysis
  GET    /api/documents/{pk}/analysis/     — Get DocumentAnalysisResult
  PATCH  /api/documents/{pk}/validate/     — Human correction / validation of extracted data
"""

import os
import logging
import time

from django.conf import settings
from django.utils import timezone
from drf_spectacular.utils import extend_schema, OpenApiParameter
from rest_framework import generics, status
from rest_framework.parsers import FormParser, MultiPartParser, JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authentication.models import AuditLog
from apps.authentication.permissions import IsOwnOrganization, RequiresOrganization
from core.utils.audit import log_action

from .models import Document, ExtractedData, DocumentPageResult, DocumentAnalysisResult
from .serializers import (
    DocumentSerializer,
    DocumentListSerializer,
    DocumentUploadSerializer,
    ExtractedDataSerializer,
    DocumentAnalysisResultSerializer,
)

logger = logging.getLogger("finai")


# ── Upload ────────────────────────────────────────────────────────────────────

class DocumentUploadView(APIView):
    """
    Upload a financial document.

    Accepts: PDF, PNG, JPG, JPEG, TIFF, ZIP, XLSX, CSV, JSON (up to 50 MB; ZIP up to 200 MB).

    The document is saved immediately and queued for async processing via Celery.
    The full pipeline (OCR → AI extraction → fraud/dup detection → audit rules) runs
    in the background.  Poll GET /api/documents/{pk}/ to monitor processing_status.

    Processing status lifecycle:
      pending → processing → completed | needs_review | failed
    """
    parser_classes     = [MultiPartParser, FormParser]
    permission_classes = [IsAuthenticated, RequiresOrganization]

    @extend_schema(
        tags=["Documents"],
        summary="Upload a financial document (PDF/image/ZIP/Excel/CSV/JSON)",
        request=DocumentUploadSerializer,
        responses={201: DocumentSerializer},
    )
    def post(self, request):
        org = getattr(request.user, "organization", None)
        if not org:
            return Response({"error": "User has no organisation."}, status=400)

        serializer = DocumentUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        uploaded_file = serializer.validated_data["file"]
        doc_type      = serializer.validated_data.get("document_type", Document.DocumentType.OTHER)
        notes         = serializer.validated_data.get("notes", "")

        doc = Document.objects.create(
            organization      = org,
            uploaded_by       = request.user,
            file              = uploaded_file,
            original_filename = uploaded_file.name,
            file_size         = uploaded_file.size,
            mime_type         = uploaded_file.content_type or "",
            document_type     = doc_type,
            processing_status = Document.ProcessingStatus.PENDING,
            notes             = notes,
        )

        log_action(request, AuditLog.Action.DOCUMENT_UPLOAD, "document", str(doc.id))

        # Queue the full pipeline asynchronously
        from .tasks import process_document_task
        process_document_task.delay(str(doc.id))

        return Response(DocumentSerializer(doc).data, status=status.HTTP_201_CREATED)


# ── List / Detail / Delete ────────────────────────────────────────────────────

class DocumentListView(generics.ListAPIView):
    """List documents for the authenticated user's organisation."""
    serializer_class   = DocumentListSerializer
    permission_classes = [IsAuthenticated, RequiresOrganization]

    @extend_schema(
        tags=["Documents"],
        summary="List documents for the organisation",
        parameters=[
            OpenApiParameter("document_type",     description="Filter by document type"),
            OpenApiParameter("status",            description="Filter by processing_status"),
            OpenApiParameter("language",          description="Filter by language"),
            OpenApiParameter("risk_level",        description="Filter by analysis risk_level (requires analysis)"),
            OpenApiParameter("is_duplicate",      description="true|false — filter duplicates"),
            OpenApiParameter("search",            description="Search filename"),
            OpenApiParameter("date_from",         description="Created on or after (YYYY-MM-DD)"),
            OpenApiParameter("date_to",           description="Created on or before (YYYY-MM-DD)"),
        ],
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        qs = (
            Document.objects
            .filter(organization=self.request.user.organization)
            .select_related("uploaded_by")
            .prefetch_related("analysis_result")
            .order_by("-created_at")
        )
        p = self.request.query_params
        if v := p.get("document_type"): qs = qs.filter(document_type=v)
        if v := p.get("status"):        qs = qs.filter(processing_status=v)
        if v := p.get("language"):      qs = qs.filter(language=v)
        if v := p.get("search"):        qs = qs.filter(original_filename__icontains=v)
        if v := p.get("date_from"):     qs = qs.filter(created_at__date__gte=v)
        if v := p.get("date_to"):       qs = qs.filter(created_at__date__lte=v)
        # Filter by analysis risk level (requires JOIN)
        if v := p.get("risk_level"):
            qs = qs.filter(analysis_result__risk_level=v)
        if v := p.get("is_duplicate"):
            qs = qs.filter(analysis_result__is_duplicate=(v.lower() == "true"))
        return qs


class DocumentDetailView(generics.RetrieveDestroyAPIView):
    """Full document detail including extraction summary and analysis."""
    serializer_class   = DocumentSerializer
    permission_classes = [IsAuthenticated, RequiresOrganization, IsOwnOrganization]

    @extend_schema(
        tags=["Documents"],
        summary="Get document detail with extracted data and analysis summary",
    )
    def get(self, request, *args, **kwargs):
        doc  = self.get_object()
        data = DocumentSerializer(doc).data

        # Extracted data
        try:
            data["extracted"] = ExtractedDataSerializer(doc.extracted_data).data
        except ExtractedData.DoesNotExist:
            data["extracted"] = None

        # Page results
        page_results = doc.page_results.all()
        data["page_count"] = page_results.count() or doc.page_count
        data["pages"] = [
            {"page": pr.page_number, "confidence": pr.confidence}
            for pr in page_results[:5]
        ]

        return Response(data)

    def get_queryset(self):
        return Document.objects.filter(
            organization=self.request.user.organization
        ).select_related("uploaded_by").prefetch_related("analysis_result")


# ── Legacy OCR Process Endpoint ───────────────────────────────────────────────

class DocumentProcessView(APIView):
    """
    (Re-)trigger OCR + legacy AI processing for a document.

    For most use cases, prefer POST /api/documents/{pk}/analyse/ which runs
    the full v2.0 pipeline (OCR → FinancialAIEngine → AuditEngine).
    """
    permission_classes = [IsAuthenticated, RequiresOrganization]

    @extend_schema(
        tags=["Documents"],
        summary="Re-trigger OCR + AI processing (legacy)",
        request={"type": "object", "properties": {
            "use_openai":      {"type": "boolean", "default": True},
            "force_reprocess": {"type": "boolean", "default": False},
        }},
    )
    def post(self, request, pk):
        try:
            doc = Document.objects.get(pk=pk, organization=request.user.organization)
        except Document.DoesNotExist:
            return Response({"error": "Document not found."}, status=404)

        if doc.processing_status == Document.ProcessingStatus.PROCESSING:
            return Response({"error": "Document is already being processed."}, status=409)

        # Queue full pipeline
        from .tasks import reprocess_document_task
        reprocess_document_task.delay(str(doc.id))

        return Response({
            "message": "Reprocessing queued.",
            "document_id": str(doc.id),
            "status": "processing",
        })


# ── Full Pipeline Analysis ────────────────────────────────────────────────────

class DocumentAnalyseView(APIView):
    """
    Trigger or return the full Financial AI + Audit pipeline for a document.

    POST — Enqueue (or synchronously run for small files < 1 MB) the full pipeline.
           Returns task info immediately; result is accessible via GET.

    Stages run:
      1. DocumentEngine.ingest()      — MIME detection, parsing, OCR
      2. FinancialAIEngine.analyse()  — classification, extraction, fraud/dup/risk/compliance
      3. AuditEngine.evaluate()       — modular rule evaluation (R001–R006)
    """
    permission_classes = [IsAuthenticated, RequiresOrganization]

    @extend_schema(
        tags=["Documents"],
        summary="Trigger full Financial AI + Audit pipeline",
        request={"type": "object", "properties": {
            "sync": {"type": "boolean", "default": False,
                     "description": "Run synchronously (blocks; suitable for files < 1 MB)"},
        }},
    )
    def post(self, request, pk):
        try:
            doc = Document.objects.get(pk=pk, organization=request.user.organization)
        except Document.DoesNotExist:
            return Response({"error": "Document not found."}, status=404)

        if doc.processing_status == Document.ProcessingStatus.PROCESSING:
            return Response(
                {"message": "Already processing.", "document_id": str(doc.id)},
                status=202,
            )

        run_sync = request.data.get("sync", False)

        if run_sync and doc.file_size and doc.file_size < 1 * 1024 * 1024:
            # Synchronous path for small files — useful for testing
            from core.services.pipeline import run_full_pipeline
            pipeline_result = run_full_pipeline(str(doc.id))

            try:
                analysis = doc.analysis_result
                return Response({
                    "message": "Analysis complete.",
                    "document_id": str(doc.id),
                    "analysis": DocumentAnalysisResultSerializer(analysis).data,
                    "processing_time_ms": pipeline_result.get("processing_time_ms"),
                })
            except DocumentAnalysisResult.DoesNotExist:
                return Response({
                    "message": "Pipeline ran but no analysis result was saved.",
                    "document_id": str(doc.id),
                    "errors": pipeline_result.get("errors", []),
                }, status=500)
        else:
            # Async path
            from .tasks import process_document_task
            process_document_task.delay(str(doc.id))
            return Response(
                {
                    "message": "Analysis queued. Poll GET /api/documents/{pk}/analysis/ for results.",
                    "document_id": str(doc.id),
                    "status": "queued",
                },
                status=202,
            )


class DocumentAnalysisResultView(APIView):
    """
    Retrieve the DocumentAnalysisResult for a processed document.

    Returns the full Financial AI + Audit output:
      - AI classification (document type, confidence)
      - Extracted fields (vendor, amount, date, currency, …)
      - Risk score + level (low / medium / high / critical)
      - Fraud score + patterns
      - Duplicate score + reasons
      - Compliance score + issues
      - Audit rule results (R001–R006)
    """
    permission_classes = [IsAuthenticated, RequiresOrganization]

    @extend_schema(
        tags=["Documents"],
        summary="Get full Financial AI + Audit analysis result",
        responses={200: DocumentAnalysisResultSerializer},
    )
    def get(self, request, pk):
        try:
            doc = Document.objects.get(pk=pk, organization=request.user.organization)
        except Document.DoesNotExist:
            return Response({"error": "Document not found."}, status=404)

        try:
            analysis = doc.analysis_result
        except DocumentAnalysisResult.DoesNotExist:
            status_msg = doc.get_processing_status_display()
            if doc.processing_status == Document.ProcessingStatus.PROCESSING:
                return Response(
                    {"message": f"Document is still processing ({status_msg}). Retry shortly."},
                    status=202,
                )
            elif doc.processing_status == Document.ProcessingStatus.PENDING:
                return Response(
                    {"message": "Document has not been processed yet. POST /api/documents/{pk}/analyse/ to start."},
                    status=404,
                )
            return Response(
                {"message": f"No analysis available. Status: {status_msg}. Errors: {doc.processing_error}"},
                status=404,
            )

        return Response(DocumentAnalysisResultSerializer(analysis).data)


# ── Validation / Human Correction ────────────────────────────────────────────

class DocumentValidateView(APIView):
    """
    Apply human corrections to the extracted data of a document.

    PATCH body:
      {
        "corrections":        {"vendor_name": "Corrected Name", "total_amount": 1500.00},
        "validation_status":  "validated" | "rejected"
      }
    """
    permission_classes = [IsAuthenticated, RequiresOrganization]

    @extend_schema(
        tags=["Documents"],
        summary="Apply human corrections to extracted document data",
        request={"type": "object", "properties": {
            "corrections":       {"type": "object"},
            "validation_status": {"type": "string", "enum": ["validated", "rejected"]},
        }},
    )
    def patch(self, request, pk):
        try:
            doc      = Document.objects.get(pk=pk, organization=request.user.organization)
            extracted = doc.extracted_data
        except Document.DoesNotExist:
            return Response({"error": "Document not found."}, status=404)
        except ExtractedData.DoesNotExist:
            return Response({"error": "No extracted data found. Process the document first."}, status=404)

        corrections  = request.data.get("corrections", {})
        val_status   = request.data.get(
            "validation_status", ExtractedData.ValidationStatus.VALIDATED
        )

        if val_status not in ExtractedData.ValidationStatus.values:
            return Response(
                {"error": f"Invalid validation_status. Must be one of: {ExtractedData.ValidationStatus.values}"},
                status=400,
            )

        if corrections:
            extracted.structured_data.update(corrections)
            extracted.corrections = {**extracted.corrections, **corrections}

        extracted.validation_status = val_status
        extracted.validated_by      = request.user
        extracted.validated_at      = timezone.now()
        extracted.save()

        log_action(request, AuditLog.Action.DOCUMENT_PROCESS, "document", str(doc.id),
                   {"action": "validate", "corrections_count": len(corrections)})

        return Response(ExtractedDataSerializer(extracted).data)
