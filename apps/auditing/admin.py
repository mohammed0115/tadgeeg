"""Auditing App Admin."""

from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from .models import AuditDocument, AuditFinding


class TenantAwareModelAdmin(admin.ModelAdmin):
    """Filters by organization for multi-tenant isolation."""
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(organization=request.user.organization)


class AuditFindingInline(admin.TabularInline):
    model = AuditFinding
    extra = 0
    readonly_fields = ("finding_type", "severity", "title", "details", "source", "created_at")
    fields = ("finding_type", "severity", "title", "details", "source", "created_at")
    can_delete = False
    show_change_link = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(AuditDocument)
class AuditDocumentAdmin(TenantAwareModelAdmin):
    list_display = (
        "original_name",
        "status_badge",
        "detected_doc_type",
        "overall_risk_level",
        "overall_confidence_display",
        "language",
        "uploaded_by",
        "created_at",
    )
    list_filter = ("status", "overall_risk_level", "detected_doc_type", "language", "created_at")
    search_fields = ("original_name", "uploaded_by__email")
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
            "fields": ("id", "original_name", "file", "mime_type"),
        }),
        ("Classification", {
            "fields": ("selected_doc_type", "detected_doc_type", "language"),
        }),
        ("Ownership", {
            "fields": ("uploaded_by",),
        }),
        ("Processing", {
            "fields": ("status", "overall_confidence", "overall_risk_level", "executive_summary", "processing_error"),
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
        if obj.overall_confidence is None:
            # format_html() with no interpolation arguments is deprecated in
            # Django 5.0 and removed in 6.0. There is nothing to interpolate
            # here — the markup is a constant — so mark_safe is what this line
            # always meant.
            return mark_safe('<span style="color:#6b7280">—</span>')
        val = obj.overall_confidence
        pct = round(val * 100, 1) if val <= 1.0 else round(val, 1)
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


# ─── AI Validation Harness admin ──────────────────────────────────────────────
from apps.auditing.models import AIValidationDataset, AIValidationRun


@admin.register(AIValidationDataset)
class AIValidationDatasetAdmin(admin.ModelAdmin):
    list_display = ["name", "version", "document_type", "language",
                    "document_count", "created_at"]
    search_fields = ["name", "document_type"]
    list_filter = ["document_type", "language"]


@admin.register(AIValidationRun)
class AIValidationRunAdmin(admin.ModelAdmin):
    list_display = ["component", "model_version", "headline", "decision",
                    "created_at"]
    list_filter = ["component", "decision"]
    search_fields = ["model_version", "dataset__name"]
    readonly_fields = ["raw_metrics", "created_at", "completed_at",
                       "true_positives", "false_positives",
                       "true_negatives", "false_negatives"]
    fieldsets = (
        ("Identity", {
            "fields": ("dataset", "component", "model_version"),
        }),
        ("Classifier metrics", {
            "fields": ("precision", "recall", "f1_score", "accuracy",
                       "false_positive_rate", "false_negative_rate",
                       "true_positives", "false_positives",
                       "true_negatives", "false_negatives"),
        }),
        ("OCR metrics", {
            "fields": ("field_accuracy", "document_accuracy",
                       "character_error_rate", "word_error_rate",
                       "average_processing_ms"),
            "classes": ("collapse",),
        }),
        ("Forecast metrics", {
            "fields": ("mape", "mae", "rmse", "bias"),
            "classes": ("collapse",),
        }),
        ("Sign-off", {
            "fields": ("decision", "approver", "approver_notes"),
        }),
        ("Audit", {
            "fields": ("raw_metrics", "created_at", "completed_at"),
        }),
    )

    @admin.display(description="Headline metric")
    def headline(self, obj):
        v = obj.headline_metric()
        return f"{v:.4f}" if v is not None else "—"
