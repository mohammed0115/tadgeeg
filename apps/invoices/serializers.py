"""Invoice Serializers"""

from django.urls import reverse
from rest_framework import serializers
from .models import Invoice, InvoiceBatch, InvoiceValidationResult, VendorProfile, InvoiceAuditEvent


class InvoiceAuditDecisionMixin(serializers.Serializer):
    """Expose the same approval decision used by InvoiceApproveView.

    Views annotate these values from RiskScoreSummary so list serialization does
    not create one database query per invoice.  A missing summary is a blocked
    *not_audited* state, matching the conservative approval gate.
    """
    blocks_approval = serializers.SerializerMethodField()
    blocking_failures = serializers.SerializerMethodField()
    requires_manual_review = serializers.SerializerMethodField()
    audit_available = serializers.SerializerMethodField()
    audit_status = serializers.SerializerMethodField()

    def get_audit_available(self, obj):
        return bool(getattr(obj, "_audit_summary_present", False))

    def get_blocks_approval(self, obj):
        return bool(getattr(obj, "_audit_blocks_approval", True))

    def get_blocking_failures(self, obj):
        return int(getattr(obj, "_audit_blocking_failures", 0) or 0)

    def get_requires_manual_review(self, obj):
        return bool(getattr(obj, "_audit_requires_manual_review", False))

    def get_audit_status(self, obj):
        if not self.get_audit_available(obj):
            return "not_audited"
        return "blocked" if self.get_blocks_approval(obj) else "clear"


class InvoiceListSerializer(InvoiceAuditDecisionMixin, serializers.ModelSerializer):
    """Compact serializer for list views."""
    uploaded_by_name = serializers.CharField(source="uploaded_by.full_name", read_only=True, default="")
    audit_session_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = Invoice
        fields = [
            "id", "invoice_number", "invoice_date", "vendor_name", "vendor_vat_number",
            "total_amount", "vat_amount", "currency", "status", "risk_level", "risk_score",
            "is_duplicate", "ocr_confidence", "language", "has_qr_code",
            "blocks_approval", "blocking_failures", "requires_manual_review",
            "audit_available", "audit_status",
            "uploaded_by_name", "original_filename", "created_at", "audit_session_id",
        ]


class InvoiceDetailSerializer(InvoiceAuditDecisionMixin, serializers.ModelSerializer):
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
            "qr_code_image", "qr_code_data",  # ZATCA QR code (generated server-side)
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

    def to_representation(self, instance):
        """Translate per-rule descriptions to the active request language.

        ``validation_details`` is stored as Arabic-only JSON at write time.
        On read, we look each rule code up in the bilingual ``RULES_AR`` /
        ``RULES_EN`` tables in ``core.services.invoice_validator`` and swap
        the description so the UI matches the page language.
        """
        data = super().to_representation(instance)
        details = data.get("validation_details") or {}
        if not isinstance(details, dict) or not details:
            return data
        try:
            from core.services.invoice_validator import rule_description
        except Exception:
            return data
        translated = {}
        for code, rule in details.items():
            if isinstance(rule, dict):
                rule = dict(rule)
                rule["description"] = rule_description(code)
            translated[code] = rule
        data["validation_details"] = translated
        return data


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
    vendor_risk_score = serializers.FloatField(read_only=True)
    average_transaction_value = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True)

    class Meta:
        model = VendorProfile
        fields = [
            "id",
            "vendor_name", "vendor_vat_number", "vendor_cr_number",
            "first_seen", "last_seen",
            "invoice_count", "total_amount", "avg_invoice_amount", "average_transaction_value",
            "max_invoice_amount", "last_transaction_amount",
            "duplicate_count", "flagged_count", "compliance_issue_count", "high_risk_audit_count",
            "transaction_frequency_30d",
            "is_new", "is_suspicious", "is_approved",
            "risk_score", "vendor_risk_score", "risk_tier", "risk_notes",
            "tags", "transaction_history", "compliance_history",
            "last_audit_at", "last_compliance_issue_at", "updated_at",
        ]
        read_only_fields = fields


class InvoiceAuditEventSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source="user.full_name", read_only=True, default="System")

    class Meta:
        model = InvoiceAuditEvent
        fields = [
            "id", "event_type", "description", "user_name",
            "before_data", "after_data", "ip_address", "timestamp",
        ]
