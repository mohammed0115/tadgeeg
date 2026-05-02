from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "severity", "category", "is_read", "created_at")
    list_filter = ("severity", "category", "is_read", "created_at")
    search_fields = ("title", "message", "user__email")
    raw_id_fields = ("user", "organization")
    readonly_fields = ("id", "created_at", "read_at")
    date_hierarchy = "created_at"
