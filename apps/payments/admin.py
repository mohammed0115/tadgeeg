from django.contrib import admin, messages
from django.test.client import RequestFactory
from django.utils import timezone

from apps.payments.models import (
    FailedWebhookEvent,
    PaymentLog,
    PaymentTransaction,
)
from apps.payments.services.webhook_service import process_webhook


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


@admin.register(FailedWebhookEvent)
class FailedWebhookEventAdmin(admin.ModelAdmin):
    list_display  = ("id", "provider", "reason", "replayed", "created_at")
    list_filter   = ("provider", "reason", "replayed")
    search_fields = ("message", "id")
    ordering = ("-created_at",)
    readonly_fields = ("id", "provider", "reason", "message", "headers",
                       "remote_ip", "user_agent", "replayed", "replayed_at",
                       "created_at")
    actions = ["replay_selected"]

    def has_add_permission(self, request):
        return False

    @admin.action(description="Replay selected webhooks through process_webhook")
    def replay_selected(self, request, queryset):
        ok = err = 0
        factory = RequestFactory()
        for evt in queryset.filter(replayed=False):
            content_type = (evt.headers or {}).get("CONTENT_TYPE", "application/json")
            replay_request = factory.post(
                f"/api/v1/payments/webhooks/{evt.provider}/",
                data=bytes(evt.body or b""),
                content_type=content_type,
            )
            # Restore the headers the adapter relies on for signature verify.
            for header_name, value in (evt.headers or {}).items():
                if header_name.startswith("HTTP_"):
                    replay_request.META[header_name] = value
            try:
                code, _ = process_webhook(evt.provider, replay_request)
            except Exception as exc:  # noqa: BLE001
                err += 1
                self.message_user(request, f"{evt.id}: {exc}", level=messages.ERROR)
                continue
            if code == "ok":
                evt.replayed = True
                evt.replayed_at = timezone.now()
                evt.save(update_fields=["replayed", "replayed_at"])
                ok += 1
            else:
                err += 1
        self.message_user(
            request,
            f"Replayed {ok} successfully, {err} still failing.",
            level=messages.SUCCESS if not err else messages.WARNING,
        )


# Removed in Stage-9 cleanup (QA report M-3): PaymentProviderConfigAdmin
# was dropped along with its model. Re-add both together if per-tenant
# provider overrides land.
