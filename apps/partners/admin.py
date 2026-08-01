from django.contrib import admin

from .models import Partner


@admin.register(Partner)
class PartnerAdmin(admin.ModelAdmin):
    list_display = [
        "company_name", "partner_type", "partner_tier", "status",
        "country", "display_order", "published_at",
    ]
    list_filter = ["status", "partner_tier", "partner_type", "country"]
    search_fields = ["company_name", "slug", "short_description"]
    prepopulated_fields = {"slug": ("company_name",)}
    ordering = ["display_order", "company_name"]
    readonly_fields = ["id", "created_at", "updated_at", "published_at"]

    fieldsets = (
        ("Identity", {"fields": ("id", "company_name", "slug")}),
        ("Public content", {
            "fields": ("logo", "country", "short_description", "long_description", "website"),
            "description": "These fields ARE served publicly once status = Published.",
        }),
        ("Classification", {
            "fields": ("partner_type", "partner_tier", "status", "display_order"),
            "description": (
                "Type, tier and status are independent (spec §C.2). The public page "
                "groups by tier, plus one section keyed on type=Distributor."
            ),
        }),
        ("Contact — INTERNAL ONLY", {
            "fields": ("contact_email", "contact_phone"),
            "description": (
                "Never served on a public surface: §C.4/§N require an explicit "
                "consent policy before publishing partner contact details, and none "
                "exists. Excluded from Partner.PUBLIC_FIELDS."
            ),
        }),
        ("Provenance", {"fields": ("source_application",)}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )
