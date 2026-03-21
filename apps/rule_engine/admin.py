"""
Django Admin for Rule Engine.
Provides full management interface for RuleDefinition, RuleAssignment, AuditRun, AuditResult.
"""
from django.contrib import admin
from django.utils.html import format_html
from .models import (
    RuleDefinition, RuleDefinitionTranslation, RuleAssignment,
    AuditRun, AuditResult, AuditEvidence,
    RiskScoreSummary, ManualReviewDecision, CrossDocumentLink
)


class RuleDefinitionTranslationInline(admin.TabularInline):
    model = RuleDefinitionTranslation
    extra = 2
    fields = ["language", "name", "description", "fail_message", "suggested_action"]


@admin.register(RuleDefinition)
class RuleDefinitionAdmin(admin.ModelAdmin):
    list_display = [
        "rule_code", "version", "category", "rule_type", "scope",
        "default_severity", "is_active", "is_system_rule", "blocks_approval",
        "requires_cross_document",
    ]
    list_filter = ["category", "rule_type", "scope", "default_severity", "is_active", "is_system_rule"]
    search_fields = ["rule_code", "implementation_class"]
    readonly_fields = ["created_at", "updated_at"]
    inlines = [RuleDefinitionTranslationInline]
    ordering = ["rule_code"]

    fieldsets = [
        ("Identity", {"fields": ["rule_code", "version"]}),
        ("Classification", {"fields": ["category", "rule_type", "scope", "default_severity"]}),
        ("Implementation", {"fields": ["implementation_class", "default_config"]}),
        ("Behavior", {"fields": [
            "blocks_approval", "requires_cross_document",
            "requires_external_reference", "requires_historical_comparison", "is_ai_rule"
        ]}),
        ("Lifecycle", {"fields": [
            "is_active", "is_system_rule", "effective_from", "effective_until",
            "deprecated_at", "deprecation_reason"
        ]}),
        ("Metadata", {"fields": ["tags", "created_at", "updated_at"]}),
    ]


@admin.register(RuleAssignment)
class RuleAssignmentAdmin(admin.ModelAdmin):
    list_display = [
        "rule", "document_type", "organization", "applicability",
        "status", "effective_severity", "effective_blocks_approval",
    ]
    list_filter = ["document_type", "status", "applicability"]
    search_fields = ["rule__rule_code", "organization__name"]
    raw_id_fields = ["rule", "organization", "created_by"]
    ordering = ["rule__rule_code", "document_type"]

    def effective_severity(self, obj):
        return obj.effective_severity
    effective_severity.short_description = "Effective Severity"

    def effective_blocks_approval(self, obj):
        return obj.effective_blocks_approval
    effective_blocks_approval.short_description = "Blocks Approval"
    effective_blocks_approval.boolean = True


class AuditResultInline(admin.TabularInline):
    model = AuditResult
    extra = 0
    readonly_fields = [
        "rule_code", "applied_severity", "status",
        "explanation", "risk_contribution", "execution_time_ms"
    ]
    fields = readonly_fields
    can_delete = False
    show_change_link = True
    max_num = 50


@admin.register(AuditRun)
class AuditRunAdmin(admin.ModelAdmin):
    list_display = [
        "id", "document_type", "document_id", "organization",
        "status", "risk_score", "risk_level",
        "total_rules", "failed_rules", "blocks_approval",
        "started_at", "processing_time_ms",
    ]
    list_filter = ["status", "document_type", "risk_level", "blocks_approval"]
    search_fields = ["document_id", "organization__name"]
    readonly_fields = [
        "id", "started_at", "completed_at", "processing_time_ms",
        "total_rules", "passed_rules", "failed_rules", "warning_rules",
        "skipped_rules", "error_rules", "risk_score", "risk_level",
    ]
    inlines = [AuditResultInline]
    ordering = ["-started_at"]

    def risk_score_display(self, obj):
        if obj.risk_score is None:
            return "—"
        color = {"critical": "red", "high": "orange", "medium": "goldenrod", "low": "green"}.get(obj.risk_level, "gray")
        return format_html('<span style="color: {}; font-weight: bold;">{:.1f}</span>', color, obj.risk_score)
    risk_score_display.short_description = "Risk Score"


class AuditEvidenceInline(admin.TabularInline):
    model = AuditEvidence
    extra = 0
    readonly_fields = ["evidence_type", "field_name", "field_name_ar", "expected_value", "actual_value", "description"]
    fields = readonly_fields
    can_delete = False


@admin.register(AuditResult)
class AuditResultAdmin(admin.ModelAdmin):
    list_display = [
        "rule_code", "applied_severity", "status",
        "risk_contribution", "blocks_approval", "execution_time_ms", "executed_at",
    ]
    list_filter = ["status", "applied_severity", "blocks_approval"]
    search_fields = ["rule_code", "audit_run__document_id"]
    readonly_fields = [
        "rule_code", "rule_version", "applied_severity", "status",
        "explanation", "explanation_ar", "risk_contribution",
        "execution_time_ms", "executed_at", "error_message", "error_traceback",
    ]
    inlines = [AuditEvidenceInline]
    ordering = ["-executed_at"]


@admin.register(RiskScoreSummary)
class RiskScoreSummaryAdmin(admin.ModelAdmin):
    list_display = [
        "document_type", "document_id", "risk_score", "risk_level",
        "blocking_failures", "blocks_approval", "requires_manual_review", "last_calculated_at",
    ]
    list_filter = ["risk_level", "blocks_approval", "requires_manual_review", "document_type"]
    readonly_fields = list_display + ["organization", "latest_audit_run", "score_breakdown", "top_failed_rules"]
    ordering = ["-risk_score"]


@admin.register(ManualReviewDecision)
class ManualReviewDecisionAdmin(admin.ModelAdmin):
    list_display = ["audit_result", "decision", "reviewer", "is_false_positive", "reviewed_at"]
    list_filter = ["decision", "is_false_positive"]
    readonly_fields = ["reviewed_at"]


@admin.register(CrossDocumentLink)
class CrossDocumentLinkAdmin(admin.ModelAdmin):
    list_display = [
        "link_type", "source_document_type", "source_document_id",
        "target_document_type", "target_document_id",
        "match_status", "match_score", "auto_detected",
    ]
    list_filter = ["link_type", "match_status", "auto_detected"]
    search_fields = ["source_document_id", "target_document_id"]
    readonly_fields = ["created_at"]
