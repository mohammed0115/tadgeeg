from django.contrib import admin

from .models import ContactLead, LeadNote


@admin.register(ContactLead)
class ContactLeadAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'email', 'company', 'source', 'status', 'assigned_to', 'is_read', 'created_at']
    list_filter = ['status', 'source', 'is_read', 'country']
    search_fields = ['full_name', 'email', 'company', 'subject']
    readonly_fields = ['id', 'created_at', 'updated_at']
    ordering = ['-created_at']

    fieldsets = (
        ('Contact Info', {
            'fields': ('id', 'full_name', 'email', 'phone', 'company', 'country'),
        }),
        ('Inquiry', {
            'fields': ('subject', 'message', 'source'),
        }),
        ('CRM', {
            'fields': ('status', 'assigned_to', 'is_read'),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
        }),
    )


@admin.register(LeadNote)
class LeadNoteAdmin(admin.ModelAdmin):
    list_display = ['lead', 'created_by', 'created_at']
    list_filter = ['created_by']
    search_fields = ['note', 'lead__full_name', 'lead__email']
    readonly_fields = ['id', 'created_at']
    ordering = ['-created_at']
