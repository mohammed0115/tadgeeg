from django.contrib import admin

from .models import AuditCase


@admin.register(AuditCase)
class AuditCaseAdmin(admin.ModelAdmin):
    list_display = ["case_number", "title", "case_type", "priority", "status", "assigned_to", "created_at"]
    search_fields = ["case_number", "title", "description"]
    list_filter = ["case_type", "priority", "status", "created_at"]
