from django.contrib import admin
from django.utils.html import format_html

from apps.audit_engine.models import AIAnalysisLog, AuditIssue, AuditJob, AuditResult


@admin.register(AuditJob)
class AuditJobAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "organization",
        "audit_file_name",
        "audit_type",
        "colored_status",
        "processing_time_ms",
        "created_at",
    ]
    list_filter = ["status", "audit_type", "organization"]
    search_fields = ["id", "audit_file__original_name", "organization__name"]
    readonly_fields = [
        "id",
        "started_at",
        "completed_at",
        "failed_at",
        "processing_time_ms",
        "error_message",
        "created_at",
        "updated_at",
    ]
    date_hierarchy = "created_at"
    ordering = ["-created_at"]

    fieldsets = (
        (
            "Identity",
            {
                "fields": ("id", "organization", "created_by", "audit_file", "audit_type"),
            },
        ),
        (
            "Status",
            {
                "fields": (
                    "status",
                    "started_at",
                    "completed_at",
                    "failed_at",
                    "processing_time_ms",
                    "error_message",
                ),
            },
        ),
        (
            "Timestamps",
            {
                "fields": ("created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    @admin.display(description="File Name")
    def audit_file_name(self, obj):
        return obj.audit_file.original_name if obj.audit_file else "—"

    @admin.display(description="Status")
    def colored_status(self, obj):
        colour_map = {
            "pending": "#888",
            "queued": "#007bff",
            "running": "#fd7e14",
            "completed": "#28a745",
            "failed": "#dc3545",
            "canceled": "#6c757d",
        }
        colour = colour_map.get(obj.status, "#000")
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            colour,
            obj.get_status_display(),
        )


class AuditIssueInline(admin.TabularInline):
    model = AuditIssue
    extra = 0
    readonly_fields = [
        "id",
        "issue_code",
        "issue_type",
        "severity",
        "title",
        "description",
        "suggested_fix",
        "confidence_score",
        "page_number",
        "row_reference",
        "created_at",
    ]
    can_delete = False
    show_change_link = True
    fields = [
        "issue_code",
        "severity",
        "issue_type",
        "title",
        "confidence_score",
        "page_number",
    ]


@admin.register(AuditResult)
class AuditResultAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "audit_job",
        "overall_score",
        "risk_level",
        "model_used",
        "tokens_used",
        "created_at",
    ]
    list_filter = ["risk_level", "model_used"]
    search_fields = ["id", "audit_job__id", "audit_job__audit_file__original_name"]
    readonly_fields = [
        "id",
        "audit_job",
        "overall_score",
        "risk_level",
        "summary",
        "extracted_text",
        "extracted_entities",
        "model_used",
        "tokens_used",
        "created_at",
    ]
    inlines = [AuditIssueInline]
    ordering = ["-created_at"]

    fieldsets = (
        (
            "Score",
            {
                "fields": ("id", "audit_job", "overall_score", "risk_level"),
            },
        ),
        (
            "Summary",
            {
                "fields": ("summary", "model_used", "tokens_used"),
            },
        ),
        (
            "Extracted Data",
            {
                "fields": ("extracted_entities", "extracted_text"),
                "classes": ("collapse",),
            },
        ),
        (
            "Timestamps",
            {
                "fields": ("created_at",),
                "classes": ("collapse",),
            },
        ),
    )


@admin.register(AuditIssue)
class AuditIssueAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "audit_result",
        "issue_code",
        "severity",
        "issue_type",
        "title",
        "confidence_score",
        "created_at",
    ]
    list_filter = ["severity", "issue_type"]
    search_fields = ["issue_code", "title", "audit_result__id"]
    readonly_fields = [
        "id",
        "audit_result",
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
    ordering = ["severity", "created_at"]

    fieldsets = (
        (
            "Classification",
            {
                "fields": (
                    "id",
                    "audit_result",
                    "issue_code",
                    "issue_type",
                    "severity",
                    "confidence_score",
                ),
            },
        ),
        (
            "Details",
            {
                "fields": (
                    "title",
                    "description",
                    "suggested_fix",
                    "page_number",
                    "row_reference",
                ),
            },
        ),
        (
            "Metadata",
            {
                "fields": ("metadata",),
                "classes": ("collapse",),
            },
        ),
        (
            "Timestamps",
            {
                "fields": ("created_at",),
                "classes": ("collapse",),
            },
        ),
    )


@admin.register(AIAnalysisLog)
class AIAnalysisLogAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "audit_file",
        "model_name",
        "provider_name",
        "status",
        "total_tokens",
        "latency_ms",
        "created_at",
    ]
    list_filter = ["status", "provider_name", "model_name"]
    search_fields = ["id", "audit_file__original_name", "model_name"]
    readonly_fields = [
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
    ordering = ["-created_at"]
    date_hierarchy = "created_at"

    fieldsets = (
        (
            "Reference",
            {
                "fields": ("id", "audit_file", "audit_job"),
            },
        ),
        (
            "Model",
            {
                "fields": (
                    "model_name",
                    "provider_name",
                    "prompt_version",
                    "status",
                ),
            },
        ),
        (
            "Usage",
            {
                "fields": (
                    "input_tokens",
                    "output_tokens",
                    "total_tokens",
                    "latency_ms",
                ),
            },
        ),
        (
            "Response",
            {
                "fields": ("response",),
                "classes": ("collapse",),
            },
        ),
        (
            "Timestamps",
            {
                "fields": ("created_at",),
                "classes": ("collapse",),
            },
        ),
    )
