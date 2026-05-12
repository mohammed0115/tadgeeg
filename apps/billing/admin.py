from django.contrib import admin

from apps.billing.models import (
    OrganizationSubscription,
    Plan,
    UsageLedger,
)


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display  = ("code", "name_en", "invoice_limit", "price", "currency",
                     "duration_days", "is_free", "is_trial", "is_active", "sort_order")
    list_filter   = ("is_active", "is_free", "is_trial")
    search_fields = ("code", "name_ar", "name_en")
    ordering = ("sort_order", "price")


@admin.register(OrganizationSubscription)
class OrganizationSubscriptionAdmin(admin.ModelAdmin):
    list_display  = ("organization", "plan", "status",
                     "invoice_limit", "used_invoices", "reserved_invoices",
                     "remaining_invoices", "starts_at", "ends_at", "auto_renew")
    list_filter   = ("status", "plan", "auto_renew")
    search_fields = ("organization__name", "organization__id",
                     "plan__code", "payment_transaction")
    date_hierarchy = "created_at"
    readonly_fields = ("id", "created_at", "updated_at", "remaining_invoices")
    ordering = ("-created_at",)

    fieldsets = (
        (None, {"fields": ("id", "organization", "plan", "status")}),
        ("Period",  {"fields": ("starts_at", "ends_at", "auto_renew")}),
        ("Quota",   {"fields": ("invoice_limit", "used_invoices",
                                "reserved_invoices", "remaining_invoices")}),
        ("Payment", {"fields": ("payment_transaction",)}),
        ("Meta",    {"fields": ("created_at", "updated_at")}),
    )

    @admin.display(description="Remaining")
    def remaining_invoices(self, obj):
        return obj.remaining_invoices


@admin.register(UsageLedger)
class UsageLedgerAdmin(admin.ModelAdmin):
    list_display  = ("organization", "subscription", "action", "quantity",
                     "document", "audit_run", "reason", "created_at")
    list_filter   = ("action",)
    search_fields = ("organization__name", "organization__id", "reason")
    date_hierarchy = "created_at"
    readonly_fields = ("id", "organization", "subscription", "document",
                       "audit_run", "action", "quantity", "reason",
                       "metadata", "created_at")
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False  # ledger is written only by QuotaService
