"""Expire subscriptions whose ends_at is in the past.

Flip any ACTIVE/TRIALING subscription with ``ends_at < now`` to
EXPIRED. Designed to run from Celery beat (already wired) or cron;
safe to run as often as every minute — it's idempotent because
already-expired rows are excluded by the filter."""
from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.billing.services.subscription_service import SubscriptionService


class Command(BaseCommand):
    help = "Flip active/trialing subscriptions past their ends_at to EXPIRED."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Count what would change without writing.",
        )

    def handle(self, *args, **options):
        from apps.billing.choices import SubscriptionStatus
        from apps.billing.models import OrganizationSubscription
        from django.utils import timezone

        if options.get("dry_run"):
            would = (
                OrganizationSubscription.objects
                .filter(
                    status__in=(SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING),
                    ends_at__lt=timezone.now(),
                )
                .count()
            )
            self.stdout.write(self.style.WARNING(
                f"DRY RUN — would expire {would} subscription(s)."
            ))
            return

        count = SubscriptionService().expire_old_subscriptions()
        if count:
            self.stdout.write(self.style.SUCCESS(
                f"Expired {count} subscription(s)."
            ))
        else:
            self.stdout.write("No subscriptions past their ends_at.")
