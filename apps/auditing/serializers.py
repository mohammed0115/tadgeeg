"""Serializers for auditing app models."""

from rest_framework import serializers
from .models import AccountingRuleEvaluation


class AccountingRuleEvaluationSerializer(serializers.ModelSerializer):
    """Serializer for individual accounting rule evaluation results."""

    class Meta:
        model = AccountingRuleEvaluation
        fields = [
            "id",
            "standard",
            "rule_code",
            "rule_title",
            "rule_category",
            "rule_status",
            "rule_severity",
            "observation",
            "failure_reason",
            "recommendation",
            "score_impact",
            "confidence",
            "related_fields",
            "metadata_json",
            "evaluated_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "evaluated_at", "created_at", "updated_at"]


class AccountingRuleEvaluationDetailedSerializer(AccountingRuleEvaluationSerializer):
    """Extended serializer with related object information."""

    report_id = serializers.PrimaryKeyRelatedField(
        source="report", read_only=True
    )
    invoice_id = serializers.PrimaryKeyRelatedField(
        source="invoice", read_only=True
    )
    audit_document_id = serializers.PrimaryKeyRelatedField(
        source="audit_document", read_only=True
    )

    class Meta(AccountingRuleEvaluationSerializer.Meta):
        fields = AccountingRuleEvaluationSerializer.Meta.fields + [
            "report_id",
            "invoice_id",
            "audit_document_id",
        ]


class RuleSummarySerializer(serializers.Serializer):
    """Serializer for rule evaluation summary statistics."""

    total_rules = serializers.IntegerField()
    passed = serializers.IntegerField()
    failed = serializers.IntegerField()
    warning = serializers.IntegerField()
    not_applicable = serializers.IntegerField()
    insufficient_data = serializers.IntegerField()
    compliance_score = serializers.FloatField()
    risk_impact = serializers.FloatField()
    high_severity_findings = serializers.IntegerField()


class AccountingRulesEvaluationResponseSerializer(serializers.Serializer):
    """Serializer for complete accounting rules evaluation response."""

    summary = RuleSummarySerializer()
    results = AccountingRuleEvaluationSerializer(many=True)
    standard = serializers.CharField()
    evaluated_at = serializers.DateTimeField()


class RuleStatsByCodeSerializer(serializers.Serializer):
    """Serializer for rule failure frequency analysis."""

    rule_code = serializers.CharField()
    rule_title = serializers.CharField()
    rule_category = serializers.CharField()
    rule_severity = serializers.CharField()
    count = serializers.IntegerField()
    percentage = serializers.FloatField()


class AccountingFindingsSummarySerializer(serializers.Serializer):
    """Serializer for accounting findings summary for executive reports."""

    standard = serializers.CharField()
    compliance_score = serializers.FloatField()
    total_rules_evaluated = serializers.IntegerField()
    failed_rules_count = serializers.IntegerField()
    critical_findings_count = serializers.IntegerField()
    high_findings_count = serializers.IntegerField()
    top_failed_rules = RuleStatsByCodeSerializer(many=True)
    key_recommendations = serializers.ListField(child=serializers.CharField())
    last_evaluated = serializers.DateTimeField()
