"""Documents Views — Upload, OCR, and AI Processing"""

import os
import time
import logging
from django.utils import timezone
from rest_framework import status, generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from drf_spectacular.utils import extend_schema, OpenApiParameter
from django.conf import settings
from core.services.ocr_service import process_document_hybrid
from core.utils.audit import log_action
from apps.authentication.models import AuditLog
from apps.authentication.permissions import IsOwnOrganization
from .models import Document, ExtractedData, DocumentPageResult
from .serializers import DocumentSerializer, ExtractedDataSerializer, DocumentUploadSerializer

logger = logging.getLogger("finai")


class DocumentUploadView(APIView):
    """Upload a document for OCR and AI processing."""
    parser_classes = [MultiPartParser, FormParser]
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Documents"],
        summary="Upload a financial document",
        request=DocumentUploadSerializer,
        responses={201: DocumentSerializer},
    )
    def post(self, request):
        serializer = DocumentUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        uploaded_file = serializer.validated_data["file"]
        doc_type = serializer.validated_data.get("document_type", "other")

        # Validate size
        if uploaded_file.size > settings.MAX_UPLOAD_SIZE:
            return Response(
                {"error": f"File too large. Max {settings.MAX_UPLOAD_SIZE_MB}MB."},
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )

        # Validate extension
        ext = os.path.splitext(uploaded_file.name)[1].lower()
        if ext not in settings.ALLOWED_UPLOAD_EXTENSIONS:
            return Response(
                {"error": f"Unsupported file type. Allowed: {settings.ALLOWED_UPLOAD_EXTENSIONS}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        doc = Document.objects.create(
            organization=request.user.organization,
            uploaded_by=request.user,
            file=uploaded_file,
            original_filename=uploaded_file.name,
            file_size=uploaded_file.size,
            mime_type=uploaded_file.content_type or f"application/{ext[1:]}",
            document_type=doc_type,
            processing_status=Document.ProcessingStatus.PENDING,
            notes=serializer.validated_data.get("notes", ""),
        )

        log_action(request, AuditLog.Action.DOCUMENT_UPLOAD, "document", str(doc.id))

        # Trigger async processing
        from .tasks import process_document_task
        process_document_task.delay(str(doc.id))

        return Response(DocumentSerializer(doc).data, status=status.HTTP_201_CREATED)


class DocumentProcessView(APIView):
    """Trigger (re)processing of an uploaded document."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Documents"],
        summary="Process a document with OCR + AI",
        request={"type": "object", "properties": {
            "use_openai": {"type": "boolean", "default": True},
            "force_reprocess": {"type": "boolean", "default": False},
        }},
    )
    def post(self, request, pk):
        try:
            doc = Document.objects.get(pk=pk, organization=request.user.organization)
        except Document.DoesNotExist:
            return Response({"error": "Document not found."}, status=status.HTTP_404_NOT_FOUND)

        if doc.processing_status == Document.ProcessingStatus.PROCESSING:
            return Response({"error": "Document is already being processed."}, status=status.HTTP_409_CONFLICT)

        use_openai = request.data.get("use_openai", True)
        doc.processing_status = Document.ProcessingStatus.PROCESSING
        doc.save(update_fields=["processing_status"])

        start = time.time()
        try:
            result = process_document_hybrid(doc.file.path, doc.document_type, use_openai=use_openai)

            # Save extracted data
            extracted, _ = ExtractedData.objects.update_or_create(
                document=doc,
                defaults={
                    "raw_text": result["raw_text"],
                    "structured_data": result["structured_data"],
                    "extraction_method": result["method"],
                    "ai_model_used": result["structured_data"].get("_ai_model", ""),
                },
            )

            # Save per-page results
            DocumentPageResult.objects.filter(document=doc).delete()
            for pr in result.get("page_results", []):
                DocumentPageResult.objects.create(
                    document=doc,
                    page_number=pr["page"],
                    raw_text=pr["text"],
                    confidence=pr["confidence"],
                    image_path=pr.get("image_path", ""),
                )

            doc.processing_status = Document.ProcessingStatus.COMPLETED
            if result["confidence"] < 60:
                doc.processing_status = Document.ProcessingStatus.NEEDS_REVIEW
            doc.ocr_confidence = result["confidence"]
            doc.language = result.get("language", "unknown")
            doc.is_handwritten = result.get("is_handwritten", False)
            doc.processing_duration_ms = result.get("processing_ms", 0)
            doc.processing_error = ""
            doc.save()

            log_action(request, AuditLog.Action.DOCUMENT_PROCESS, "document", str(doc.id))

            return Response({
                "document": DocumentSerializer(doc).data,
                "extracted": ExtractedDataSerializer(extracted).data,
                "page_count": len(result.get("page_results", [])),
                "processing_ms": result.get("processing_ms"),
            })

        except Exception as e:
            doc.processing_status = Document.ProcessingStatus.FAILED
            doc.processing_error = str(e)
            doc.save(update_fields=["processing_status", "processing_error"])
            logger.error(f"Document {pk} processing failed: {e}")
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class DocumentListView(generics.ListAPIView):
    serializer_class = DocumentSerializer
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Documents"],
        summary="List documents for the user's organization",
        parameters=[
            OpenApiParameter("document_type", description="Filter by type"),
            OpenApiParameter("status", description="Filter by processing status"),
            OpenApiParameter("language", description="Filter by language"),
        ],
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        qs = Document.objects.filter(organization=self.request.user.organization).order_by("-created_at")
        p = self.request.query_params
        if v := p.get("document_type"):
            qs = qs.filter(document_type=v)
        if v := p.get("status"):
            qs = qs.filter(processing_status=v)
        if v := p.get("language"):
            qs = qs.filter(language=v)
        if v := p.get("search"):
            qs = qs.filter(original_filename__icontains=v)
        return qs


class DocumentDetailView(generics.RetrieveDestroyAPIView):
    serializer_class = DocumentSerializer
    permission_classes = [IsAuthenticated, IsOwnOrganization]

    @extend_schema(tags=["Documents"], summary="Get document details and extracted data")
    def get(self, request, *args, **kwargs):
        doc = self.get_object()
        data = DocumentSerializer(doc).data
        try:
            data["extracted"] = ExtractedDataSerializer(doc.extracted_data).data
        except ExtractedData.DoesNotExist:
            data["extracted"] = None
        return Response(data)

    def get_queryset(self):
        return Document.objects.filter(organization=self.request.user.organization)


class DocumentValidateView(APIView):
    """Manually validate or correct extracted data."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Documents"],
        summary="Validate or correct extracted document data",
        request={"type": "object", "properties": {
            "corrections": {"type": "object"},
            "validation_status": {"type": "string", "enum": ["validated", "rejected"]},
        }},
    )
    def patch(self, request, pk):
        try:
            doc = Document.objects.get(pk=pk, organization=request.user.organization)
            extracted = doc.extracted_data
        except (Document.DoesNotExist, ExtractedData.DoesNotExist):
            return Response({"error": "Document or extracted data not found."}, status=404)

        corrections = request.data.get("corrections", {})
        val_status = request.data.get("validation_status", ExtractedData.ValidationStatus.VALIDATED)

        if corrections:
            # Merge corrections into structured data
            extracted.structured_data.update(corrections)
            extracted.corrections = corrections

        extracted.validation_status = val_status
        extracted.validated_by = request.user
        extracted.validated_at = timezone.now()
        extracted.save()

        return Response(ExtractedDataSerializer(extracted).data)
