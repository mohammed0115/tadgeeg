from rest_framework import serializers
from .models import (
    AccountMapping,
    AuditCase,
    AuditDifferenceItem,
    AuditDifferenceItemResponse,
    AuditDifferenceSummary,
    AuditEvidenceAttachment,
    AuditEvidenceRequest,
    AuditConfirmationRequest,
    AuditControlDeficiency,
    AuditEvidenceRequestEvent,
    AuditFinding,
    AuditReadinessWorkpaper,
    ProposedAuditAdjustment,
    AuditSession,
    CaseComment,
    CustomRuleDefinition,
    GeneralLedgerImport,
    GeneralLedgerRiskFinding,
    GeneralLedgerRiskFindingReview,
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


# ── TADGEEG-FIN-AUDIT-3B — GL risk-finding review trail ───────────────────────
class GeneralLedgerRiskFindingReviewSerializer(serializers.ModelSerializer):
    reviewer_email = serializers.CharField(source="reviewer.email", read_only=True, default="")

    class Meta:
        model = GeneralLedgerRiskFindingReview
        fields = [
            "id", "finding", "engagement", "organization", "from_status",
            "to_status", "reviewer", "reviewer_email", "reviewer_note",
            "review_reason", "metadata", "created_at",
        ]
        read_only_fields = fields


# ── TADGEEG-FIN-AUDIT-2B — General Ledger risk findings (candidates) ──────────
class GeneralLedgerRiskFindingSerializer(serializers.ModelSerializer):
    latest_review = serializers.SerializerMethodField()
    reviews_count = serializers.SerializerMethodField()

    def get_latest_review(self, obj):
        r = obj.reviews.first()  # ordered -created_at
        return GeneralLedgerRiskFindingReviewSerializer(r).data if r else None

    def get_reviews_count(self, obj):
        return obj.reviews.count()

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
            # TADGEEG-FIN-AUDIT-3B — review trail summary.
            "latest_review", "reviews_count",
        ]
        read_only_fields = fields


# ── TADGEEG-FIN-AUDIT-4A — Summary of Audit Differences ───────────────────────
class AuditDifferenceItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditDifferenceItem
        fields = [
            "id", "summary", "engagement", "organization", "source_type",
            "gl_finding", "account_code", "account_name", "mapped_category",
            "finding_risk_code", "finding_title", "amount_impact",
            "debit_impact", "credit_impact", "materiality_status",
            "materiality_adjusted_severity", "is_above_trivial",
            "is_above_performance_materiality", "is_above_overall_materiality",
            "management_response_status", "auditor_conclusion",
            "evidence_snapshot", "created_at",
        ]
        read_only_fields = fields


class AuditDifferenceSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditDifferenceSummary
        fields = [
            "id", "engagement", "organization", "source_scope", "status",
            "total_accepted_findings", "total_gross_misstatement",
            "total_debit_impact", "total_credit_impact", "total_absolute_impact",
            "overall_materiality", "performance_materiality", "trivial_threshold",
            "materiality_basis", "exceeds_performance_materiality",
            "exceeds_overall_materiality", "conclusion_status",
            "summary_by_category", "summary_by_account", "calculation_snapshot",
            "calculated_by", "calculated_at", "reviewed_by", "reviewed_at",
            "reviewer_note", "created_at", "updated_at",
        ]
        read_only_fields = fields


# ── TADGEEG-FIN-AUDIT-4B — Management response + proposed adjustments ──────────
class AuditDifferenceItemResponseSerializer(serializers.ModelSerializer):
    actor_email = serializers.CharField(source="actor.email", read_only=True, default="")

    class Meta:
        model = AuditDifferenceItemResponse
        fields = [
            "id", "item", "summary", "engagement", "organization",
            "from_status", "to_status", "actor", "actor_email", "response_note",
            "response_reason", "metadata", "created_at",
        ]
        read_only_fields = fields


class ProposedAuditAdjustmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProposedAuditAdjustment
        fields = [
            "id", "item", "summary", "engagement", "organization",
            "adjustment_type", "description", "debit_account_code",
            "debit_account_name", "credit_account_code", "credit_account_name",
            "amount", "currency", "management_accepted", "client_posted_reference",
            "status", "proposed_by", "proposed_at", "created_at", "updated_at",
        ]
        read_only_fields = fields


# ── TADGEEG-FIN-AUDIT-5A — Audit Readiness / Opinion Preparation Workpaper ────
class AuditReadinessWorkpaperSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditReadinessWorkpaper
        fields = [
            "id", "engagement", "organization", "sad_summary", "status",
            "readiness_conclusion", "suggested_opinion_direction",
            "total_accepted_differences", "total_unadjusted_differences",
            "total_adjusted_differences", "total_pending_management_response",
            "total_needs_evidence", "total_absolute_impact",
            "overall_materiality", "performance_materiality",
            "conclusion_basis", "unadjusted_summary",
            "management_response_summary", "proposed_adjustment_summary",
            "legal_disclaimer", "generated_by", "generated_at",
            "reviewed_by", "reviewed_at", "reviewer_note",
            "created_at", "updated_at",
        ]
        read_only_fields = fields


# ── TADGEEG-FIN-AUDIT-6A — Evidence Request workflow ─────────────────────────
class AuditEvidenceAttachmentSerializer(serializers.ModelSerializer):
    uploaded_by_name = serializers.CharField(
        source="uploaded_by.full_name", read_only=True, default="")
    # TADGEEG-FIN-AUDIT-6C — lifecycle / versioning / integrity.
    lifecycle_state_display = serializers.CharField(
        source="get_lifecycle_state_display", read_only=True)
    integrity_badge = serializers.CharField(read_only=True)
    is_expired = serializers.BooleanField(read_only=True)

    class Meta:
        model = AuditEvidenceAttachment
        fields = [
            "id", "evidence_request", "engagement", "organization",
            "uploaded_by", "uploaded_by_name", "document", "uploaded_file",
            "original_filename", "file_sha256", "content_type", "size_bytes",
            "description", "is_active", "uploaded_at",
            "lifecycle_state", "lifecycle_state_display", "lifecycle_changed_at",
            "retention_until", "version", "replaces", "notes",
            "last_verified_at", "last_verification_ok", "integrity_badge",
            "is_expired",
        ]
        read_only_fields = fields


class AuditEvidenceRequestEventSerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(
        source="actor.full_name", read_only=True, default="")
    event_type_display = serializers.CharField(
        source="get_event_type_display", read_only=True)

    class Meta:
        model = AuditEvidenceRequestEvent
        fields = [
            "id", "evidence_request", "engagement", "organization", "actor",
            "actor_name", "event_type", "event_type_display", "from_status",
            "to_status", "note", "metadata", "created_at",
        ]
        read_only_fields = fields


class AuditEvidenceRequestSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    priority_display = serializers.CharField(source="get_priority_display", read_only=True)
    request_reason_display = serializers.CharField(
        source="get_request_reason_display", read_only=True)
    requested_by_name = serializers.CharField(
        source="requested_by.full_name", read_only=True, default="")
    assigned_to_name = serializers.CharField(
        source="assigned_to.full_name", read_only=True, default="")
    assigned_client_user_name = serializers.CharField(
        source="assigned_client_user.full_name", read_only=True, default="")
    days_remaining = serializers.IntegerField(read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)
    sla_state = serializers.CharField(read_only=True)
    attachments = AuditEvidenceAttachmentSerializer(many=True, read_only=True)
    events = AuditEvidenceRequestEventSerializer(many=True, read_only=True)

    class Meta:
        model = AuditEvidenceRequest
        fields = [
            "id", "request_number", "engagement", "organization", "gl_finding",
            "sad_item", "requested_by", "requested_by_name", "assigned_to",
            "assigned_to_name", "assigned_client_user", "assigned_client_user_name",
            "title", "description", "request_reason", "request_reason_display",
            "status", "status_display", "priority", "priority_display",
            "due_date", "requested_at", "submitted_at", "reviewed_by",
            "reviewed_at", "reviewer_note", "management_explanation",
            "days_remaining", "is_overdue", "sla_state",
            "created_at", "updated_at", "attachments", "events",
        ]
        read_only_fields = fields


class AuditEvidenceRequestListSerializer(serializers.ModelSerializer):
    """Lean list serializer (no nested attachments/events)."""
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    priority_display = serializers.CharField(source="get_priority_display", read_only=True)
    requested_by_name = serializers.CharField(
        source="requested_by.full_name", read_only=True, default="")
    assigned_to_name = serializers.CharField(
        source="assigned_to.full_name", read_only=True, default="")
    assigned_client_user_name = serializers.CharField(
        source="assigned_client_user.full_name", read_only=True, default="")
    days_remaining = serializers.IntegerField(read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)
    sla_state = serializers.CharField(read_only=True)

    class Meta:
        model = AuditEvidenceRequest
        fields = [
            "id", "request_number", "engagement", "gl_finding", "sad_item",
            "title", "request_reason", "status", "status_display", "priority",
            "priority_display", "due_date", "requested_by_name",
            "assigned_to_name", "assigned_client_user_name", "requested_at",
            "days_remaining", "is_overdue", "sla_state", "created_at",
        ]
        read_only_fields = fields


# ── TADGEEG-FIN-AUDIT-9C — External Confirmations (ISA 505) ──────────────────
class AuditConfirmationRequestSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    confirmation_type_display = serializers.CharField(
        source="get_confirmation_type_display", read_only=True)
    requested_by_name = serializers.CharField(
        source="requested_by.full_name", read_only=True, default="")
    difference = serializers.SerializerMethodField()
    is_within_tolerance = serializers.SerializerMethodField()

    class Meta:
        model = AuditConfirmationRequest
        fields = [
            "id", "request_number", "engagement", "organization",
            "confirmation_type", "confirmation_type_display",
            "party_name", "party_reference", "party_email",
            "recorded_amount", "confirmed_amount", "currency", "tolerance",
            "status", "status_display", "difference", "is_within_tolerance",
            "response_note", "requested_by", "requested_by_name",
            "sent_at", "responded_at", "reviewed_at", "created_at", "updated_at",
        ]
        read_only_fields = fields

    def get_difference(self, obj):
        d = obj.difference
        return str(d) if d is not None else None

    def get_is_within_tolerance(self, obj):
        return obj.is_within_tolerance


# ── TADGEEG-FIN-AUDIT-9B — Control Deficiencies (ISA 265) ────────────────────
class AuditControlDeficiencySerializer(serializers.ModelSerializer):
    classification_display = serializers.CharField(
        source="get_classification_display", read_only=True)
    area_display = serializers.CharField(source="get_area_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    identified_by_name = serializers.CharField(
        source="identified_by.full_name", read_only=True, default="")

    class Meta:
        model = AuditControlDeficiency
        fields = [
            "id", "reference", "engagement", "organization", "title", "area",
            "area_display", "classification", "classification_display",
            "description", "potential_effect", "recommendation",
            "management_response", "management_action_owner", "target_date",
            "status", "status_display", "gl_finding", "identified_by",
            "identified_by_name", "created_at", "updated_at",
        ]
        read_only_fields = fields
