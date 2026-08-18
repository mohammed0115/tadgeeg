"""Idempotently seed the nine canonical billing plans (spec §H and §J).

Re-runnable: ``update_or_create`` keyed on ``code``.

**What this command can and cannot change.** Editing a figure here propagates
to plans, and therefore to subscriptions created or activated *after* the edit.
It does NOT touch an existing subscription: ``OrganizationSubscription``
snapshots ``price``-derived charges and the limit columns at activation
(``subscription_service.activate_subscription``), so a paying customer keeps
what they were sold. That guarantee is structural, and
``tests/test_plan_catalogue.py`` asserts it.

Conventions this file relies on:

* ``None`` limit  = unlimited. NOT zero — zero means "no allowance".
* ``None`` price + ``is_custom_quote=True`` = contact sales. NOT 0.00, which
  would read as free and make the plan purchasable at no charge.

Figures are verbatim from the spec. Do not round or convert them.
"""
from __future__ import annotations

from decimal import Decimal

from django.core.management.base import BaseCommand

from apps.billing.choices import PlanCode
from apps.billing.models import Plan


# One commercial policy, consumed by the entitlement service and public API.
# Values express the contractual tier rather than a view-specific permission.
PACKAGE_POLICY = {
    PlanCode.FREE_TRIAL: {"retention_months": 3, "backup_frequency": "none", "feature_tiers": {"reports": "basic", "dashboard": "basic", "fraud_detection": "basic", "permissions": "basic", "approvals": "single", "report_customization": "none", "whatsapp": False, "api": False, "erp": False, "white_label": False}},
    PlanCode.STARTER: {"retention_months": 3, "backup_frequency": "weekly", "feature_tiers": {"reports": "basic", "dashboard": "basic", "fraud_detection": "basic", "permissions": "basic", "approvals": "single", "report_customization": "none", "whatsapp": False, "api": False, "erp": False, "white_label": False}},
    PlanCode.BASIC: {"retention_months": 12, "backup_frequency": "weekly", "feature_tiers": {"reports": "advanced", "dashboard": "advanced", "fraud_detection": "advanced", "permissions": "advanced", "approvals": "single", "report_customization": "basic", "whatsapp": False, "api": False, "erp": False, "white_label": False}},
    PlanCode.BUSINESS: {"retention_months": 24, "backup_frequency": "daily", "feature_tiers": {"reports": "professional", "dashboard": "interactive", "fraud_detection": "advanced", "permissions": "advanced", "approvals": "single", "report_customization": "basic", "whatsapp": False, "api": False, "erp": False, "white_label": False}},
    PlanCode.PROFESSIONAL: {"retention_months": 36, "backup_frequency": "daily", "feature_tiers": {"reports": "executive", "dashboard": "executive", "fraud_detection": "professional", "permissions": "full", "approvals": "single", "report_customization": "advanced", "whatsapp": True, "api": "read", "erp": False, "white_label": False}},
    PlanCode.ENTERPRISE: {"retention_months": 60, "backup_frequency": "daily", "feature_tiers": {"reports": "custom", "dashboard": "executive", "fraud_detection": "professional", "permissions": "full", "approvals": "multi", "report_customization": "full", "whatsapp": True, "api": "full", "erp": True, "white_label": True}},
    PlanCode.ACCOUNTING_PARTNER: {"retention_months": 24, "backup_frequency": "daily", "feature_tiers": {"reports": "professional", "dashboard": "interactive", "fraud_detection": "advanced", "permissions": "advanced", "approvals": "single", "report_customization": "advanced", "whatsapp": False, "api": "read", "erp": False, "white_label": False}},
    PlanCode.ACCOUNTING_PROFESSIONAL: {"retention_months": 36, "backup_frequency": "daily", "feature_tiers": {"reports": "executive", "dashboard": "executive", "fraud_detection": "professional", "permissions": "full", "approvals": "multi", "report_customization": "advanced", "whatsapp": True, "api": "read", "erp": True, "white_label": False}},
    PlanCode.ACCOUNTING_ENTERPRISE: {"retention_months": 60, "backup_frequency": "daily", "feature_tiers": {"reports": "custom", "dashboard": "executive", "fraud_detection": "professional", "permissions": "full", "approvals": "multi", "report_customization": "full", "whatsapp": True, "api": "full", "erp": True, "white_label": True}},
}


PLANS = [
    # ── Business plans (§H) ──────────────────────────────────────────────
    {
        "code":            PlanCode.FREE_TRIAL,
        "name_ar":         "التجربة المجانية",
        "name_en":         "Free Trial",
        "description_ar":  "٢٠ فاتورة مجانية لمرة واحدة لكل منظمة، لمدة ٣٠ يومًا.",
        "description_en":  "20 free invoices, once per organization, for 30 days.",
        "invoice_limit":   20,
        "user_limit":      1,
        "price":           Decimal("0.00"),
        "is_custom_quote": False,
        "duration_days":   30,
        "is_free":         True,
        "is_trial":        True,
        "sort_order":      0,
    },
    {
        "code":            PlanCode.STARTER,
        "name_ar":         "الباقة الأساسية",
        "name_en":         "Starter",
        "description_ar":  "١٠٠ فاتورة شهريًا · مستخدم واحد.",
        "description_en":  "100 invoices per month · 1 user.",
        "invoice_limit":   100,
        "user_limit":      1,
        "price":           Decimal("149.00"),
        "is_custom_quote": False,
        "duration_days":   30,
        "is_free":         False,
        "is_trial":        False,
        "sort_order":      10,
    },
    {
        "code":            PlanCode.BASIC,
        "name_ar":         "الباقة المتوسطة",
        "name_en":         "Basic",
        "description_ar":  "٥٠٠ فاتورة شهريًا · ٣ مستخدمين.",
        "description_en":  "500 invoices per month · 3 users.",
        "invoice_limit":   500,
        "user_limit":      3,
        "price":           Decimal("299.00"),
        "is_custom_quote": False,
        "duration_days":   30,
        "is_free":         False,
        "is_trial":        False,
        "sort_order":      20,
    },
    {
        "code":            PlanCode.BUSINESS,
        "name_ar":         "باقة الأعمال",
        "name_en":         "Business",
        "description_ar":  "٢٠٠٠ فاتورة شهريًا · ١٠ مستخدمين — الأكثر شيوعًا.",
        "description_en":  "2,000 invoices per month · 10 users — most popular.",
        "invoice_limit":   2000,
        "user_limit":      10,
        "price":           Decimal("599.00"),
        "is_custom_quote": False,
        "duration_days":   30,
        "is_free":         False,
        "is_trial":        False,
        "sort_order":      30,
    },
    {
        "code":            PlanCode.PROFESSIONAL,
        "name_ar":         "الباقة الاحترافية",
        "name_en":         "Professional",
        "description_ar":  "٥٠٠٠ فاتورة شهريًا · ٢٥ مستخدمًا.",
        "description_en":  "5,000 invoices per month · 25 users.",
        "invoice_limit":   5000,
        "user_limit":      25,
        "price":           Decimal("999.00"),
        "is_custom_quote": False,
        "duration_days":   30,
        "is_free":         False,
        "is_trial":        False,
        "sort_order":      40,
    },
    {
        "code":            PlanCode.ENTERPRISE,
        "name_ar":         "باقة المؤسسات",
        "name_en":         "Enterprise",
        "description_ar":  "فواتير ومستخدمون بلا حدود · التسعير حسب العرض.",
        "description_en":  "Unlimited invoices and users · custom quote.",
        "invoice_limit":   None,          # unlimited — NOT zero
        "user_limit":      None,          # unlimited — NOT zero
        "price":           None,          # custom quote — NOT 0.00
        "is_custom_quote": True,
        "duration_days":   30,
        "is_free":         False,
        "is_trial":        False,
        "sort_order":      50,
    },

    # ── Accounting-firm plans (§J) ───────────────────────────────────────
    # NOTE: the spec also gives each of these a COMPANY limit (20 / 50 /
    # unlimited). That dimension is NOT modelled — one subscription belongs to
    # exactly one Organization and a unique constraint enforces one usable
    # subscription per organisation, so "one subscription covering 20 client
    # companies" cannot be expressed. Storing the number without being able to
    # enforce it would be a guarantee that does not exist.
    # See docs/adr/0006-plan-limit-dimensions.md.
    {
        "code":            PlanCode.ACCOUNTING_PARTNER,
        "name_ar":         "شريك المحاسبة",
        "name_en":         "Accounting Partner",
        "description_ar":  "١٠٬٠٠٠ فاتورة شهريًا · ١٠ مستخدمين · لمكاتب المحاسبة.",
        "description_en":  "10,000 invoices per month · 10 users · for accounting firms.",
        "invoice_limit":   10000,
        "user_limit":      10,
        "price":           Decimal("990.00"),
        "is_custom_quote": False,
        "duration_days":   30,
        "is_free":         False,
        "is_trial":        False,
        "sort_order":      60,
    },
    {
        "code":            PlanCode.ACCOUNTING_PROFESSIONAL,
        "name_ar":         "المحاسبة الاحترافية",
        "name_en":         "Accounting Professional",
        "description_ar":  "٣٠٬٠٠٠ فاتورة شهريًا · ٢٥ مستخدمًا · لمكاتب المحاسبة.",
        "description_en":  "30,000 invoices per month · 25 users · for accounting firms.",
        "invoice_limit":   30000,
        "user_limit":      25,
        "price":           Decimal("1990.00"),
        "is_custom_quote": False,
        "duration_days":   30,
        "is_free":         False,
        "is_trial":        False,
        "sort_order":      70,
    },
    {
        "code":            PlanCode.ACCOUNTING_ENTERPRISE,
        "name_ar":         "مؤسسات المحاسبة",
        "name_en":         "Accounting Enterprise",
        "description_ar":  "بلا حدود · التسعير حسب العرض · لمكاتب المحاسبة.",
        "description_en":  "Unlimited · custom quote · for accounting firms.",
        "invoice_limit":   None,
        "user_limit":      None,
        "price":           None,
        "is_custom_quote": True,
        "duration_days":   30,
        "is_free":         False,
        "is_trial":        False,
        "sort_order":      80,
    },
]


class Command(BaseCommand):
    help = "Idempotently create/update the nine canonical billing plans."

    def handle(self, *args, **options):
        created = updated = 0
        for spec in PLANS:
            defaults = {k: v for k, v in spec.items() if k != "code"}
            defaults["currency"]  = "SAR"
            defaults["is_active"] = True
            defaults.update(PACKAGE_POLICY[spec["code"]])
            _, was_created = Plan.objects.update_or_create(
                code=spec["code"], defaults=defaults,
            )
            if was_created:
                created += 1
                self.stdout.write(self.style.SUCCESS(f"  + created {spec['code']}"))
            else:
                updated += 1
                self.stdout.write(f"  · updated {spec['code']}")

        self.stdout.write(self.style.SUCCESS(
            f"Done. {created} created, {updated} updated. Active plans: "
            f"{Plan.objects.filter(is_active=True).count()} "
            f"(purchasable: {sum(1 for p in Plan.objects.all() if p.is_purchasable)})"
        ))
