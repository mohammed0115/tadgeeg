from django.conf import settings
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import AuditLog, Organization, OrganizationSettings, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ["email"]
    list_display = ["email", "full_name", "organization", "role", "is_active", "is_staff"]
    list_filter = ["role", "is_active", "is_staff", "organization"]
    search_fields = ["email", "full_name", "phone"]
    readonly_fields = ["id", "last_login", "created_at", "updated_at"]
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Profile", {"fields": ("full_name", "phone", "department", "organization", "role")}),
        ("Security", {"fields": ("mfa_enabled", "mfa_secret", "failed_login_attempts", "locked_until", "last_login_ip")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Timestamps", {"fields": ("last_login", "created_at", "updated_at")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "full_name", "password1", "password2", "organization", "role")}),
    )

    def get_queryset(self, request):
        """Filter users by organization for non-superusers."""
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        # Staff users can only see users in their organization
        return qs.filter(organization=request.user.organization)


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ["name", "country", "currency", "vat_number", "is_active"]
    search_fields = ["name", "name_ar", "vat_number", "cr_number"]
    list_filter = ["country", "currency", "is_active"]


@admin.register(OrganizationSettings)
class OrganizationSettingsAdmin(admin.ModelAdmin):
    list_display = ["organization", "updated_at"]
    search_fields = ["organization__name", "organization__vat_number"]

    def get_queryset(self, request):
        """Filter organization settings by user's organization."""
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(organization=request.user.organization)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ["action", "user", "organization", "resource_type", "timestamp"]
    list_filter = ["action", "organization", "timestamp"]
    search_fields = ["resource_type", "resource_id", "user__email", "organization__name"]
    readonly_fields = ["timestamp"]

    def get_queryset(self, request):
        """Filter audit logs by organization for non-superusers."""
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        # Staff users can only see audit logs from their organization
        return qs.filter(organization=request.user.organization)


admin.site.site_header = f"{settings.PRODUCT_NAME} — من تطوير {settings.COMPANY_NAME_AR}"
admin.site.site_title = f"{settings.PRODUCT_NAME} Admin"
admin.site.index_title = "لوحة إدارة النظام"
