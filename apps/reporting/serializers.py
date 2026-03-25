from rest_framework import serializers

from apps.reporting.models import Report, ReportItem


# ─────────────────────────────────────────────────────────────────────────────
# ReportItem
# ─────────────────────────────────────────────────────────────────────────────

class ReportItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReportItem
        fields = [
            "id",
            "report",
            "audit_result_id",
            "metadata",
            "created_at",
        ]
        read_only_fields = fields


# ─────────────────────────────────────────────────────────────────────────────
# Report (full — includes nested items)
# ─────────────────────────────────────────────────────────────────────────────

class ReportSerializer(serializers.ModelSerializer):
    items = ReportItemSerializer(many=True, read_only=True)
    generated_by_email = serializers.SerializerMethodField()
    organization_name = serializers.SerializerMethodField()

    class Meta:
        model = Report
        fields = [
            "id",
            "organization",
            "organization_name",
            "report_type",
            "title",
            "generated_by",
            "generated_by_email",
            "related_audit_job",
            "status",
            "file_path",
            "report_data",
            "error_message",
            "created_at",
            "updated_at",
            "items",
        ]
        read_only_fields = fields

    def get_generated_by_email(self, obj: Report) -> str | None:
        return obj.generated_by.email if obj.generated_by_id else None

    def get_organization_name(self, obj: Report) -> str | None:
        return obj.organization.name if obj.organization_id else None


# ─────────────────────────────────────────────────────────────────────────────
# Report (list — lightweight, no nested items)
# ─────────────────────────────────────────────────────────────────────────────

class ReportListSerializer(serializers.ModelSerializer):
    generated_by_email = serializers.SerializerMethodField()

    class Meta:
        model = Report
        fields = [
            "id",
            "report_type",
            "title",
            "status",
            "generated_by",
            "generated_by_email",
            "created_at",
        ]
        read_only_fields = fields

    def get_generated_by_email(self, obj: Report) -> str | None:
        return obj.generated_by.email if obj.generated_by_id else None


# ─────────────────────────────────────────────────────────────────────────────
# Write serializer — used only for POST /generate
# ─────────────────────────────────────────────────────────────────────────────

class GenerateReportSerializer(serializers.Serializer):
    report_type = serializers.ChoiceField(choices=Report.ReportType.choices)
    audit_job_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    format = serializers.ChoiceField(  # noqa: A003
        choices=["json", "csv"],
        default="json",
        required=False,
    )
