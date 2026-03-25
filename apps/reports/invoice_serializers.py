"""
DRF Serializers / DTOs for the Invoice Audit Report.

Serializer taxonomy:
  - Model serializers    : ReportSerializer (existing, unchanged)
  - Computed serializers : everything below — validate outbound API shape

These are OUTPUT-ONLY (read/response) serializers.
They document and enforce the JSON contract for every section.
"""

from rest_framework import serializers


# ─────────────────────────────────────────────────────────────────────────────
# Primitives
# ─────────────────────────────────────────────────────────────────────────────

class ReportHeaderSerializer(serializers.Serializer):
    report_id        = serializers.UUIDField(allow_null=True)
    title            = serializers.CharField()
    organization_name = serializers.CharField()
    organization_id  = serializers.UUIDField()
    created_at       = serializers.DateTimeField()
    created_by       = serializers.CharField(allow_null=True)
    report_type      = serializers.CharField()
    language         = serializers.CharField()
    period_from      = serializers.DateField(allow_null=True)
    period_to        = serializers.DateField(allow_null=True)
    overall_status   = serializers.CharField()
    overall_status_ar = serializers.CharField()


class InvoiceAuditSummarySerializer(serializers.Serializer):
    total_invoices       = serializers.IntegerField()
    total_amount         = serializers.FloatField()
    currency             = serializers.CharField()
    compliance_score     = serializers.FloatField()
    average_risk_score   = serializers.FloatField()
    risk_level           = serializers.CharField()
    risk_level_ar        = serializers.CharField()
    risk_level_en        = serializers.CharField()
    duplicate_count      = serializers.IntegerField()
    high_risk_count      = serializers.IntegerField()
    flagged_count        = serializers.IntegerField()
    validated_count      = serializers.IntegerField()
    not_validated_count  = serializers.IntegerField()


class KeyFindingSerializer(serializers.Serializer):
    code      = serializers.CharField()
    severity  = serializers.CharField()
    title_ar  = serializers.CharField()
    title_en  = serializers.CharField()


class ExecutiveSummarySerializer(serializers.Serializer):
    conclusion       = serializers.CharField()
    compliance_score = serializers.FloatField()
    risk_level       = serializers.CharField()
    risk_level_ar    = serializers.CharField()
    risk_level_en    = serializers.CharField()
    key_findings     = KeyFindingSerializer(many=True)


class ComplianceCategorySerializer(serializers.Serializer):
    passed     = serializers.IntegerField()
    failed     = serializers.IntegerField()
    score      = serializers.FloatField()
    rule_count = serializers.IntegerField()


class ComplianceEngineSerializer(serializers.Serializer):
    total_rules   = serializers.IntegerField()
    total_checks  = serializers.IntegerField()
    passed_rules  = serializers.IntegerField()
    failed_rules  = serializers.IntegerField()
    overall_score = serializers.FloatField()
    by_category   = serializers.DictField(child=ComplianceCategorySerializer())


class ViolationSerializer(serializers.Serializer):
    rule_code = serializers.CharField()
    title_ar  = serializers.CharField()
    title_en  = serializers.CharField()
    category  = serializers.CharField()
    severity  = serializers.CharField()
    weight    = serializers.IntegerField()


class HighRiskInvoiceSerializer(serializers.Serializer):
    """
    Computed (not model) serializer.
    Returned by high_risk_invoices section and the /high-risk/ sub-endpoint.
    """
    id               = serializers.UUIDField()
    invoice_number   = serializers.CharField()
    supplier_name    = serializers.CharField()
    invoice_date     = serializers.DateField(allow_null=True)
    amount           = serializers.FloatField()
    currency         = serializers.CharField()
    risk_level       = serializers.CharField()
    risk_score       = serializers.FloatField()
    compliance_score = serializers.FloatField(allow_null=True)
    is_duplicate     = serializers.BooleanField()
    is_flagged       = serializers.BooleanField()
    violations       = ViolationSerializer(many=True)
    violation_count  = serializers.IntegerField()


class FailedRuleSerializer(serializers.Serializer):
    """
    Computed serializer — one row per failed rule, aggregated across all invoices.
    Returned by failed_rules_analysis section and the /failed-rules/ sub-endpoint.
    """
    rule_code       = serializers.CharField()
    title_ar        = serializers.CharField()
    title_en        = serializers.CharField()
    category        = serializers.CharField()
    severity        = serializers.CharField()
    weight          = serializers.IntegerField()
    failure_count   = serializers.IntegerField()
    failure_rate    = serializers.FloatField()
    invoice_numbers = serializers.ListField(child=serializers.CharField())


class SupplierSummarySerializer(serializers.Serializer):
    """
    Computed serializer — aggregated per vendor_name.
    Returned by supplier_analysis section and the /supplier-analysis/ sub-endpoint.
    """
    supplier_name        = serializers.CharField()
    invoice_count        = serializers.IntegerField()
    total_spend          = serializers.FloatField()
    average_invoice      = serializers.FloatField()
    spend_share_percent  = serializers.FloatField()
    flagged_count        = serializers.IntegerField()
    duplicate_count      = serializers.IntegerField()
    risk_tier            = serializers.CharField()
    is_new_vendor        = serializers.BooleanField()
    is_suspicious        = serializers.BooleanField()


class RiskAnalysisSerializer(serializers.Serializer):
    safe_count           = serializers.IntegerField()
    review_count         = serializers.IntegerField()
    high_risk_count      = serializers.IntegerField()
    safe_pct             = serializers.FloatField()
    review_pct           = serializers.FloatField()
    high_risk_pct        = serializers.FloatField()
    average_risk_score   = serializers.FloatField()
    thresholds           = serializers.DictField()


class RecommendationSerializer(serializers.Serializer):
    priority  = serializers.CharField()
    code      = serializers.CharField()
    action_ar = serializers.CharField()
    action_en = serializers.CharField()


class ActionsSerializer(serializers.Serializer):
    immediate_actions  = RecommendationSerializer(many=True)
    future_improvements = RecommendationSerializer(many=True)


# ─────────────────────────────────────────────────────────────────────────────
# Root serializer — complete invoice audit report
# ─────────────────────────────────────────────────────────────────────────────

class InvoiceAuditReportSerializer(serializers.Serializer):
    """
    Full invoice audit report.
    All sections are computed (no model FK) — this is a DTO/response serializer.

    JSON sections:
        report_header               → ReportHeaderSerializer
        summary                     → InvoiceAuditSummarySerializer
        executive_summary           → ExecutiveSummarySerializer
        compliance_engine           → ComplianceEngineSerializer
        high_risk_invoices          → HighRiskInvoiceSerializer (list)
        failed_rules_analysis       → FailedRuleSerializer (list)
        supplier_analysis           → SupplierSummarySerializer (list)
        risk_analysis               → RiskAnalysisSerializer
        anomalies                   → dict (free-form)
        actions_and_recommendations → ActionsSerializer
    """
    report_header               = ReportHeaderSerializer()
    summary                     = InvoiceAuditSummarySerializer()
    executive_summary           = ExecutiveSummarySerializer()
    compliance_engine           = ComplianceEngineSerializer()
    high_risk_invoices          = HighRiskInvoiceSerializer(many=True)
    failed_rules_analysis       = FailedRuleSerializer(many=True)
    supplier_analysis           = SupplierSummarySerializer(many=True)
    risk_analysis               = RiskAnalysisSerializer()
    anomalies                   = serializers.DictField()
    actions_and_recommendations = ActionsSerializer()


# ─────────────────────────────────────────────────────────────────────────────
# Request serializer
# ─────────────────────────────────────────────────────────────────────────────

class InvoiceAuditReportRequestSerializer(serializers.Serializer):
    """POST body for generating an invoice audit report."""
    date_from  = serializers.DateField(required=False, allow_null=True)
    date_to    = serializers.DateField(required=False, allow_null=True)
    language   = serializers.ChoiceField(choices=["ar", "en"], default="ar")
    save       = serializers.BooleanField(default=True)
    use_async  = serializers.BooleanField(default=False)
