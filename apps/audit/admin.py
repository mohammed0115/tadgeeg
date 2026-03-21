from django.contrib import admin

from .models import AuditCase


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
