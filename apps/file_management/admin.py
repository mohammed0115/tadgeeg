"""
Django admin configuration for the file management app.

Registers:
  - Folder          (with inline children count)
  - FileVersion     (inline under AuditFileProfile admin)
  - AuditFileProfile (inline under AuditFile — registered here to avoid
                      circular dependency with storage_management admin)
"""
from django.contrib import admin
from django.utils.html import format_html

from apps.file_management.models import AuditFileProfile, FileVersion, Folder


# ---------------------------------------------------------------------------
# Inlines
# ---------------------------------------------------------------------------

class FolderChildrenInline(admin.TabularInline):
    """Shows direct child folders nested under a parent folder."""
    model = Folder
    fk_name = "parent"
    fields = ("name", "slug", "created_by", "created_at")
    readonly_fields = ("slug", "created_at")
    extra = 0
    show_change_link = True
    verbose_name = "Child Folder"
    verbose_name_plural = "Child Folders"


class FileVersionInline(admin.TabularInline):
    """Shows all stored versions of a file (registered under FileVersionAdmin via AuditFile)."""
    model = FileVersion
    fk_name = "audit_file"
    fields = (
        "version_number",
        "storage_provider",
        "storage_path",
        "checksum",
        "file_size",
        "created_by",
        "created_at",
    )
    readonly_fields = (
        "version_number",
        "storage_path",
        "checksum",
        "file_size",
        "created_at",
    )
    extra = 0
    can_delete = False
    verbose_name = "Version"
    verbose_name_plural = "Versions"


class AuditFileProfileInline(admin.StackedInline):
    """Inline profile shown on AuditFile admin (registered via storage_management admin)."""
    model = AuditFileProfile
    fields = (
        "folder",
        "sanitized_name",
        "version_number",
        "is_archived",
        "storage_path",
        "storage_provider",
        "metadata",
    )
    readonly_fields = ("version_number", "storage_path")
    extra = 0
    can_delete = False


# ---------------------------------------------------------------------------
# ModelAdmin registrations
# ---------------------------------------------------------------------------

@admin.register(Folder)
class FolderAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "organization",
        "parent",
        "full_path_display",
        "files_count",
        "created_by",
        "created_at",
    )
    list_filter = ("organization",)
    search_fields = ("name", "slug", "organization__name")
    readonly_fields = ("id", "slug", "created_at", "updated_at", "full_path_display")
    raw_id_fields = ("parent", "created_by")
    inlines = [FolderChildrenInline]
    ordering = ("organization", "name")
    fieldsets = (
        (None, {
            "fields": ("id", "organization", "parent", "name", "slug", "full_path_display"),
        }),
        ("Audit", {
            "fields": ("created_by", "created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    @admin.display(description="Full Path")
    def full_path_display(self, obj: Folder) -> str:
        return obj.get_full_path()

    @admin.display(description="Files")
    def files_count(self, obj: Folder) -> int:
        return obj.files.count()


@admin.register(FileVersion)
class FileVersionAdmin(admin.ModelAdmin):
    list_display = (
        "audit_file",
        "version_number",
        "storage_provider",
        "checksum_short",
        "file_size_display",
        "created_by",
        "created_at",
    )
    list_filter = ("storage_provider", "created_at")
    search_fields = (
        "audit_file__original_name",
        "checksum",
        "audit_file__organization__name",
    )
    readonly_fields = (
        "id",
        "audit_file",
        "version_number",
        "storage_path",
        "checksum",
        "file_size",
        "created_at",
    )
    raw_id_fields = ("created_by",)
    ordering = ("-created_at",)
    fieldsets = (
        (None, {
            "fields": ("id", "audit_file", "version_number"),
        }),
        ("Storage", {
            "fields": ("storage_provider", "storage_path", "checksum", "file_size"),
        }),
        ("Audit", {
            "fields": ("created_by", "created_at"),
            "classes": ("collapse",),
        }),
    )

    @admin.display(description="Checksum")
    def checksum_short(self, obj: FileVersion) -> str:
        return obj.checksum[:12] + "…" if obj.checksum else "—"

    @admin.display(description="Size")
    def file_size_display(self, obj: FileVersion) -> str:
        size = obj.file_size
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"


@admin.register(AuditFileProfile)
class AuditFileProfileAdmin(admin.ModelAdmin):
    list_display = (
        "audit_file",
        "folder",
        "version_number",
        "is_archived",
        "storage_provider",
        "sanitized_name",
    )
    list_filter = ("is_archived", "storage_provider", "folder__organization")
    search_fields = (
        "audit_file__original_name",
        "sanitized_name",
        "audit_file__organization__name",
    )
    readonly_fields = ("audit_file", "version_number", "storage_path")
    raw_id_fields = ("folder", "storage_provider")
    fieldsets = (
        (None, {
            "fields": ("audit_file", "folder", "sanitized_name"),
        }),
        ("Version & Storage", {
            "fields": ("version_number", "storage_path", "storage_provider"),
        }),
        ("State", {
            "fields": ("is_archived", "metadata"),
        }),
    )
