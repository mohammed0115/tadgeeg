"""
Document App Serializers

Provides DRF serializers for:
  - Document upload (input validation)
  - Document list / detail (output)
  - ExtractedData (OCR + AI output)
  - DocumentPageResult (per-page OCR)
  - DocumentAnalysisResult (full Financial AI + Audit pipeline output)
"""

from rest_framework import serializers
from .models import Document, ExtractedData, DocumentPageResult, DocumentAnalysisResult


# ── Input ─────────────────────────────────────────────────────────────────────

class DocumentUploadSerializer(serializers.Serializer):
    """Validates the multipart upload form data."""
    file          = serializers.FileField()
    document_type = serializers.ChoiceField(
        choices=Document.DocumentType.choices,
        default=Document.DocumentType.OTHER,
        required=False,
    )
    notes = serializers.CharField(required=False, allow_blank=True, max_length=1000)

    def validate_file(self, value):
        import os
        from django.conf import settings

        ext = os.path.splitext(value.name)[1].lower()
        if ext not in settings.ALLOWED_UPLOAD_EXTENSIONS:
            raise serializers.ValidationError(
                f"Unsupported file type '{ext}'. "
                f"Allowed: {', '.join(settings.ALLOWED_UPLOAD_EXTENSIONS)}"
            )

        max_size = getattr(settings, "MAX_UPLOAD_SIZE", 50 * 1024 * 1024)
        if value.size > max_size:
            raise serializers.ValidationError(
                f"File too large ({value.size:,} bytes). "
                f"Maximum allowed: {max_size // (1024*1024)} MB."
            )
        return value


# ── Output — core models ───────────────────────────────────────────────────────

class DocumentPageResultSerializer(serializers.ModelSerializer):
    class Meta:
        model  = DocumentPageResult
        fields = ["id", "page_number", "raw_text", "confidence", "image_path", "created_at"]
        read_only_fields = fields


class ExtractedDataSerializer(serializers.ModelSerializer):
    class Meta:
        model  = ExtractedData
        fields = [
            "id", "raw_text", "structured_data", "validation_status",
            "validated_by", "validated_at", "corrections",
            "extraction_method", "ai_model_used",
            "created_at", "updated_at",
        ]
        read_only_fields = fields


class DocumentAnalysisResultSerializer(serializers.ModelSerializer):
    """
    Full Financial AI + Audit pipeline output.
    Returned by /api/documents/{pk}/analysis/ endpoint.
    """
    rule_results = serializers.SerializerMethodField()
    fraud_patterns  = serializers.SerializerMethodField()
    duplicate_reasons = serializers.SerializerMethodField()
    compliance_issues = serializers.SerializerMethodField()
    missing_fields  = serializers.SerializerMethodField()

    class Meta:
        model  = DocumentAnalysisResult
        fields = [
            # Identification
            "id",
            # Classification
            "ai_document_type", "classification_confidence", "classification_method",
            # Extracted fields
            "vendor_name", "document_number", "doc_date", "currency",
            "total_amount", "tax_amount",
            # Scores
            "risk_score", "risk_level",
            "fraud_score", "duplicate_score", "compliance_score",
            # Flags
            "is_duplicate", "requires_review", "escalate",
            # Audit rules breakdown (computed)
            "rule_results",
            # Intelligence detail (computed)
            "fraud_patterns", "duplicate_reasons",
            "compliance_issues", "missing_fields",
            # Pipeline meta
            "pipeline_version", "processing_errors", "processing_time_ms",
            "created_at", "updated_at",
        ]
        read_only_fields = fields

    def get_rule_results(self, obj):
        return obj.audit_report.get("rule_results", [])

    def get_fraud_patterns(self, obj):
        return obj.analysis_data.get("fraud_patterns", [])

    def get_duplicate_reasons(self, obj):
        return obj.analysis_data.get("duplicate_reasons", [])

    def get_compliance_issues(self, obj):
        return obj.analysis_data.get("compliance_issues", [])

    def get_missing_fields(self, obj):
        return obj.analysis_data.get("missing_fields", [])


class DocumentListSerializer(serializers.ModelSerializer):
    """Compact list view — avoids loading heavy JSON fields."""
    uploaded_by_name = serializers.SerializerMethodField()
    has_analysis     = serializers.SerializerMethodField()

    class Meta:
        model  = Document
        fields = [
            "id", "original_filename", "document_type",
            "processing_status", "file_size", "mime_type",
            "language", "ocr_confidence", "is_handwritten",
            "page_count", "tags", "notes",
            "uploaded_by_name", "has_analysis",
            "created_at", "updated_at",
        ]
        read_only_fields = fields

    def get_uploaded_by_name(self, obj):
        if obj.uploaded_by:
            return getattr(obj.uploaded_by, "full_name", None) or obj.uploaded_by.email
        return None

    def get_has_analysis(self, obj):
        return hasattr(obj, "analysis_result")


class DocumentSerializer(serializers.ModelSerializer):
    """Full document detail including extracted data and analysis summary."""
    uploaded_by_name = serializers.SerializerMethodField()
    analysis_summary = serializers.SerializerMethodField()

    class Meta:
        model  = Document
        fields = [
            "id", "organization", "original_filename", "file",
            "document_type", "processing_status",
            "file_size", "mime_type",
            "language", "ocr_confidence", "is_handwritten",
            "page_count", "processing_error", "processing_duration_ms",
            "tags", "notes",
            "uploaded_by", "uploaded_by_name",
            "analysis_summary",
            "created_at", "updated_at",
        ]
        read_only_fields = fields

    def get_uploaded_by_name(self, obj):
        if obj.uploaded_by:
            return getattr(obj.uploaded_by, "full_name", None) or obj.uploaded_by.email
        return None

    def get_analysis_summary(self, obj):
        """Lightweight summary from DocumentAnalysisResult (no heavy JSON fields)."""
        try:
            ar = obj.analysis_result
            return {
                "ai_document_type":          ar.ai_document_type,
                "risk_level":                ar.risk_level,
                "risk_score":                ar.risk_score,
                "fraud_score":               ar.fraud_score,
                "duplicate_score":           ar.duplicate_score,
                "compliance_score":          ar.compliance_score,
                "is_duplicate":              ar.is_duplicate,
                "requires_review":           ar.requires_review,
                "escalate":                  ar.escalate,
                "vendor_name":               ar.vendor_name,
                "document_number":           ar.document_number,
                "total_amount":              str(ar.total_amount) if ar.total_amount else None,
                "classification_confidence": ar.classification_confidence,
            }
        except DocumentAnalysisResult.DoesNotExist:
            return None
