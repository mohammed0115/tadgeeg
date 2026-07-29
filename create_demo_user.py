#!/usr/bin/env python
"""Create (or reset) a working demo user for Tadgeeg.

Fixes the previous version, which was broken for this project:
  * it imported django.contrib.auth.models.User — but Tadgeeg uses a CUSTOM
    user model (apps.authentication.models.User) keyed on `email`, with no
    `username` field;
  * it hard-coded a wrong sys.path.

This script:
  * creates an Organization,
  * creates/updates the demo user (email login, Senior Auditor role, verified),
  * seeds billing plans + activates a subscription so the user is NOT blocked by
    SubscriptionRequiredMiddleware,
  * (optionally) creates a client (auditee) demo user too.

Usage:  python create_demo_user.py
"""
import os
import sys

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "finai_backend.settings")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.utils import timezone  # noqa: E402

from apps.authentication.models import Organization  # noqa: E402

User = get_user_model()

EMAIL = "demo@finai.sa"
PASSWORD = "DemoDashboard123!"
CLIENT_EMAIL = "client@finai.sa"


def _activate_subscription(org):
    """Give the org an active subscription so the demo user isn't gated."""
    try:
        from apps.billing.choices import PlanCode
        from apps.billing.models import Plan
        from apps.billing.services.subscription_service import SubscriptionService
        if not Plan.objects.filter(code=PlanCode.BUSINESS).exists():
            call_command("seed_billing_plans")
        svc = SubscriptionService()
        svc.activate_subscription(
            svc.create_pending_paid_subscription(
                org, Plan.objects.get(code=PlanCode.BUSINESS)))
        return True
    except Exception as exc:  # pragma: no cover
        print(f"⚠️  Could not activate a subscription automatically: {exc}")
        print("    (Set SUBSCRIPTION_REQUIRED=false to bypass the billing gate.)")
        return False


def _upsert_user(email, *, role, full_name, org):
    user, created = User.objects.get_or_create(
        email=email, defaults={"full_name": full_name, "role": role,
                               "organization": org})
    user.full_name = full_name
    user.role = role
    user.organization = org
    user.is_active = True
    user.email_verified_at = timezone.now()
    user.set_password(PASSWORD)
    user.save()
    return user, created


def main():
    org, _ = Organization.objects.get_or_create(
        name="Demo Audit Firm",
        defaults={"country": Organization.Country.SAUDI_ARABIA})
    sub_ok = _activate_subscription(org)

    auditor, a_created = _upsert_user(
        EMAIL, role=User.Role.SENIOR_AUDITOR, full_name="Demo Auditor", org=org)
    client, c_created = _upsert_user(
        CLIENT_EMAIL, role=User.Role.CLIENT, full_name="Demo Client", org=org)

    print("✅ Demo users ready" + (" (subscription active)" if sub_ok else ""))
    print("\n📧 Auditor login:")
    print(f"   Email:    {EMAIL}")
    print(f"   Password: {PASSWORD}   (role: Senior Auditor)")
    print("\n📧 Client (auditee) login:")
    print(f"   Email:    {CLIENT_EMAIL}")
    print(f"   Password: {PASSWORD}   (role: Client)")
    print("\n🔗 App:       http://localhost:8000/")
    print("🔗 Login:     http://localhost:8000/login/")
    print("🔗 Dashboard: http://localhost:8000/dashboard/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
