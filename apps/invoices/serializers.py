"""Invoice Serializers"""

from django.urls import reverse
from rest_framework import serializers
from .models import Invoice, InvoiceBatch, InvoiceValidationResult, VendorProfile, InvoiceAuditEvent


class InvoiceListSerializer(serializers.ModelSerializer):
    """Compact serializer for list views."""
    uploaded_by_name = serializers.CharField(source="uploaded_by.full_name", read_only=True, default="")
    audit_session_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = Invoice
        fields = [
            "id", "invoice_number", "invoice_date", "vendor_name", "vendor_vat_number",
            "total_amount", "vat_amount", "currency", "status", "risk_level", "risk_score",
            "is_duplicate", "ocr_confidence", "language", "has_qr_code",
            "uploaded_by_name", "original_filename", "created_at", "audit_session_id",
        ]


class InvoiceDetailSerializer(serializers.ModelSerializer):
    """Full serializer including all fields."""
    file = serializers.SerializerMethodField()
    uploaded_by_name = serializers.CharField(source="uploaded_by.full_name", read_only=True, default="")
    approved_by_name = serializers.CharField(source="approved_by.full_name", read_only=True, default="")

    class Meta:
        model = Invoice
        fields = "__all__"
        read_only_fields = [
            "id", "organization", "uploaded_by", "created_at", "updated_at",
            "risk_score", "risk_level", "is_duplicate", "ocr_confidence",
            "raw_text", "extracted_data", "ai_summary",
        ]

    def get_file(self, obj):
        if not obj.file:
            return None
        request = self.context.get("request")
        path = reverse("invoice-download", kwargs={"pk": obj.pk})
        return request.build_absolute_uri(path) if request else path


class InvoiceValidationResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvoiceValidationResult
        exclude = ["id", "invoice"]


class InvoiceBatchSerializer(serializers.ModelSerializer):
    uploaded_by_name = serializers.CharField(source="uploaded_by.full_name", read_only=True, default="")
    audit_session_id = serializers.UUIDField(read_only=True)
    audit_session_status = serializers.CharField(source="audit_session.status", read_only=True, default="")

    class Meta:
        model = InvoiceBatch
        fields = [
            "id", "batch_name", "status", "total_files", "processed_files",
            "failed_files", "uploaded_by_name", "created_at", "completed_at",
            "audit_session_id", "audit_session_status",
        ]


class VendorProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = VendorProfile
        exclude = ["id", "organization"]


class InvoiceAuditEventSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source="user.full_name", read_only=True, default="System")

    class Meta:
        model = InvoiceAuditEvent
        fields = [
            "id", "event_type", "description", "user_name",
            "before_data", "after_data", "ip_address", "timestamp",
        ]
