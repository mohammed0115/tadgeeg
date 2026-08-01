"""Seed the add-on catalogue from spec §I.

Prices are transcribed verbatim. §I.1 user packs and §I.3 advanced API carry
"/شهر" and are recurring; §I.2 invoice packs and the one-time services do not
and are charged once. The three "حسب العرض" services carry no price at all.

"يبدأ من" prices (Odoo integration, custom reports, advanced API) are floors
under a negotiation, not amounts anyone can pay today, so they are seeded with
``is_price_from=True`` and are excluded from self-service purchase. The report
records this reading rather than leaving it implicit.

Idempotent: re-running updates the catalogue and never duplicates a code.
"""

from __future__ import annotations

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.billing.choices import AddonBillingType, AddonDimension
from apps.billing.models import Addon

D = Decimal
R, O, Q = (
    AddonBillingType.RECURRING,
    AddonBillingType.ONE_TIME,
    AddonBillingType.CUSTOM_QUOTE,
)
USERS, INVOICES, NONE = (
    AddonDimension.USERS,
    AddonDimension.INVOICES,
    AddonDimension.NONE,
)

# code, en, ar, billing_type, dimension, quantity, price, is_price_from, sort
ADDONS = [
    # §I.1 — extra users, priced per month
    ("user_extra_1",   "Extra user",            "مستخدم إضافي",            R, USERS, 1,  D("30.00"),   False, 10),
    ("user_pack_10",   "10-user pack",          "باقة 10 مستخدمين",        R, USERS, 10, D("250.00"),  False, 20),
    ("user_pack_25",   "25-user pack",          "باقة 25 مستخدمًا",         R, USERS, 25, D("550.00"),  False, 30),

    # §I.2 — invoice packs. No "/شهر" in the spec: one-time quota top-ups.
    ("invoice_pack_500",   "500 invoices",   "500 فاتورة",    O, INVOICES, 500,   D("50.00"),  False, 40),
    ("invoice_pack_1000",  "1,000 invoices", "1,000 فاتورة",  O, INVOICES, 1000,  D("90.00"),  False, 50),
    ("invoice_pack_5000",  "5,000 invoices", "5,000 فاتورة",  O, INVOICES, 5000,  D("350.00"), False, 60),
    ("invoice_pack_10000", "10,000 invoices","10,000 فاتورة", O, INVOICES, 10000, D("600.00"), False, 70),

    # §I.3 — professional services. These grant no quota.
    ("svc_training_remote", "Remote training",        "تدريب عن بعد",       O, NONE, None, D("500.00"),   False, 80),
    ("svc_training_onsite", "On-site training",       "تدريب حضوري",        Q, NONE, None, None,          False, 90),
    ("svc_odoo",            "Odoo integration",       "ربط Odoo",           O, NONE, None, D("2000.00"),  True,  100),
    ("svc_erp_other",       "Other ERP integration",  "ربط ERP آخر",        Q, NONE, None, None,          False, 110),
    ("svc_custom_reports",  "Custom reports",         "تقارير مخصصة",       O, NONE, None, D("1500.00"),  True,  120),
    ("svc_api_advanced",    "Advanced API",           "API متقدم",          R, NONE, None, D("500.00"),   True,  130),
    ("svc_white_label",     "White Label",            "White Label",        Q, NONE, None, None,          False, 140),
]


class Command(BaseCommand):
    help = "Seed the add-on catalogue (spec §I). Idempotent."

    @transaction.atomic
    def handle(self, *args, **options):
        created = updated = 0
        for (code, en, ar, btype, dim, qty, price, from_price, order) in ADDONS:
            defaults = {
                "name_en": en,
                "name_ar": ar,
                "billing_type": btype,
                "dimension": dim,
                "quantity": qty,
                "price": price,
                "currency": "SAR",
                "is_price_from": from_price,
                "is_active": True,
                "sort_order": order,
            }
            obj, was_created = Addon.objects.update_or_create(
                code=code, defaults=defaults,
            )
            if was_created:
                created += 1
                self.stdout.write(f"  + created {code}")
            else:
                updated += 1
                self.stdout.write(f"  · updated {code}")

        purchasable = sum(1 for a in Addon.objects.filter(is_active=True) if a.is_purchasable)
        self.stdout.write(
            f"Done. {created} created, {updated} updated. "
            f"Active add-ons: {Addon.objects.filter(is_active=True).count()} "
            f"(self-service purchasable: {purchasable})"
        )
