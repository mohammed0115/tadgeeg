from rest_framework import serializers
from .models import AuditCase, AuditFinding, AuditSession, CaseComment

class CaseCommentSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source="author.full_name", read_only=True)
    class Meta:
        model = CaseComment
        fields = ["id", "case", "author", "author_name", "text", "is_internal", "created_at"]
        read_only_fields = ["id", "author", "created_at"]

class AuditCaseSerializer(serializers.ModelSerializer):
    comments = CaseCommentSerializer(many=True, read_only=True)
    assigned_to_name = serializers.CharField(source="assigned_to.full_name", read_only=True)
    invoice_number = serializers.CharField(source="invoice.invoice_number", read_only=True)

    class Meta:
        model = AuditCase
        fields = "__all__"
        read_only_fields = ["id", "case_number", "organization", "created_at", "updated_at"]


class AuditSessionSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source="created_by.full_name", read_only=True, default="")
    progress_percent = serializers.FloatField(read_only=True)

    class Meta:
        model = AuditSession
        fields = [
            "id",
            "name",
            "status",
            "total_count",
            "processed_count",
            "success_count",
            "failed_count",
            "review_required_count",
            "duplicate_count",
            "high_risk_count",
            "average_risk_score",
            "max_risk_score",
            "last_error",
            "context",
            "started_at",
            "completed_at",
            "failed_at",
            "created_at",
            "updated_at",
            "created_by_name",
            "progress_percent",
        ]


class AuditFindingSerializer(serializers.ModelSerializer):
    invoice_number = serializers.CharField(source="invoice.invoice_number", read_only=True, default="")
    vendor_name = serializers.CharField(source="invoice.vendor_name", read_only=True, default="")

    class Meta:
        model = AuditFinding
        fields = [
            "id",
            "audit_session",
            "invoice",
            "invoice_number",
            "vendor_name",
            "rule_code",
            "rule_name",
            "rule_group",
            "severity",
            "status",
            "message",
            "details",
            "source",
            "first_detected_at",
            "last_detected_at",
            "resolved_at",
        ]
