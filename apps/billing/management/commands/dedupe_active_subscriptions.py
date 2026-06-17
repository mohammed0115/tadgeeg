"""Diagnose / repair organizations that have more than one usable
(active|trialing) subscription.

Background: the "one usable subscription per org" rule is enforced in the
application layer (SubscriptionService.activate_subscription) and by a partial
UniqueConstraint that only works on Postgres/SQLite — MySQL silently ignores
it, so historical rows may have drifted into multiple actives.

Safe by default:
  * ``--dry-run`` (DEFAULT): only reports; changes NOTHING.
  * ``--apply``: keeps the most recently created usable subscription per org and
    sets the older ones to CANCELED. Never deletes rows.

Usage:
  python manage.py dedupe_active_subscriptions            # dry-run
  python manage.py dedupe_active_subscriptions --apply
"""
from __future__ import annotations

from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.billing.choices import SubscriptionStatus, USABLE_STATUSES
from apps.billing.models import OrganizationSubscription


class Command(BaseCommand):
    help = "Report (or repair) orgs with more than one usable subscription."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true",
            help="Cancel older duplicates, keeping the newest usable per org. "
                 "Without this flag the command is a no-op dry-run.",
        )

    def handle(self, *args, **options):
        apply = options["apply"]

        usable = (
            OrganizationSubscription.objects
            .filter(status__in=tuple(USABLE_STATUSES))
            .order_by("organization_id", "-created_at")
        )
        by_org = defaultdict(list)
        for sub in usable:
            by_org[sub.organization_id].append(sub)

        dupes = {org_id: subs for org_id, subs in by_org.items() if len(subs) > 1}

        if not dupes:
            self.stdout.write(self.style.SUCCESS(
                "No organizations with duplicate usable subscriptions."))
            return

        self.stdout.write(self.style.WARNING(
            f"{len(dupes)} organization(s) have multiple usable subscriptions:"))

        total_to_cancel = 0
        for org_id, subs in dupes.items():
            keep = subs[0]            # newest (queryset ordered -created_at)
            stale = subs[1:]
            total_to_cancel += len(stale)
            self.stdout.write(
                f"  org={org_id}: keep {keep.pk} ({keep.status}), "
                f"cancel {len(stale)} older: {[str(s.pk) for s in stale]}"
            )

        if not apply:
            self.stdout.write(self.style.NOTICE(
                f"DRY-RUN — nothing changed. Would cancel {total_to_cancel} "
                f"subscription(s). Re-run with --apply to repair."))
            return

        with transaction.atomic():
            cancelled = 0
            for org_id, subs in dupes.items():
                for stale in subs[1:]:
                    locked = (OrganizationSubscription.objects
                              .select_for_update().get(pk=stale.pk))
                    if locked.status in USABLE_STATUSES:
                        locked.status = SubscriptionStatus.CANCELED
                        locked.save(update_fields=["status", "updated_at"])
                        cancelled += 1
        self.stdout.write(self.style.SUCCESS(
            f"Repaired — cancelled {cancelled} duplicate subscription(s)."))
