"""
Management command: setup_platform_crm_roles
============================================
Idempotently create the five Platform CRM Django Groups.

  python manage.py setup_platform_crm_roles

Never deletes groups, never modifies users, never assigns membership.
Safe to run repeatedly.
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create the Platform CRM role groups (idempotent; no user assignment)."

    def handle(self, *args, **options):
        from apps.platform_admin.services.crm_roles import ensure_platform_crm_groups

        report = ensure_platform_crm_groups()

        for name in report["created"]:
            self.stdout.write(self.style.SUCCESS(f"Created group: {name}"))
        for name in report["existing"]:
            self.stdout.write(f"Existing group (unchanged): {name}")

        self.stdout.write(
            self.style.WARNING("No user assignments performed.")
        )
        self.stdout.write(
            f"Summary: {len(report['created'])} created, "
            f"{len(report['existing'])} existing, "
            f"{report['assignments']} user assignments."
        )
