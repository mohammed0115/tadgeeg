from django.contrib import admin


class TenantAwareModelAdmin(admin.ModelAdmin):
    """Base admin class that filters by user organization for multi-tenant isolation."""
    
    def get_queryset(self, request):
        """Filter queryset by user's organization to prevent multi-tenant data leaks."""
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(organization=request.user.organization)


try:
    from .models import ComplianceRule, ComplianceViolation

    @admin.register(ComplianceRule)
    class ComplianceRuleAdmin(TenantAwareModelAdmin):
        list_display = ["name", "organization", "standard", "is_active", "created_at"]
        search_fields = ["name", "description"]
        list_filter = ["standard", "is_active", "created_at"]

    @admin.register(ComplianceViolation)
    class ComplianceViolationAdmin(TenantAwareModelAdmin):
        list_display = ["organization", "standard", "severity", "is_resolved", "created_at"]
        search_fields = ["rule_description", "description"]
        list_filter = ["standard", "severity", "is_resolved", "created_at"]

except ImportError:
    pass
