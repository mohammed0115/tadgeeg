from django.contrib import admin

from .models import Transaction


class TenantAwareModelAdmin(admin.ModelAdmin):
    """Base admin class that filters by user organization for multi-tenant isolation."""
    
    def get_queryset(self, request):
        """Filter queryset by user's organization to prevent multi-tenant data leaks."""
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(organization=request.user.organization)


@admin.register(Transaction)
class TransactionAdmin(TenantAwareModelAdmin):
    list_display = ["reference_number", "vendor_name", "transaction_type", "amount", "currency", "risk_level"]
    search_fields = ["reference_number", "vendor_name", "invoice_number", "description"]
    list_filter = ["transaction_type", "risk_level", "currency", "is_flagged", "is_duplicate"]
