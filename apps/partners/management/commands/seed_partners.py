"""Idempotently seed the launch partners.

Follows the ``seed_billing_plans`` pattern: ``update_or_create`` keyed on the
stable identifier (``slug``), so re-running does not duplicate rows.

Bironex Holding is seeded as DATA, not markup (§C.3). A partner hardcoded into
a template cannot be reordered, re-tiered, hidden, or edited by the people who
own the relationship — which is the whole point of the admin surface.

Existing rows are updated but their ``status`` is NOT forced back to published:
if an operator has deliberately hidden a partner, a redeploy running this
command must not silently republish them.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.partners.models import Partner, PartnerStatus, PartnerTier, PartnerType


PARTNERS = [
    {
        "slug": "bironex-holding",
        "company_name": "Bironex Holding",
        "country": "SA",
        # Verbatim from spec §C.3 — do not paraphrase.
        "short_description": (
            "شريك استراتيجي في تطوير الحلول الرقمية والذكاء الاصطناعي "
            "وأنظمة ERP والتحول الرقمي."
        ),
        "long_description": (
            "شريك استراتيجي في تطوير الحلول الرقمية والذكاء الاصطناعي "
            "وأنظمة ERP والتحول الرقمي."
        ),
        "partner_type": PartnerType.STRATEGIC,
        "partner_tier": PartnerTier.STRATEGIC,
        "display_order": 0,
    },
]


class Command(BaseCommand):
    help = "Idempotently create/update the launch partners."

    def handle(self, *args, **options):
        created = updated = 0

        for spec in PARTNERS:
            slug = spec["slug"]
            defaults = {k: v for k, v in spec.items() if k != "slug"}

            partner = Partner.objects.filter(slug=slug).first()
            if partner is None:
                # New rows are published immediately — these are the launch
                # partners the public page is being built for.
                partner = Partner.objects.create(
                    slug=slug, status=PartnerStatus.PUBLISHED, **defaults
                )
                partner.publish()  # stamps published_at
                created += 1
                self.stdout.write(self.style.SUCCESS(f"  + created {slug}"))
                continue

            # Update content, but leave `status` alone: an operator may have
            # hidden this partner on purpose.
            for field, value in defaults.items():
                setattr(partner, field, value)
            partner.save()
            updated += 1
            self.stdout.write(f"  · updated {slug} (status left at {partner.status!r})")

        self.stdout.write(self.style.SUCCESS(
            f"Done. {created} created, {updated} updated. "
            f"Published partners: {Partner.published.count()}"
        ))
