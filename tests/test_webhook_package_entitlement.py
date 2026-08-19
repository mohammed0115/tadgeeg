from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.management import call_command
from django.test import Client
from django.utils import timezone

from apps.authentication.models import Organization, User
from apps.billing.choices import PlanCode, SubscriptionStatus
from apps.billing.models import OrganizationSubscription, Plan


def _user_for_plan(code, email):
    org = Organization.objects.create(name=f"{code}-webhook")
    plan = Plan.objects.get(code=code)
    now = timezone.now()
    OrganizationSubscription.objects.create(
        organization=org, plan=plan, status=SubscriptionStatus.ACTIVE,
        starts_at=now - timedelta(days=1), ends_at=now + timedelta(days=29),
        invoice_limit=plan.invoice_limit, user_limit=plan.user_limit,
        feature_tiers_snapshot=plan.feature_tiers,
    )
    return User.objects.create_user(
        email=email, password="x", full_name="Webhook User", organization=org,
        role=User.Role.ADMIN,
    )


@pytest.mark.django_db
def test_webhooks_require_full_api_package():
    call_command("seed_billing_plans")
    limited = _user_for_plan(PlanCode.BUSINESS, "limited-webhooks@test.local")
    enterprise = _user_for_plan(PlanCode.ENTERPRISE, "enterprise-webhooks@test.local")
    client = Client()
    client.force_login(limited)
    assert client.get("/api/v1/webhooks/").status_code == 403
    client.force_login(enterprise)
    assert client.get("/api/v1/webhooks/").status_code == 200
