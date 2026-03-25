from django.contrib import admin

from apps.activity_logs.models import ActivityLog


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    """Read-only admin panel for activity logs."""

    list_display = (
        "id",
        "action",
        "entity_type",
        "entity_id",
        "user",
        "organization",
        "ip_address",
        "created_at",
    )
    list_filter = ("action", "entity_type", "created_at")
    search_fields = ("user__email", "entity_id", "description", "ip_address")
    readonly_fields = (
        "id",
        "organization",
        "user",
        "action",
        "entity_type",
        "entity_id",
        "description",
        "metadata",
        "ip_address",
        "created_at",
    )
    ordering = ("-created_at",)
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
