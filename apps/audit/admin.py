from django.contrib import admin

from .models import AuditCase, TrialBalanceImport, TrialBalanceRow


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
