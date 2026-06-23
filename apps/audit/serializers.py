from rest_framework import serializers
from .models import (
    AccountMapping,
    AuditCase,
    AuditFinding,
    AuditSession,
    CaseComment,
    CustomRuleDefinition,
    GeneralLedgerImport,
    GeneralLedgerRiskFinding,
    GeneralLedgerRow,
    TrialBalanceImport,
    TrialBalanceRow,
)

class CaseCommentSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source="author.full_name", read_only=True)
    class Meta:
        model = CaseComment
        fields = ["id", "case", "author", "author_name", "text", "is_internal", "created_at"]
        read_only_fields = ["id", "author", "created_at"]

class AuditCaseSerializer(serializers.ModelSerializer):
    comments = CaseCommentSerializer(many=True, read_only=True)
    assigned_to_name = serializers.CharField(source="assigned_to.full_name", read_only=True)
    invoice_number = serializers.CharField(source="invoice.invoice_number", read_only=True)

    class Meta:
        model = AuditCase
        fields = "__all__"
        read_only_fields = ["id", "case_number", "organization", "created_at", "updated_at"]


class AuditSessionSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source="created_by.full_name", read_only=True, default="")
    progress_percent = serializers.FloatField(read_only=True)

    class Meta:
        model = AuditSession
        fields = [
            "id",
            "name",
            "status",
            "total_count",
            "processed_count",
            "success_count",
            "failed_count",
            "review_required_count",
            "duplicate_count",
            "high_risk_count",
            "average_risk_score",
            "max_risk_score",
            "last_error",
            "context",
            "started_at",
            "completed_at",
            "failed_at",
            "created_at",
            "updated_at",
            "created_by_name",
            "progress_percent",
        ]


class AuditFindingSerializer(serializers.ModelSerializer):
    invoice_number = serializers.CharField(source="invoice.invoice_number", read_only=True, default="")
    vendor_name = serializers.CharField(source="invoice.vendor_name", read_only=True, default="")

    class Meta:
        model = AuditFinding
        fields = [
            "id",
            "audit_session",
            "invoice",
            "invoice_number",
            "vendor_name",
            "rule_code",
            "rule_name",
            "rule_group",
            "severity",
            "status",
            "message",
            "details",
            "source",
            "first_detected_at",
            "last_detected_at",
            "resolved_at",
        ]


class CustomRuleDefinitionSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source="created_by.full_name", read_only=True, default="")

    class Meta:
        model = CustomRuleDefinition
        fields = [
            "id", "name", "description", "standard", "severity",
            "condition_type", "condition_params", "remediation_suggestion",
            "is_active", "version", "created_by", "created_by_name",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "version", "created_by", "created_at", "updated_at"]



# ── TADGEEG-FIN-AUDIT-1B — Trial Balance upload + Account Mapping ──────────────
class TrialBalanceRowSerializer(serializers.ModelSerializer):
    class Meta:
        model = TrialBalanceRow
        fields = [
            "id", "row_number", "account_code", "account_name", "account_type",
            "opening_debit", "opening_credit", "period_debit", "period_credit",
            "closing_debit", "closing_credit", "net_movement", "closing_balance",
            "currency", "is_valid", "validation_errors",
        ]
        read_only_fields = fields


class TrialBalanceImportSerializer(serializers.ModelSerializer):
    """Detail/summary view of one staged import."""
    invalid_rows_sample = serializers.SerializerMethodField()

    class Meta:
        model = TrialBalanceImport
        fields = [
            "id", "engagement", "organization", "original_filename",
            "source_format", "file_sha256", "period_start", "period_end",
            "fiscal_year", "currency", "status", "row_count", "valid_row_count",
            "invalid_row_count", "total_debit", "total_credit", "difference",
            "is_balanced", "column_mapping", "validation_summary", "errors",
            "warnings", "created_by", "created_at", "updated_at", "validated_at",
            "archived_at", "invalid_rows_sample",
        ]
        read_only_fields = fields

    def get_invalid_rows_sample(self, obj):
        rows = obj.rows.filter(is_valid=False)[:20]
        return TrialBalanceRowSerializer(rows, many=True).data


class AccountMappingSerializer(serializers.ModelSerializer):
    class Meta:
        model = AccountMapping
        fields = [
            "id", "engagement", "organization", "account_code", "account_name",
            "mapped_category", "mapped_ledger_account", "mapping_source",
            "confidence", "notes", "created_by", "updated_by",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "organization", "mapping_source", "confidence",
            "created_by", "updated_by", "created_at", "updated_at",
        ]


# ── TADGEEG-FIN-AUDIT-2A — General Ledger import staging ──────────────────────
class GeneralLedgerRowSerializer(serializers.ModelSerializer):
    class Meta:
        model = GeneralLedgerRow
        fields = [
            "id", "row_number", "journal_number", "line_number",
            "transaction_date", "posting_date", "account_code", "account_name",
            "mapped_account", "debit", "credit", "signed_amount", "currency",
            "description", "document_number", "reference", "counterparty",
            "cost_center", "department", "entered_by", "source_system",
            "is_valid", "validation_errors",
        ]
        read_only_fields = fields


class GeneralLedgerImportSerializer(serializers.ModelSerializer):
    """Detail/summary view of one staged GL import."""
    invalid_rows_sample = serializers.SerializerMethodField()

    class Meta:
        model = GeneralLedgerImport
        fields = [
            "id", "engagement", "organization", "related_trial_balance_import",
            "original_filename", "source_format", "file_sha256",
            "period_start", "period_end", "fiscal_year", "currency", "status",
            "row_count", "valid_row_count", "invalid_row_count", "journal_count",
            "balanced_journal_count", "unbalanced_journal_count",
            "total_debit", "total_credit", "difference", "is_balanced",
            "column_mapping", "validation_summary", "errors", "warnings",
            "created_by", "created_at", "updated_at", "validated_at",
            "archived_at", "invalid_rows_sample",
        ]
        read_only_fields = fields

    def get_invalid_rows_sample(self, obj):
        rows = obj.rows.filter(is_valid=False)[:20]
        return GeneralLedgerRowSerializer(rows, many=True).data


# ── TADGEEG-FIN-AUDIT-2B — General Ledger risk findings (candidates) ──────────
class GeneralLedgerRiskFindingSerializer(serializers.ModelSerializer):
    class Meta:
        model = GeneralLedgerRiskFinding
        fields = [
            "id", "engagement", "organization", "general_ledger_import", "row",
            "journal_number", "risk_code", "risk_title", "risk_description",
            "risk_category", "severity", "score", "amount_impact",
            "account_code", "account_name", "mapped_category",
            "evidence_snapshot", "fingerprint", "status", "reviewed_by",
            "reviewed_at", "reviewer_note", "created_at", "updated_at",
            # TADGEEG-FIN-AUDIT-3A — materiality overlay (separate from original).
            "materiality_status", "materiality_basis", "materiality_overall",
            "materiality_performance", "materiality_trivial_threshold",
            "amount_to_overall_materiality_ratio",
            "amount_to_performance_materiality_ratio",
            "materiality_adjusted_score", "materiality_adjusted_severity",
            "materiality_assessed_at", "materiality_snapshot",
        ]
        read_only_fields = fields
