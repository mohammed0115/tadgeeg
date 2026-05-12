from django.contrib import admin

from apps.payments.models import (
    PaymentLog,
    PaymentProviderConfig,
    PaymentTransaction,
)


class PaymentLogInline(admin.TabularInline):
    model = PaymentLog
    can_delete = False
    extra = 0
    readonly_fields = ("event_type", "status_before", "status_after", "message", "payload", "created_at")
    fields = ("event_type", "status_before", "status_after", "message", "created_at")
    ordering = ("-created_at",)


@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display  = ("id", "organization", "provider", "purpose", "amount", "currency", "status", "created_at")
    list_filter   = ("provider", "status", "purpose", "currency", "created_at")
    search_fields = ("id", "provider_payment_id", "provider_reference", "idempotency_key")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    inlines = [PaymentLogInline]

    readonly_fields = (
        "id", "organization", "user", "provider", "purpose",
        "reference_type", "reference_id", "amount", "currency", "status",
        "provider_payment_id", "provider_reference", "checkout_url",
        "success_url", "cancel_url", "failure_url",
        "raw_request", "raw_response", "raw_webhook",
        "idempotency_key", "paid_at", "failed_reason",
        "request_ip", "user_agent", "created_at", "updated_at",
    )

    def has_add_permission(self, request):
        return False  # transactions can only be created via the API


@admin.register(PaymentLog)
class PaymentLogAdmin(admin.ModelAdmin):
    list_display  = ("id", "transaction", "event_type", "status_before", "status_after", "created_at")
    list_filter   = ("event_type", "created_at")
    search_fields = ("transaction__id", "event_type", "message")
    ordering = ("-created_at",)
    readonly_fields = ("id", "transaction", "event_type", "status_before",
                       "status_after", "message", "payload", "created_at")

    def has_add_permission(self, request):
        return False


@admin.register(PaymentProviderConfig)
class PaymentProviderConfigAdmin(admin.ModelAdmin):
    list_display  = ("organization", "provider", "is_active", "updated_at")
    list_filter   = ("provider", "is_active")
    search_fields = ("organization__name", "merchant_id", "store_id")

    def get_readonly_fields(self, request, obj=None):
        # secret_key must never appear in the admin form.
        ro = ["created_at", "updated_at"]
        if obj is not None:
            ro.append("secret_key")
        return ro

    def get_fieldsets(self, request, obj=None):
        return (
            (None, {"fields": ("organization", "provider", "is_active")}),
            ("Credentials", {"fields": ("public_key", "secret_key", "merchant_id", "store_id")}),
            ("Extra",  {"fields": ("extra_config",)}),
            ("Meta",   {"fields": ("created_at", "updated_at")}),
        )
