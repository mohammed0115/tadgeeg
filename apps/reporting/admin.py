from django.contrib import admin

from apps.reporting.models import Report, ReportItem


class ReportItemInline(admin.TabularInline):
    model = ReportItem
    extra = 0
    readonly_fields = ("id", "audit_result_id", "metadata", "created_at")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "report_type",
        "title",
        "organization",
        "generated_by",
        "status",
        "created_at",
    )
    list_filter = ("report_type", "status", "created_at")
    search_fields = ("title", "generated_by__email", "organization__name")
    readonly_fields = (
        "id",
        "organization",
        "report_type",
        "title",
        "generated_by",
        "related_audit_job",
        "status",
        "file_path",
        "report_data",
        "error_message",
        "created_at",
        "updated_at",
    )
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    inlines = [ReportItemInline]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ReportItem)
class ReportItemAdmin(admin.ModelAdmin):
    list_display = ("id", "report", "audit_result_id", "created_at")
    readonly_fields = ("id", "report", "audit_result_id", "metadata", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
