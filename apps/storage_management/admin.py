"""
Django admin registrations for storage management models.
"""
from django.contrib import admin
from django.utils.html import format_html

from apps.storage_management.models import (
    AuditFile,
    FileStorageMapping,
    OrganizationStoragePolicy,
    StorageActivityLog,
    StorageConfig,
    StoragePolicy,
    StorageProvider,
)


@admin.register(StorageProvider)
class StorageProviderAdmin(admin.ModelAdmin):
    list_display = ["name", "provider_type", "is_active", "is_default", "created_at"]
    list_filter = ["provider_type", "is_active", "is_default"]
    search_fields = ["name", "description"]
    readonly_fields = ["id", "created_at", "updated_at"]
    fieldsets = (
        (None, {"fields": ("id", "name", "provider_type", "description")}),
        ("Status", {"fields": ("is_active", "is_default")}),
        ("Timestamps", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )


@admin.register(StorageConfig)
class StorageConfigAdmin(admin.ModelAdmin):
    list_display = ["provider", "organization", "bucket_name", "region", "use_ssl", "updated_at"]
    list_filter = ["use_ssl", "provider__provider_type"]
    search_fields = ["provider__name", "bucket_name", "organization__name"]
    readonly_fields = ["id", "created_at", "updated_at"]
    fieldsets = (
        (None, {"fields": ("id", "provider", "organization")}),
        (
            "Connection",
            {
                "fields": (
                    "bucket_name",
                    "region",
                    "endpoint_url",
                    "base_path",
                    "use_ssl",
                )
            },
        ),
        (
            "Credentials (Encrypted)",
            {
                "fields": ("access_key_encrypted", "secret_key_encrypted"),
                "classes": ("collapse",),
                "description": "Values are stored encrypted. Do not paste raw credentials here — use the API.",
            },
        ),
        ("Extra Settings", {"fields": ("extra_settings",), "classes": ("collapse",)}),
        ("Timestamps", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )


@admin.register(OrganizationStoragePolicy)
class OrganizationStoragePolicyAdmin(admin.ModelAdmin):
    list_display = [
        "organization",
        "primary_storage",
        "backup_storage",
        "archive_storage",
        "temp_storage",
        "updated_at",
    ]
    search_fields = ["organization__name"]
    autocomplete_fields = ["organization", "primary_storage"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(StoragePolicy)
class StoragePolicyAdmin(admin.ModelAdmin):
    list_display = [
        "organization",
        "max_file_size_mb",
        "retention_days",
        "require_encryption",
        "antivirus_scan_enabled",
        "updated_at",
    ]
    list_filter = ["require_encryption", "require_signed_urls", "antivirus_scan_enabled"]
    search_fields = ["organization__name"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(AuditFile)
class AuditFileAdmin(admin.ModelAdmin):
    list_display = [
        "original_name",
        "organization",
        "uploaded_by",
        "file_type",
        "file_size_display",
        "status",
        "created_at",
    ]
    list_filter = ["status", "file_type", "organization"]
    search_fields = ["original_name", "checksum", "organization__name"]
    readonly_fields = ["id", "checksum", "created_at", "updated_at", "file_size_display"]
    date_hierarchy = "created_at"

    def file_size_display(self, obj):
        return obj.file_size_display

    file_size_display.short_description = "Size"


@admin.register(FileStorageMapping)
class FileStorageMappingAdmin(admin.ModelAdmin):
    list_display = [
        "file",
        "storage_provider",
        "storage_bucket",
        "version_number",
        "created_at",
    ]
    list_filter = ["storage_provider"]
    search_fields = ["file__original_name", "storage_path", "checksum"]
    readonly_fields = ["id", "created_at"]


@admin.register(StorageActivityLog)
class StorageActivityLogAdmin(admin.ModelAdmin):
    list_display = [
        "action",
        "entity_type",
        "user",
        "organization",
        "success",
        "created_at",
    ]
    list_filter = ["action", "success", "entity_type"]
    search_fields = ["user__email", "organization__name", "entity_id", "error_message"]
    readonly_fields = ["id", "created_at"]
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
