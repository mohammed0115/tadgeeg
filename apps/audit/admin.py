from django.contrib import admin

from .models import (
    AccountMapping,
    AuditCase,
    GeneralLedgerImport,
    GeneralLedgerRiskFinding,
    GeneralLedgerRiskFindingReview,
    GeneralLedgerRow,
    TrialBalanceImport,
    TrialBalanceRow,
)


class TenantAwareModelAdmin(admin.ModelAdmin):
    """Base admin class that filters by user organization for multi-tenant isolation."""
    
    def get_queryset(self, request):
        """Filter queryset by user's organization to prevent multi-tenant data leaks."""
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(organization=request.user.organization)


@admin.register(AuditCase)
class AuditCaseAdmin(TenantAwareModelAdmin):
    list_display = ["case_number", "title", "case_type", "priority", "status", "assigned_to", "created_at"]
    search_fields = ["case_number", "title", "description"]
    list_filter = ["case_type", "priority", "status", "created_at"]


# ── Trial Balance import staging (read-focused: imported client audit evidence
#    must not be silently edited from the admin). ─────────────────────────────
@admin.register(TrialBalanceImport)
class TrialBalanceImportAdmin(TenantAwareModelAdmin):
    list_display = ["id", "engagement", "status", "fiscal_year", "row_count",
                    "valid_row_count", "invalid_row_count", "is_balanced", "created_at"]
    list_filter = ["status", "is_balanced", "source_format", "fiscal_year"]
    search_fields = ["id", "original_filename", "engagement__engagement_code"]
    date_hierarchy = "created_at"
    readonly_fields = [f.name for f in TrialBalanceImport._meta.fields]

    def has_add_permission(self, request):  # imports come from the upload flow
        return False

    def has_change_permission(self, request, obj=None):  # evidence is immutable
        return False


@admin.register(TrialBalanceRow)
class TrialBalanceRowAdmin(TenantAwareModelAdmin):
    list_display = ["import_batch", "row_number", "account_code", "account_name",
                    "closing_debit", "closing_credit", "is_valid"]
    list_filter = ["is_valid", "account_type"]
    search_fields = ["account_code", "account_name"]
    readonly_fields = [f.name for f in TrialBalanceRow._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(AccountMapping)
class AccountMappingAdmin(TenantAwareModelAdmin):
    # Mapping is a classification layer (not immutable evidence): the category
    # and notes may be curated by the auditor. It never writes to the ledger.
    list_display = ["account_code", "account_name", "mapped_category",
                    "mapping_source", "confidence", "engagement", "updated_at"]
    list_filter = ["mapped_category", "mapping_source"]
    search_fields = ["account_code", "account_name"]
    readonly_fields = ["mapping_source", "confidence", "created_by", "updated_by",
                       "created_at", "updated_at"]


# ── General Ledger import staging (read-focused: imported audit evidence). ────
@admin.register(GeneralLedgerImport)
class GeneralLedgerImportAdmin(TenantAwareModelAdmin):
    list_display = ["id", "engagement", "status", "fiscal_year", "row_count",
                    "valid_row_count", "invalid_row_count", "journal_count",
                    "unbalanced_journal_count", "is_balanced", "created_at"]
    list_filter = ["status", "is_balanced", "source_format", "fiscal_year"]
    search_fields = ["id", "original_filename", "engagement__engagement_code"]
    date_hierarchy = "created_at"
    readonly_fields = [f.name for f in GeneralLedgerImport._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(GeneralLedgerRow)
class GeneralLedgerRowAdmin(TenantAwareModelAdmin):
    list_display = ["import_batch", "row_number", "journal_number", "account_code",
                    "account_name", "debit", "credit", "is_valid"]
    list_filter = ["is_valid"]
    search_fields = ["account_code", "account_name", "journal_number"]
    readonly_fields = [f.name for f in GeneralLedgerRow._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(GeneralLedgerRiskFinding)
class GeneralLedgerRiskFindingAdmin(TenantAwareModelAdmin):
    # Candidate findings are auditor-reviewed; status/reviewer notes may be
    # curated, but the machine-derived fields stay read-only. Never posts to ledger.
    list_display = ["risk_code", "risk_category", "severity", "score",
                    "account_code", "amount_impact", "status", "engagement", "created_at"]
    list_filter = ["risk_category", "severity", "status"]
    search_fields = ["risk_code", "account_code", "account_name", "journal_number"]
    readonly_fields = ["engagement", "organization", "general_ledger_import", "row",
                       "journal_number", "risk_code", "risk_title", "risk_description",
                       "risk_category", "severity", "score", "amount_impact",
                       "account_code", "account_name", "mapped_category",
                       "evidence_snapshot", "fingerprint", "created_at", "updated_at"]


@admin.register(GeneralLedgerRiskFindingReview)
class GeneralLedgerRiskFindingReviewAdmin(TenantAwareModelAdmin):
    # Immutable audit trail — strictly read-only in admin.
    list_display = ["finding", "from_status", "to_status", "review_reason",
                    "reviewer", "created_at"]
    list_filter = ["to_status", "review_reason"]
    search_fields = ["finding__id", "reviewer_note"]
    date_hierarchy = "created_at"
    readonly_fields = [f.name for f in GeneralLedgerRiskFindingReview._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
