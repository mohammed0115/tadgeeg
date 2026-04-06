"""
Management command: fix_user_org
================================
Diagnoses and optionally fixes users who cannot create other users
because their account is missing an organization link.

Usage:
  # Diagnose only (read-only):
  python manage.py fix_user_org --email newtonsudan31@gmail.com

  # Fix: link user to the first available organization:
  python manage.py fix_user_org --email newtonsudan31@gmail.com --fix

  # Fix: link to a specific organization by name:
  python manage.py fix_user_org --email newtonsudan31@gmail.com --fix --org "Company Name"
"""

from django.core.management.base import BaseCommand, CommandError
from apps.authentication.models import User, Organization


class Command(BaseCommand):
    help = "Diagnose and fix users who cannot create users (missing org / wrong role)"

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True, help="User email to inspect")
        parser.add_argument("--fix", action="store_true", default=False,
                            help="Apply the fix (link to org). Without this flag, only diagnose.")
        parser.add_argument("--org", default=None,
                            help="Organization name to link to (default: first org in DB)")
        parser.add_argument("--set-role", default=None,
                            help="Set user role (e.g. admin, senior_auditor)")

    def handle(self, *args, **options):
        email = options["email"]
        try:
            user = User.objects.select_related("organization").get(email=email)
        except User.DoesNotExist:
            raise CommandError(f"No user found with email: {email}")

        self.stdout.write(f"\n{'=' * 60}")
        self.stdout.write(f"User: {user.email}")
        self.stdout.write(f"Full name: {user.full_name}")
        self.stdout.write(f"Role: {user.role}")
        self.stdout.write(f"Organization: {user.organization or '❌ NONE — this is the problem'}")
        self.stdout.write(f"is_active: {user.is_active}")
        self.stdout.write(f"is_superuser: {user.is_superuser}")
        self.stdout.write(f"can_manage_users: {user.can_manage_users}")
        self.stdout.write(f"is_email_verified: {user.is_email_verified}")
        self.stdout.write(f"{'=' * 60}\n")

        # Diagnose
        problems = []
        if not user.organization:
            problems.append("❌ CRITICAL: User has no organization — cannot create users")
        if not user.can_manage_users:
            problems.append(f"❌ Role '{user.role}' cannot manage users. Must be 'admin'")
        if not user.is_active:
            problems.append("❌ Account is inactive (is_active=False)")
        if not user.is_email_verified:
            problems.append("⚠️  Email not verified (is_email_verified=False)")

        if not problems:
            self.stdout.write(self.style.SUCCESS("✅ No problems found — user should be able to create users."))
            self.stdout.write("If creation still fails, check the browser console for the actual error response.")
            return

        for p in problems:
            self.stdout.write(self.style.ERROR(p))

        if not options["fix"] and not options["set_role"]:
            self.stdout.write("\nRun with --fix to apply fixes automatically.")
            self.stdout.write("Example: python manage.py fix_user_org --email "
                              f"{email} --fix")
            return

        # Apply fixes
        changed = False

        if options["set_role"]:
            role_val = options["set_role"].lower().replace("-", "_")
            valid_roles = [r[0] for r in User.Role.choices]
            if role_val not in valid_roles:
                raise CommandError(f"Invalid role '{role_val}'. Valid: {valid_roles}")
            user.role = role_val
            changed = True
            self.stdout.write(self.style.SUCCESS(f"✅ Role set to: {role_val}"))

        if options["fix"] and not user.organization:
            org_name = options.get("org")
            if org_name:
                try:
                    org = Organization.objects.get(name=org_name)
                except Organization.DoesNotExist:
                    raise CommandError(f"Organization '{org_name}' not found.")
            else:
                org = Organization.objects.first()
                if not org:
                    raise CommandError("No organizations exist in the database. Create one first.")

            user.organization = org
            changed = True
            self.stdout.write(self.style.SUCCESS(f"✅ Linked to organization: {org.name}"))

        if options["fix"] and not user.can_manage_users and not options["set_role"]:
            user.role = User.Role.ADMIN
            changed = True
            self.stdout.write(self.style.SUCCESS("✅ Role upgraded to: admin"))

        if changed:
            user.save()
            self.stdout.write(self.style.SUCCESS(
                f"\n✅ FIXED. User {email} can now create users.\n"
                f"   Organization: {user.organization}\n"
                f"   Role: {user.role}\n"
                f"   can_manage_users: {user.can_manage_users}"
            ))
