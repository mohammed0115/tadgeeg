import csv

from django.contrib import admin, messages
from django.db.models import F, Sum
from django.http import HttpResponse
from django.utils import timezone

from apps.billing.choices import SubscriptionStatus, UsageAction
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

    actions = [
        "expire_selected_subscriptions",
        "cancel_selected_subscriptions",
        "recalculate_usage_from_ledger",
        "export_subscriptions_csv",
    ]

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

    # ─── admin actions ──────────────────────────────────────────────────────

    @admin.action(description="Expire selected subscriptions (flip status → expired)")
    def expire_selected_subscriptions(self, request, queryset):
        """Manually expire active/trialing rows. Paid/canceled/expired
        rows are skipped so this is safe to run with a broad filter."""
        affected = queryset.filter(
            status__in=(SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING),
        ).update(status=SubscriptionStatus.EXPIRED, ends_at=timezone.now())
        self.message_user(
            request,
            f"Expired {affected} subscription(s).",
            level=messages.SUCCESS if affected else messages.WARNING,
        )

    @admin.action(description="Cancel selected subscriptions")
    def cancel_selected_subscriptions(self, request, queryset):
        """Cancel any non-terminal subscription. Refunds, if any, are
        operator-handled in the payments admin separately."""
        non_terminal = queryset.exclude(
            status__in=(SubscriptionStatus.EXPIRED, SubscriptionStatus.CANCELED),
        )
        affected = non_terminal.update(status=SubscriptionStatus.CANCELED)
        self.message_user(
            request,
            f"Canceled {affected} subscription(s).",
            level=messages.SUCCESS if affected else messages.WARNING,
        )

    @admin.action(description="Recalculate used / reserved from the usage ledger")
    def recalculate_usage_from_ledger(self, request, queryset):
        """Repair drift: rewrite ``used_invoices`` / ``reserved_invoices``
        from the UsageLedger. Cheap O(N) — run this when you suspect
        the counters disagree with reality (e.g. after a manual fix).
        """
        fixed = 0
        for sub in queryset:
            agg = UsageLedger.objects.filter(
                organization=sub.organization, subscription=sub,
            ).values("action").annotate(total=Sum("quantity"))
            totals = {row["action"]: int(row["total"] or 0) for row in agg}
            consume = totals.get(UsageAction.CONSUME, 0)
            reserve = totals.get(UsageAction.RESERVE, 0)
            release = totals.get(UsageAction.RELEASE, 0)
            refund  = totals.get(UsageAction.REFUND,  0)
            # used = consumed - refunded; reserved = reserve - consume - release
            new_used     = max(0, consume - refund)
            new_reserved = max(0, reserve - consume - release)
            if sub.used_invoices != new_used or sub.reserved_invoices != new_reserved:
                sub.used_invoices     = new_used
                sub.reserved_invoices = new_reserved
                sub.save(update_fields=["used_invoices", "reserved_invoices", "updated_at"])
                fixed += 1
        self.message_user(
            request,
            f"Recalculated {fixed} subscription(s).",
            level=messages.SUCCESS if fixed else messages.INFO,
        )

    @admin.action(description="Export selected subscriptions as CSV")
    def export_subscriptions_csv(self, request, queryset):
        """Stream a CSV file with the fields ops most often need:
        org / plan / status / period / quota counters. No PII other
        than org name + id."""
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = (
            f'attachment; filename="subscriptions-{timezone.now():%Y%m%d-%H%M}.csv"'
        )
        writer = csv.writer(response)
        writer.writerow([
            "id", "organization_id", "organization", "plan",
            "status", "starts_at", "ends_at",
            "invoice_limit", "used_invoices", "reserved_invoices",
            "remaining_invoices", "auto_renew", "created_at",
        ])
        for sub in queryset.select_related("organization", "plan"):
            writer.writerow([
                sub.id, sub.organization_id, sub.organization.name,
                sub.plan.code, sub.status,
                sub.starts_at.isoformat() if sub.starts_at else "",
                sub.ends_at.isoformat() if sub.ends_at else "",
                sub.invoice_limit, sub.used_invoices, sub.reserved_invoices,
                sub.remaining_invoices, sub.auto_renew,
                sub.created_at.isoformat(),
            ])
        return response


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
