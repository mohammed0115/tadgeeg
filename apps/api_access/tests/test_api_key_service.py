from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.api_access.models import OrganizationAPIKey
from apps.api_access.service import APIAccessError, issue_key
from apps.authentication.models import Organization
from apps.billing.choices import PlanCode, SubscriptionStatus
from apps.billing.models import OrganizationSubscription, Plan


@pytest.mark.django_db
def test_business_api_key_is_limited_and_digest_only():
    call_command("seed_billing_plans")
    org = Organization.objects.create(name="Business API")
    plan = Plan.objects.get(code=PlanCode.BUSINESS)
    now = timezone.now()
    OrganizationSubscription.objects.create(
        organization=org, plan=plan, status=SubscriptionStatus.ACTIVE,
        starts_at=now - timedelta(days=1), ends_at=now + timedelta(days=29),
        invoice_limit=plan.invoice_limit, user_limit=plan.user_limit,
        feature_tiers_snapshot=plan.feature_tiers,
    )
    raw, key = issue_key(organization=org, name="ERP")
    assert raw.startswith("tdg_")
    assert raw not in key.key_hash
    assert key.monthly_limit == 10_000
    assert key.scopes == ["invoices:read", "reports:read"]
    with pytest.raises(APIAccessError, match="limit"):
        issue_key(organization=org, name="second")
    assert OrganizationAPIKey.authenticate(raw).pk == key.pk
