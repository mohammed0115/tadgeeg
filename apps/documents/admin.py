from django.contrib import admin

from .models import Document


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
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

    admin.site.register(PurchaseOrder)
    admin.site.register(BankStatement)
    admin.site.register(PayrollSheet)
    admin.site.register(ExpenseReport)
    admin.site.register(VATReturn)
    admin.site.register(FixedAsset)
    admin.site.register(SalesReceipt)
except ImportError:
    pass
