from django.contrib import admin

from .models import Invoice, InvoiceAuditEvent, InvoiceBatch, InvoiceValidationResult, VendorProfile


class TenantAwareModelAdmin(admin.ModelAdmin):
    """Base admin class that filters by user organization for multi-tenant isolation."""
    
    def get_queryset(self, request):
        """Filter queryset by user's organization to prevent multi-tenant data leaks."""
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            # Allow superuser to see all (for support/audit)
            return qs
        org = getattr(request.user, "organization", None)
        if not org:
            return qs.none()

        # Direct tenant ownership
        if any(f.name == "organization" for f in qs.model._meta.fields):
            return qs.filter(organization=org)

        # Indirect tenant ownership through invoice FK
        if any(f.name == "invoice" for f in qs.model._meta.fields):
            return qs.filter(invoice__organization=org)

        return qs.none()


@admin.register(Invoice)
class InvoiceAdmin(TenantAwareModelAdmin):
    list_display = ["invoice_number", "vendor_name", "invoice_date", "total_amount", "status", "risk_level"]
    search_fields = ["invoice_number", "vendor_name", "vendor_vat_number"]
    list_filter = ["status", "risk_level", "currency"]


@admin.register(InvoiceBatch)
class InvoiceBatchAdmin(TenantAwareModelAdmin):
    list_display = ["batch_name", "total_files", "processed_files", "failed_files", "status", "created_at"]
    search_fields = ["batch_name"]
    list_filter = ["status", "created_at"]


@admin.register(InvoiceValidationResult)
class InvoiceValidationResultAdmin(TenantAwareModelAdmin):
    list_display = ["invoice", "validation_score", "rules_failed", "validated_at"]
    search_fields = ["invoice__invoice_number"]
    list_filter = ["validated_at"]


@admin.register(VendorProfile)
class VendorProfileAdmin(TenantAwareModelAdmin):
    list_display = ["vendor_name", "vendor_vat_number", "risk_tier", "updated_at"]
    search_fields = ["vendor_name", "vendor_vat_number"]
    list_filter = ["risk_tier", "updated_at"]


@admin.register(InvoiceAuditEvent)
class InvoiceAuditEventAdmin(TenantAwareModelAdmin):
    list_display = ["invoice", "event_type", "timestamp"]
    search_fields = ["invoice__invoice_number", "event_type"]
    list_filter = ["event_type", "timestamp"]
    readonly_fields = ["timestamp"]
