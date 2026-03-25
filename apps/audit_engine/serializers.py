from rest_framework import serializers

from apps.audit_engine.models import AIAnalysisLog, AuditIssue, AuditJob, AuditResult


class AuditIssueSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditIssue
        fields = [
            "id",
            "issue_code",
            "issue_type",
            "severity",
            "title",
            "description",
            "page_number",
            "row_reference",
            "suggested_fix",
            "confidence_score",
            "metadata",
            "created_at",
        ]
        read_only_fields = fields


class AuditResultSerializer(serializers.ModelSerializer):
    issues = AuditIssueSerializer(many=True, read_only=True)

    class Meta:
        model = AuditResult
        fields = [
            "id",
            "audit_job",
            "overall_score",
            "risk_level",
            "summary",
            "extracted_text",
            "extracted_entities",
            "model_used",
            "tokens_used",
            "issues",
            "created_at",
        ]
        read_only_fields = fields


class AuditJobSerializer(serializers.ModelSerializer):
    """Full detail serializer — includes nested result."""

    result = AuditResultSerializer(read_only=True)
    audit_file_name = serializers.CharField(
        source="audit_file.original_name", read_only=True
    )
    created_by_email = serializers.EmailField(
        source="created_by.email", read_only=True, default=None
    )

    class Meta:
        model = AuditJob
        fields = [
            "id",
            "organization",
            "audit_file",
            "audit_file_name",
            "created_by",
            "created_by_email",
            "audit_type",
            "status",
            "started_at",
            "completed_at",
            "failed_at",
            "error_message",
            "processing_time_ms",
            "created_at",
            "updated_at",
            "result",
        ]
        read_only_fields = fields


class AuditJobListSerializer(serializers.ModelSerializer):
    """Lightweight list serializer — no nested result for performance."""

    audit_file_name = serializers.CharField(
        source="audit_file.original_name", read_only=True
    )

    class Meta:
        model = AuditJob
        fields = [
            "id",
            "organization_id",
            "audit_file",
            "audit_file_name",
            "audit_type",
            "status",
            "created_at",
            "processing_time_ms",
        ]
        read_only_fields = fields


class RunAuditSerializer(serializers.Serializer):
    """Write serializer for the /jobs/run/ action."""

    file_id = serializers.UUIDField(
        help_text="UUID of the AuditFile to audit.",
    )
    audit_type = serializers.ChoiceField(
        choices=AuditJob.AuditType.choices,
        default=AuditJob.AuditType.GENERIC_AUDIT,
        help_text="Type of audit to perform.",
    )

    def validate_file_id(self, value):
        from apps.storage_management.models import AuditFile

        try:
            AuditFile.objects.get(id=value)
        except AuditFile.DoesNotExist:
            raise serializers.ValidationError(
                f"AuditFile with id '{value}' does not exist."
            )
        return value


class AIAnalysisLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIAnalysisLog
        fields = [
            "id",
            "audit_file",
            "audit_job",
            "model_name",
            "provider_name",
            "prompt_version",
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "latency_ms",
            "status",
            "response",
            "created_at",
        ]
        read_only_fields = fields
