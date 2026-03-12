from django.contrib import admin

from .models import Transaction


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ["reference_number", "vendor_name", "transaction_type", "amount", "currency", "risk_level"]
    search_fields = ["reference_number", "vendor_name", "invoice_number", "description"]
    list_filter = ["transaction_type", "risk_level", "currency", "is_flagged", "is_duplicate"]
