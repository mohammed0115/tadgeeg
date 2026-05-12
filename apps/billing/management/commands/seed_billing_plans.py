"""Idempotently seed the four canonical billing plans.

Re-runnable: uses ``update_or_create`` keyed on ``code`` so running it
twice doesn't duplicate rows. Pricing/quota changes here propagate to
new subscriptions only — existing rows keep their snapshotted values
(see Plan / OrganizationSubscription module docstring)."""
from __future__ import annotations

from decimal import Decimal

from django.core.management.base import BaseCommand

from apps.billing.choices import PlanCode
from apps.billing.models import Plan


PLANS = [
    {
        "code":           PlanCode.FREE_TRIAL,
        "name_ar":        "التجربة المجانية",
        "name_en":        "Free Trial",
        "description_ar": "٢٠ فاتورة مجانية لمرة واحدة لكل منظمة.",
        "description_en": "20 free invoices, once per organization.",
        "invoice_limit":  20,
        "price":          Decimal("0.00"),
        "duration_days":  30,
        "is_free":        True,
        "is_trial":       True,
        "sort_order":     0,
    },
    {
        "code":           PlanCode.STARTER,
        "name_ar":        "Starter",
        "name_en":        "Starter",
        "description_ar": "١٠٠ فاتورة شهريًا.",
        "description_en": "100 invoices per month.",
        "invoice_limit":  100,
        "price":          Decimal("350.00"),
        "duration_days":  30,
        "is_free":        False,
        "is_trial":       False,
        "sort_order":     10,
    },
    {
        "code":           PlanCode.BUSINESS,
        "name_ar":        "Business",
        "name_en":        "Business",
        "description_ar": "٥٠٠ فاتورة شهريًا — الأكثر طلبًا.",
        "description_en": "500 invoices per month — most popular.",
        "invoice_limit":  500,
        "price":          Decimal("550.00"),
        "duration_days":  30,
        "is_free":        False,
        "is_trial":       False,
        "sort_order":     20,
    },
    {
        "code":           PlanCode.PROFESSIONAL,
        "name_ar":        "Professional",
        "name_en":        "Professional",
        "description_ar": "١٠٠٠ فاتورة شهريًا.",
        "description_en": "1000 invoices per month.",
        "invoice_limit":  1000,
        "price":          Decimal("890.00"),
        "duration_days":  30,
        "is_free":        False,
        "is_trial":       False,
        "sort_order":     30,
    },
]


class Command(BaseCommand):
    help = "Idempotently create/update the canonical billing plans."

    def handle(self, *args, **options):
        created = updated = 0
        for spec in PLANS:
            defaults = {k: v for k, v in spec.items() if k != "code"}
            defaults["currency"]  = "SAR"
            defaults["is_active"] = True
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
            f"Done. {created} created, {updated} updated. Total active plans: "
            f"{Plan.objects.filter(is_active=True).count()}"
        ))
