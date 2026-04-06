"""
DRF Serializers for the unified document reporting system.

JSON Schema for each report type + the Executive Report.
All serializers are read-only (output-only) response shapes.
"""

from rest_framework import serializers


# ─────────────────────────────────────────────────────────────
# Sub-serializers (shared)
# ─────────────────────────────────────────────────────────────

class EvidenceSerializer(serializers.Serializer):
    type           = serializers.CharField(source="type")
    field_name     = serializers.CharField()
    field_name_ar  = serializers.CharField()
    expected       = serializers.JSONField()
    actual         = serializers.JSONField()
    description    = serializers.CharField()
    description_ar = serializers.CharField()


class RuleEvaluationRowSerializer(serializers.Serializer):
    rule_code           = serializers.CharField()
    rule_name_en        = serializers.CharField()
    rule_name_ar        = serializers.CharField()
    status              = serializers.CharField()           # pass|fail|warning|skipped|error
    status_ar           = serializers.CharField()
    severity            = serializers.CharField()           # critical|high|medium|low
    severity_ar         = serializers.CharField()
    explanation_en      = serializers.CharField()
    explanation_ar      = serializers.CharField()
    risk_contribution   = serializers.FloatField()
    blocks_approval     = serializers.BooleanField()
    execution_time_ms   = serializers.IntegerField()
    suggested_action_ar = serializers.CharField()
    evidence            = serializers.ListField(child=serializers.DictField())


class ViolationSerializer(serializers.Serializer):
    rule_code          = serializers.CharField()
    severity           = serializers.CharField()
    severity_ar        = serializers.CharField()
    title_en           = serializers.CharField()
    title_ar           = serializers.CharField()
    blocks_approval    = serializers.BooleanField()
    risk_contribution  = serializers.FloatField()
    recommendation_ar  = serializers.CharField()
    recommendation_en  = serializers.CharField()
    financial_impact   = serializers.FloatField()


class RecommendationSerializer(serializers.Serializer):
    priority          = serializers.CharField()
    rule_code         = serializers.CharField()
    action_en         = serializers.CharField()
    action_ar         = serializers.CharField()
    impact_ar         = serializers.CharField()
    impact_en         = serializers.CharField()
    financial_impact  = serializers.FloatField()


# ─────────────────────────────────────────────────────────────
# Report Meta
# ─────────────────────────────────────────────────────────────

class ReportMetaSerializer(serializers.Serializer):
    report_id               = serializers.UUIDField(allow_null=True)
    report_type             = serializers.CharField()
    document_type           = serializers.CharField()
    document_id             = serializers.UUIDField()
    organization_id         = serializers.UUIDField()
    organization_name       = serializers.CharField()
    generated_at            = serializers.DateTimeField()
    generated_by            = serializers.CharField()
    language                = serializers.CharField()
    audit_run_id            = serializers.UUIDField(allow_null=True)
    status                  = serializers.CharField()   # clean|issues_found|critical|not_audited
    status_ar               = serializers.CharField()
    engine_version          = serializers.CharField()
    document_type_label_ar  = serializers.CharField()
    document_type_label_en  = serializers.CharField()


# ─────────────────────────────────────────────────────────────
# Report Summary
# ─────────────────────────────────────────────────────────────

class ReportSummarySerializer(serializers.Serializer):
    total_amount           = serializers.FloatField()
    currency               = serializers.CharField()
    item_count             = serializers.IntegerField()
    total_rules            = serializers.IntegerField()
    rules_passed           = serializers.IntegerField()
    rules_failed           = serializers.IntegerField()
    rules_warning          = serializers.IntegerField()
    rules_skipped          = serializers.IntegerField()
    rules_error            = serializers.IntegerField()
    pass_rate              = serializers.FloatField()
    risk_score             = serializers.FloatField()
    risk_level             = serializers.CharField()
    risk_level_ar          = serializers.CharField()
    blocking_failures      = serializers.IntegerField()
    requires_manual_review = serializers.BooleanField()
    blocks_approval        = serializers.BooleanField()
    error_rate             = serializers.FloatField()
    processing_time_ms     = serializers.IntegerField()


# ─────────────────────────────────────────────────────────────
# AI Insights
# ─────────────────────────────────────────────────────────────

class AIInsightsSerializer(serializers.Serializer):
    anomalies       = serializers.ListField(child=serializers.DictField())
    patterns        = serializers.ListField(child=serializers.DictField())
    risk_factors    = serializers.ListField(child=serializers.DictField())
    vendor_behavior = serializers.DictField()
    ai_summary_ar   = serializers.CharField()
    ai_summary_en   = serializers.CharField()
    has_insights    = serializers.BooleanField()


# ─────────────────────────────────────────────────────────────
# Compliance
# ─────────────────────────────────────────────────────────────

class ComplianceSerializer(serializers.Serializer):
    zatca_compliant   = serializers.BooleanField()
    compliance_score  = serializers.FloatField()
    required_fields_ok = serializers.BooleanField(required=False)
    checks            = serializers.DictField()
    missing_fields    = serializers.ListField(child=serializers.DictField())
    failed_rules      = serializers.ListField(child=serializers.CharField())
    warning_rules     = serializers.ListField(child=serializers.CharField())
    violations        = serializers.ListField(child=serializers.DictField(), required=False)


# ─────────────────────────────────────────────────────────────
# Audit Trail
# ─────────────────────────────────────────────────────────────

class AuditTrailSerializer(serializers.Serializer):
    auditor            = serializers.CharField()
    audit_date         = serializers.DateTimeField(allow_null=True)
    audit_type         = serializers.CharField()       # automatic|manual
    triggered_by       = serializers.CharField()
    engine_version     = serializers.CharField()
    processing_time_ms = serializers.IntegerField()


# ─────────────────────────────────────────────────────────────
# Full Document Report (unified for all 8 types)
# ─────────────────────────────────────────────────────────────

class DocumentAuditReportSerializer(serializers.Serializer):
    """
    Full report for any single document.
    The document_specific field varies by document_type.

    Schema:
    {
        report_meta:       ReportMeta,
        summary:           ReportSummary,
        key_fields:        dict (type-specific),
        rule_evaluation:   [RuleEvaluationRow, ...],
        violations:        [Violation, ...],
        ai_insights:       AIInsights,
        compliance:        Compliance,
        recommendations:   [Recommendation, ...],
        audit_trail:       AuditTrail,
        document_specific: dict (type-specific extra sections)
    }
    """
    report_meta       = ReportMetaSerializer()
    summary           = ReportSummarySerializer()
    key_fields        = serializers.DictField()
    rule_evaluation   = RuleEvaluationRowSerializer(many=True)
    violations        = ViolationSerializer(many=True)
    ai_insights       = AIInsightsSerializer()
    compliance        = ComplianceSerializer()
    recommendations   = RecommendationSerializer(many=True)
    audit_trail       = AuditTrailSerializer()
    document_specific = serializers.DictField()


# ─────────────────────────────────────────────────────────────
# Executive Report Serializers
# ─────────────────────────────────────────────────────────────

class ExecutiveSummarySerializer(serializers.Serializer):
    overall_score      = serializers.FloatField()
    risk_level         = serializers.CharField()
    risk_level_ar      = serializers.CharField()
    compliance_rate    = serializers.FloatField()
    avg_risk_score     = serializers.FloatField()
    total_documents    = serializers.IntegerField()
    top_issues_count   = serializers.IntegerField()
    summary_ar         = serializers.CharField()
    summary_en         = serializers.CharField()


class FinancialOverviewSerializer(serializers.Serializer):
    total_revenue     = serializers.FloatField()
    total_expenses    = serializers.FloatField()
    net_profit        = serializers.FloatField()
    total_vat_payable = serializers.FloatField()
    currency          = serializers.CharField()


class AuditOverviewSerializer(serializers.Serializer):
    total_documents_audited = serializers.IntegerField()
    clean_documents         = serializers.IntegerField()
    documents_with_issues   = serializers.IntegerField()
    blocking_documents      = serializers.IntegerField()
    pass_rate               = serializers.FloatField()
    failure_rate            = serializers.FloatField()
    total_rules_evaluated   = serializers.IntegerField()
    total_rules_passed      = serializers.IntegerField()
    total_rules_failed      = serializers.IntegerField()
    top_failed_rules        = serializers.ListField(child=serializers.DictField())


class RiskAnalysisSerializer(serializers.Serializer):
    distribution   = serializers.DictField()
    high_risk_docs = serializers.ListField(child=serializers.DictField())
    total_critical = serializers.IntegerField()
    total_high     = serializers.IntegerField()


class ComplianceOverviewSerializer(serializers.Serializer):
    zatca_compliance_rate = serializers.FloatField()
    vat_failures          = serializers.IntegerField()
    vat_total_checks      = serializers.IntegerField()


class AIInsightsExecutiveSerializer(serializers.Serializer):
    fraud_indicator_count = serializers.IntegerField()
    structuring_alerts    = serializers.IntegerField()
    ghost_employee_alerts = serializers.IntegerField()
    duplicate_alerts      = serializers.IntegerField()
    self_approval_alerts  = serializers.IntegerField()


class ExecutiveRecommendationSerializer(serializers.Serializer):
    priority   = serializers.CharField()
    rule_code  = serializers.CharField()
    occurrence = serializers.IntegerField()
    action_ar  = serializers.CharField()
    action_en  = serializers.CharField()


class ExecutiveReportSerializer(serializers.Serializer):
    """
    Full organization-wide executive report.

    Schema:
    {
        report_meta:          ReportMeta (no document_id),
        executive_summary:    ExecutiveSummary,
        financial_overview:   FinancialOverview,
        audit_overview:       AuditOverview,
        risk_analysis:        RiskAnalysis,
        compliance_overview:  ComplianceOverview,
        top_issues:           [{rule_code, applied_severity, count, avg_risk},...],
        ai_insights:          AIInsightsExecutive,
        recommendations:      [ExecutiveRecommendation,...],
        document_breakdown:   [{document_type, count, avg_risk, failed},...],
    }
    """
    report_meta          = serializers.DictField()
    executive_summary    = ExecutiveSummarySerializer()
    financial_overview   = FinancialOverviewSerializer()
    audit_overview       = AuditOverviewSerializer()
    risk_analysis        = RiskAnalysisSerializer()
    compliance_overview  = ComplianceOverviewSerializer()
    top_issues           = serializers.ListField(child=serializers.DictField())
    ai_insights          = AIInsightsExecutiveSerializer()
    recommendations      = ExecutiveRecommendationSerializer(many=True)
    document_breakdown   = serializers.ListField(child=serializers.DictField())


# ─────────────────────────────────────────────────────────────
# Generate Report Request Serializers
# ─────────────────────────────────────────────────────────────

DOCUMENT_TYPES = [
    "sales_invoice", "purchase_order", "bank_statement",
    "payroll", "expense_report", "vat_return", "fixed_asset", "sales_receipt",
]


class DocumentReportRequestSerializer(serializers.Serializer):
    """
    POST body for generating a document report.
    - If document_id is provided: single-document report.
    - If document_id is omitted/null: aggregate summary for all documents of that type.
    """
    document_id   = serializers.UUIDField(required=False, allow_null=True, default=None)
    document_type = serializers.ChoiceField(choices=DOCUMENT_TYPES)
    language      = serializers.ChoiceField(choices=["ar", "en"], default="ar")
    save          = serializers.BooleanField(default=True)


class ExecutiveReportRequestSerializer(serializers.Serializer):
    """POST body for generating an executive report."""
    date_from = serializers.DateField(required=False, allow_null=True)
    date_to   = serializers.DateField(required=False, allow_null=True)
    language  = serializers.ChoiceField(choices=["ar", "en"], default="ar")
    save      = serializers.BooleanField(default=True)
