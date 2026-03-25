"""
DRF Serializers for Rule Engine API.
"""
from rest_framework import serializers
from apps.rule_engine.models import (
    RuleDefinition, RuleDefinitionTranslation, RuleAssignment,
    AuditRun, AuditResult, AuditEvidence,
    RiskScoreSummary, ManualReviewDecision
)


class RuleTranslationSerializer(serializers.ModelSerializer):
    class Meta:
        model = RuleDefinitionTranslation
        fields = ["language", "name", "description", "fail_message", "pass_message", "suggested_action"]


class RuleDefinitionSerializer(serializers.ModelSerializer):
    translations = RuleTranslationSerializer(many=True, read_only=True)
    name_en = serializers.SerializerMethodField()
    name_ar = serializers.SerializerMethodField()

    class Meta:
        model = RuleDefinition
        fields = [
            "rule_code", "version", "category", "rule_type", "scope",
            "default_severity", "blocks_approval",
            "requires_cross_document", "requires_external_reference",
            "is_active", "is_system_rule",
            "name_en", "name_ar", "translations",
        ]

    def get_name_en(self, obj):
        t = obj.translations.filter(language="en").first()
        return t.name if t else obj.rule_code

    def get_name_ar(self, obj):
        t = obj.translations.filter(language="ar").first()
        return t.name if t else obj.rule_code


class AuditEvidenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditEvidence
        fields = [
            "evidence_type", "field_name", "field_name_ar",
            "expected_value", "actual_value",
            "description", "description_ar",
            "linked_document_type", "linked_document_id",
        ]


class ManualReviewDecisionSerializer(serializers.ModelSerializer):
    reviewer_name = serializers.SerializerMethodField()

    class Meta:
        model = ManualReviewDecision
        fields = [
            "decision", "notes", "is_false_positive",
            "false_positive_reason", "reviewer_name", "reviewed_at",
        ]
        read_only_fields = ["reviewed_at", "reviewer_name"]

    def get_reviewer_name(self, obj):
        if obj.reviewer:
            return getattr(obj.reviewer, "get_full_name", lambda: str(obj.reviewer))()
        return None


class AuditResultSerializer(serializers.ModelSerializer):
    evidence = AuditEvidenceSerializer(source="evidence_items", many=True, read_only=True)
    manual_review = ManualReviewDecisionSerializer(read_only=True)
    rule_name_en = serializers.SerializerMethodField()
    rule_name_ar = serializers.SerializerMethodField()
    suggested_action_ar = serializers.SerializerMethodField()

    class Meta:
        model = AuditResult
        fields = [
            "rule_code", "rule_name_en", "rule_name_ar",
            "applied_severity", "status",
            "explanation", "explanation_ar",
            "risk_contribution", "blocks_approval",
            "evidence", "suggested_action_ar",
            "manual_review",
            "execution_time_ms", "executed_at",
        ]

    def get_rule_name_en(self, obj):
        try:
            t = obj.rule_assignment.rule.translations.filter(language="en").first()
            return t.name if t else obj.rule_code
        except Exception:
            return obj.rule_code

    def get_rule_name_ar(self, obj):
        try:
            t = obj.rule_assignment.rule.translations.filter(language="ar").first()
            return t.name if t else obj.rule_code
        except Exception:
            return obj.rule_code

    def get_suggested_action_ar(self, obj):
        try:
            t = obj.rule_assignment.rule.translations.filter(language="ar").first()
            return t.suggested_action if t else ""
        except Exception:
            return ""


class AuditRunSummarySerializer(serializers.ModelSerializer):
    results = AuditResultSerializer(many=True, read_only=True)
    failed_blocking = serializers.SerializerMethodField()
    top_failures = serializers.SerializerMethodField()
    pass_rate = serializers.SerializerMethodField()

    class Meta:
        model = AuditRun
        fields = [
            "id", "document_type", "document_id",
            "status", "risk_score", "risk_level",
            "total_rules", "passed_rules", "failed_rules",
            "warning_rules", "skipped_rules", "error_rules",
            "blocks_approval", "requires_manual_review",
            "pass_rate", "processing_time_ms",
            "started_at", "completed_at",
            "results", "failed_blocking", "top_failures",
        ]

    def get_failed_blocking(self, obj):
        return list(obj.results.filter(status="fail", blocks_approval=True).values_list("rule_code", flat=True))

    def get_top_failures(self, obj):
        return list(
            obj.results.filter(status__in=["fail", "warning"])
            .order_by("-risk_contribution")
            .values("rule_code", "applied_severity", "status", "risk_contribution")[:5]
        )

    def get_pass_rate(self, obj):
        if not obj.total_rules:
            return None
        evaluated = obj.total_rules - obj.skipped_rules - obj.error_rules
        if evaluated == 0:
            return None
        return round(obj.passed_rules / evaluated * 100, 1)


class RiskScoreSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = RiskScoreSummary
        fields = [
            "document_type", "document_id",
            "risk_score", "risk_level",
            "fraud_indicators", "compliance_failures", "blocking_failures",
            "requires_manual_review", "blocks_approval",
            "top_failed_rules", "score_breakdown",
            "last_calculated_at",
        ]


class DocumentCanonicalDataSerializer(serializers.Serializer):
    """Read-only view of a DocumentCanonicalData record."""
    document_type    = serializers.CharField()
    typed_model_name = serializers.CharField()
    typed_object_id  = serializers.UUIDField()
    canonical_data   = serializers.DictField()
    raw_ai_output    = serializers.DictField()
    version          = serializers.IntegerField()
    created_at       = serializers.DateTimeField()
    updated_at       = serializers.DateTimeField()


class TriggerAuditSerializer(serializers.Serializer):
    document_id = serializers.UUIDField()
    document_type = serializers.ChoiceField(choices=[
        "sales_invoice", "purchase_order", "bank_statement", "payroll",
        "expense", "tax_return", "fixed_asset", "sales_receipt", "other"
    ])
    triggered_by = serializers.ChoiceField(
        choices=["upload", "manual", "scheduled", "reprocess"],
        default="manual"
    )
