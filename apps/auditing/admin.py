"""Auditing App Admin."""

from django.contrib import admin
from django.utils.html import format_html

from .models import AuditDocument, AuditFinding


class AuditFindingInline(admin.TabularInline):
    model = AuditFinding
    extra = 0
    readonly_fields = ("finding_type", "severity", "title", "details", "created_at")
    fields = ("finding_type", "severity", "title", "details", "created_at")
    can_delete = False
    show_change_link = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(AuditDocument)
class AuditDocumentAdmin(admin.ModelAdmin):
    list_display = (
        "original_name",
        "status_badge",
        "detected_doc_type",
        "overall_risk_level",
        "overall_confidence_display",
        "language",
        "uploaded_by",
        "organization",
        "created_at",
    )
    list_filter = ("status", "overall_risk_level", "detected_doc_type", "language", "created_at")
    search_fields = ("original_name", "uploaded_by__email", "organization__name")
    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
        "extracted_text",
        "normalized_text",
        "ai_result",
        "processing_error",
    )
    ordering = ("-created_at",)
    inlines = [AuditFindingInline]

    fieldsets = (
        ("Document Info", {
            "fields": ("id", "original_name", "file", "mime_type", "file_size"),
        }),
        ("Classification", {
            "fields": ("selected_doc_type", "detected_doc_type", "language"),
        }),
        ("Ownership", {
            "fields": ("uploaded_by", "organization"),
        }),
        ("Processing", {
            "fields": ("status", "overall_confidence", "overall_risk_level", "processing_error"),
        }),
        ("AI Results", {
            "fields": ("ai_result",),
            "classes": ("collapse",),
        }),
        ("Extracted Text", {
            "fields": ("extracted_text", "normalized_text"),
            "classes": ("collapse",),
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
        }),
    )

    def status_badge(self, obj):
        colors = {
            "pending": "#f59e0b",
            "processing": "#3b82f6",
            "completed": "#10b981",
            "failed": "#ef4444",
        }
        color = colors.get(obj.status, "#6b7280")
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;border-radius:9999px;font-size:11px;font-weight:600">{}</span>',
            color,
            obj.get_status_display(),
        )
    status_badge.short_description = "Status"

    def overall_confidence_display(self, obj):
        pct = round(obj.overall_confidence * 100, 1) if obj.overall_confidence <= 1 else round(obj.overall_confidence, 1)
        color = "#10b981" if pct >= 75 else "#f59e0b" if pct >= 40 else "#ef4444"
        return format_html(
            '<span style="color:{};font-weight:600">{:.1f}%</span>',
            color, pct,
        )
    overall_confidence_display.short_description = "Confidence"


@admin.register(AuditFinding)
class AuditFindingAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "finding_type",
        "severity_badge",
        "document",
        "created_at",
    )
    list_filter = ("finding_type", "severity", "created_at")
    search_fields = ("title", "details", "document__original_name")
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)

    def severity_badge(self, obj):
        colors = {"low": "#10b981", "medium": "#f59e0b", "high": "#ef4444"}
        color = colors.get(obj.severity, "#6b7280")
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;border-radius:9999px;font-size:11px;font-weight:600">{}</span>',
            color,
            obj.get_severity_display(),
        )
    severity_badge.short_description = "Severity"
