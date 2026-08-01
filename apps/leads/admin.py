from django.contrib import admin

from .models import ContactLead, LeadNote, TrialLeadProfile


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


@admin.register(TrialLeadProfile)
class TrialLeadProfileAdmin(admin.ModelAdmin):
    list_display = [
        'user', 'country', 'primary_benefit', 'company_name',
        'heard_about', 'created_at',
    ]
    list_filter = ['country', 'primary_benefit', 'heard_about', 'employee_count']
    search_fields = ['user__email', 'user__full_name', 'company_name', 'city', 'sector']
    ordering = ['-created_at']

    # The auto-captured block is observed, not authored. Making it editable
    # would let staff rewrite attribution and IP evidence; there is no
    # legitimate reason to correct these by hand.
    readonly_fields = [
        'id', 'user', 'registered_ip', 'device_type', 'language',
        'referral_source', 'campaign_source', 'created_at', 'updated_at',
    ]

    fieldsets = (
        ('Identity', {
            'fields': ('id', 'user'),
        }),
        ('Contact', {
            'fields': ('country', 'city', 'company_name'),
        }),
        ('Intent & segmentation', {
            'fields': ('primary_benefit', 'employee_count', 'sector', 'heard_about'),
        }),
        ('Auto-captured (personal data — see docs/adr/0004-lead-metadata-privacy.md)', {
            'fields': (
                'registered_ip', 'device_type', 'language',
                'referral_source', 'campaign_source',
            ),
            'description': (
                'Captured at registration for fraud/abuse triage and acquisition '
                'reporting. Django admin is staff-only; do not surface these on any '
                'customer-facing view.'
            ),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
        }),
    )
