"""
Management command: prune_audit_logs
=====================================
Deletes audit log records whose retain_until date has passed.
Records with retain_until=NULL are automatically assigned a 7-year window
from their timestamp before pruning is evaluated.

Usage:
    python manage.py prune_audit_logs           # dry-run (shows count)
    python manage.py prune_audit_logs --execute  # actually deletes

Add to Celery Beat for automated retention enforcement:
    {"task": "authentication.prune_audit_logs", "schedule": crontab(hour=3, minute=0, day_of_week=0)}
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

RETENTION_YEARS = 7


class Command(BaseCommand):
    help = "Prune audit log records that have exceeded the 7-year retention window."

    def add_arguments(self, parser):
        parser.add_argument(
            "--execute",
            action="store_true",
            default=False,
            help="Actually delete expired records (default is dry-run).",
        )

    def handle(self, *args, **options):
        from apps.authentication.models import AuditLog

        now = timezone.now()
        cutoff = now - timedelta(days=RETENTION_YEARS * 365)

        # Backfill retain_until for records that never had it set
        backfill_qs = AuditLog.objects.filter(retain_until__isnull=True)
        backfill_count = backfill_qs.count()
        if backfill_count:
            self.stdout.write(f"Backfilling retain_until for {backfill_count} records...")
            # Use a raw loop-free bulk_update via annotated queryset
            from django.db.models import ExpressionWrapper, DurationValue, F, DateTimeField
            from django.db.models.functions import Now
            # Set retain_until = timestamp + 7 years
            for log in backfill_qs.only("id", "timestamp").iterator(chunk_size=500):
                log.retain_until = log.timestamp + timedelta(days=RETENTION_YEARS * 365)
            AuditLog.objects.bulk_update(
                list(backfill_qs.only("id", "timestamp")),
                fields=["retain_until"],
            )

        # Find expired records
        expired_qs = AuditLog.objects.filter(retain_until__lt=now)
        expired_count = expired_qs.count()

        self.stdout.write(f"Found {expired_count} audit log records past their retention date.")

        if options["execute"]:
            deleted, _ = expired_qs.delete()
            self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} expired audit log records."))
        else:
            self.stdout.write(
                self.style.WARNING("Dry-run mode — no records deleted. Use --execute to delete.")
            )
