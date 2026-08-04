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

from pathlib import Path

from django.core.files import File
from django.core.management.base import BaseCommand

from apps.partners.models import Partner, PartnerStatus, PartnerTier, PartnerType


#: Logos live in the repository so every environment renders the same card.
#: The alternative — uploading through the admin — has to be repeated on dev,
#: test and live, and is lost whenever a media volume is recreated.
SEED_ASSETS = Path(__file__).resolve().parents[2] / "seed_assets"


PARTNERS = [
    {
        "slug": "bironex-holding",
        "company_name": "Bironex Holding",
        "company_name_ar": "شركة بيرونيكس القابضة",
        "country": "SA",
        "website": "https://bironex.sa",
        # INTERNAL — Partner.PUBLIC_FIELDS excludes both, so these are stored
        # for the people who own the relationship and never served publicly.
        # §N requires explicit consent before a partner's contact details go
        # on a public page, and no such consent is recorded.
        "contact_email": "info@bironex.sa",
        "contact_phone": "056929862",
        # Verbatim from spec §C.3 — do not paraphrase.
        "short_description": (
            "شريك استراتيجي في تطوير الحلول الرقمية والذكاء الاصطناعي "
            "وأنظمة ERP والتحول الرقمي."
        ),
        "long_description": (
            "شريك استراتيجي في تطوير الحلول الرقمية والذكاء الاصطناعي "
            "وأنظمة ERP والتحول الرقمي."
        ),
        # Without these the English page served the Arabic paragraph under a
        # Latin company name. Partner copy is data, so it cannot go through the
        # gettext catalogue — the translation has to live on the row.
        "short_description_en": (
            "A strategic partner in digital solutions, artificial intelligence, "
            "ERP systems and digital transformation."
        ),
        "long_description_en": (
            "A strategic partner in digital solutions, artificial intelligence, "
            "ERP systems and digital transformation."
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
            else:
                # Update content, but leave `status` alone: an operator may
                # have hidden this partner on purpose.
                for field, value in defaults.items():
                    setattr(partner, field, value)
                partner.save()
                updated += 1
                self.stdout.write(f"  · updated {slug} (status left at {partner.status!r})")

            self._attach_logo(partner, slug)

        self.stdout.write(self.style.SUCCESS(
            f"Done. {created} created, {updated} updated. "
            f"Published partners: {Partner.published.count()}"
        ))

    def _attach_logo(self, partner, slug):
        """Attach ``seed_assets/<slug>.<ext>`` when present.

        Silence would be wrong in both directions, so both are reported: a
        missing asset is a note (the card falls back to initials and the page
        still works), and an unreadable one is a warning. Re-running does not
        re-upload — the file is only written when the field is empty.
        """
        if partner.logo:
            return

        for extension in (".png", ".jpg", ".jpeg", ".webp", ".svg"):
            candidate = SEED_ASSETS / f"{slug}{extension}"
            if not candidate.exists():
                continue
            try:
                with candidate.open("rb") as handle:
                    partner.logo.save(candidate.name, File(handle), save=True)
            except OSError as exc:
                self.stdout.write(self.style.WARNING(
                    f"    ! logo {candidate.name} could not be read: {exc}"
                ))
                return
            self.stdout.write(self.style.SUCCESS(f"    + logo {candidate.name}"))
            return

        self.stdout.write(
            f"    · no logo at {SEED_ASSETS.name}/{slug}.(png|jpg|webp|svg) "
            f"— the card will show initials"
        )
