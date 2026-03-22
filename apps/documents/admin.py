from django.contrib import admin

from .models import Document


class TenantAwareModelAdmin(admin.ModelAdmin):
    """Base admin class that filters by user organization for multi-tenant isolation."""
    
    def get_queryset(self, request):
        """Filter queryset by user's organization to prevent multi-tenant data leaks."""
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            # Allow superuser to see all (for support/audit), but this should be logged
            return qs
        # Regular staff users and org admins see only their organization's data
        return qs.filter(organization=request.user.organization)


@admin.register(Document)
class DocumentAdmin(TenantAwareModelAdmin):
    list_display = ["original_filename", "document_type", "processing_status", "ocr_confidence", "created_at"]
    search_fields = ["original_filename", "mime_type", "notes"]
    list_filter = ["document_type", "processing_status", "created_at"]


try:
    from .typed_models import (
        BankStatement,
        ExpenseReport,
        FixedAsset,
        PayrollSheet,
        PurchaseOrder,
        SalesReceipt,
        VATReturn,
    )

    class PurchaseOrderAdmin(TenantAwareModelAdmin):
        list_display = ["po_number", "vendor_name", "audit_status", "risk_level", "created_at"]
        search_fields = ["po_number", "vendor_name"]
        list_filter = ["audit_status", "risk_level", "created_at"]

    class BankStatementAdmin(TenantAwareModelAdmin):
        list_display = ["statement_period_from", "statement_period_to", "account_number", "audit_status", "risk_level", "created_at"]
        search_fields = ["account_number", "bank_name"]
        list_filter = ["audit_status", "risk_level", "created_at"]

    class PayrollSheetAdmin(TenantAwareModelAdmin):
        list_display = ["payroll_period_from", "payroll_period_to", "employee_count", "audit_status", "risk_level", "created_at"]
        search_fields = ["department", "company_name"]
        list_filter = ["audit_status", "risk_level", "created_at"]

    class ExpenseReportAdmin(TenantAwareModelAdmin):
        list_display = ["report_period_from", "report_period_to", "department", "audit_status", "risk_level", "created_at"]
        search_fields = ["report_number", "department"]
        list_filter = ["audit_status", "risk_level", "created_at"]

    class VATReturnAdmin(TenantAwareModelAdmin):
        list_display = ["period_from", "period_to", "filing_status", "audit_status", "risk_level", "created_at"]
        search_fields = ["vat_number", "taxpayer_name"]
        list_filter = ["filing_status", "audit_status", "risk_level", "created_at"]

    class FixedAssetAdmin(TenantAwareModelAdmin):
        list_display = ["fiscal_year", "asset_count", "total_cost", "audit_status", "risk_level", "created_at"]
        search_fields = ["fiscal_year", "company_name", "department"]
        list_filter = ["audit_status", "risk_level", "created_at"]

    class SalesReceiptAdmin(TenantAwareModelAdmin):
        list_display = ["receipt_number", "receipt_date", "audit_status", "risk_level", "created_at"]
        search_fields = ["receipt_number", "customer_name"]
        list_filter = ["audit_status", "risk_level", "created_at"]

    admin.site.register(PurchaseOrder, PurchaseOrderAdmin)
    admin.site.register(BankStatement, BankStatementAdmin)
    admin.site.register(PayrollSheet, PayrollSheetAdmin)
    admin.site.register(ExpenseReport, ExpenseReportAdmin)
    admin.site.register(VATReturn, VATReturnAdmin)
    admin.site.register(FixedAsset, FixedAssetAdmin)
    admin.site.register(SalesReceipt, SalesReceiptAdmin)
except ImportError:
    pass

try:
    from .canonical_models import (
        CanonicalFieldDefinition,
        DocumentTypeFieldMapping,
        DocumentCanonicalData,
    )

    @admin.register(CanonicalFieldDefinition)
    class CanonicalFieldDefinitionAdmin(admin.ModelAdmin):
        list_display = ["field_code", "label_en", "data_type", "field_group", "is_nullable", "is_active"]
        search_fields = ["field_code", "label_en", "label_ar"]
        list_filter = ["field_group", "data_type", "is_nullable", "is_active",
                       "required_for_storage", "required_for_rule_execution"]
        ordering = ["field_group", "sort_order"]

    @admin.register(DocumentTypeFieldMapping)
    class DocumentTypeFieldMappingAdmin(admin.ModelAdmin):
        list_display = ["document_type", "source_column", "canonical_field", "transform", "priority", "is_active"]
        search_fields = ["source_column", "source_column_ar", "canonical_field__field_code"]
        list_filter = ["document_type", "transform", "is_active"]
        ordering = ["document_type", "-priority"]

    @admin.register(DocumentCanonicalData)
    class DocumentCanonicalDataAdmin(admin.ModelAdmin):
        list_display = ["document_type", "typed_model_name", "typed_object_id", "version", "created_at"]
        search_fields = ["typed_model_name", "typed_object_id"]
        list_filter = ["document_type", "typed_model_name"]
        readonly_fields = ["raw_ai_output", "canonical_data", "extraction_confidence",
                           "extraction_source", "created_at", "updated_at"]

except ImportError:
    pass
