from django.contrib import admin

from .models import Invoice, InvoiceAuditEvent, InvoiceBatch, InvoiceValidationResult, VendorProfile


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ["invoice_number", "vendor_name", "invoice_date", "total_amount", "status", "risk_level"]
    search_fields = ["invoice_number", "vendor_name", "vendor_vat_number"]
    list_filter = ["status", "risk_level", "currency"]


admin.site.register(InvoiceBatch)
admin.site.register(InvoiceValidationResult)
admin.site.register(VendorProfile)
admin.site.register(InvoiceAuditEvent)
