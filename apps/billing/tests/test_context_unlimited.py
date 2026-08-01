"""NULL (unlimited) must not be reported to the UI as 0 (no allowance).

`billing.context_processors.billing` runs on every authenticated page. It read
`int(sub.invoice_limit or 0)`, which collapses the two opposite meanings this
phase went to some trouble to keep apart: an Enterprise customer's header would
have said their quota was zero. Phase 3A made the column nullable, so this is
the type change reaching a consumer that migrations do not show.
"""
from io import StringIO
import pytest
from django.core.management import call_command

pytestmark = pytest.mark.django_db


@pytest.fixture
def plans(db):
    call_command("seed_billing_plans", stdout=StringIO())


def _sub(code, org, *, invoice_limit=..., used=5):
    """An ACTIVE subscription inside its date window.

    `get_active_subscription` filters on `starts_at <= now <= ends_at`
    (`quota_service.py:72-73`), so a row without a window is invisible to the
    context processor and the test would pass for the wrong reason.
    """
    from datetime import timedelta

    from django.utils import timezone

    from apps.billing.choices import SubscriptionStatus
    from apps.billing.models import OrganizationSubscription, Plan

    plan = Plan.objects.get(code=code)
    now = timezone.now()
    return OrganizationSubscription.objects.create(
        organization=org, plan=plan, status=SubscriptionStatus.ACTIVE,
        starts_at=now - timedelta(days=1), ends_at=now + timedelta(days=29),
        invoice_limit=(plan.invoice_limit if invoice_limit is ... else invoice_limit),
        user_limit=plan.user_limit,
        used_invoices=used,
    )


def test_unlimited_subscription_is_not_reported_as_a_zero_limit(plans, rf):
    """`int(sub.invoice_limit or 0)` turns unlimited into 'no allowance'."""
    from apps.authentication.models import Organization, User
    from apps.billing.choices import PlanCode
    from apps.billing.context_processors import billing as billing_context

    org = Organization.objects.create(name="Unlimited Co")
    _sub(PlanCode.ENTERPRISE, org)
    user = User.objects.create_user(
        username="u1", email="u1@x.co", password="x", organization=org,
    )
    req = rf.get("/dashboard/")
    req.user = user
    b = billing_context(req)["billing"]

    assert b.is_unlimited is True, "unlimited must be flagged, not implied"
    assert b.invoice_limit != 0, (
        "an unlimited plan is being reported as a zero allowance — the header "
        "would tell an Enterprise customer they have no quota"
    )
    assert b.usage_percent == 0


def test_a_real_zero_limit_is_still_zero(plans, rf):
    """The opposite case must keep working: 0 means no allowance."""
    from apps.authentication.models import Organization, User
    from apps.billing.choices import PlanCode
    from apps.billing.context_processors import billing as billing_context

    org = Organization.objects.create(name="Zero Co")
    _sub(PlanCode.STARTER, org, invoice_limit=0, used=0)
    user = User.objects.create_user(
        username="u2", email="u2@x.co", password="x", organization=org,
    )
    req = rf.get("/dashboard/")
    req.user = user
    b = billing_context(req)["billing"]
    assert b.is_unlimited is False
    assert b.invoice_limit == 0


def test_seat_dimension_is_exposed_on_the_existing_quota_bar(plans, rf):
    """§L.1.3 — seats ride on the existing bar, not a parallel widget."""
    from apps.authentication.models import Organization, User
    from apps.billing.choices import PlanCode
    from apps.billing.context_processors import billing as billing_context

    org = Organization.objects.create(name="Seats Co")
    _sub(PlanCode.BASIC, org)                       # 3 seats
    user = User.objects.create_user(
        username="s1", email="s1@x.co", password="x", organization=org,
    )
    User.objects.create_user(
        username="s2", email="s2@x.co", password="x", organization=org,
    )
    req = rf.get("/dashboard/")
    req.user = user
    b = billing_context(req)["billing"]

    assert b.user_limit == 3
    assert b.seats_used == 2
    assert b.is_unlimited_users is False


def test_unlimited_seats_are_not_reported_as_zero(plans, rf):
    from apps.authentication.models import Organization, User
    from apps.billing.choices import PlanCode
    from apps.billing.context_processors import billing as billing_context

    org = Organization.objects.create(name="Unlimited Seats Co")
    _sub(PlanCode.ENTERPRISE, org)
    user = User.objects.create_user(
        username="s3", email="s3@x.co", password="x", organization=org,
    )
    req = rf.get("/dashboard/")
    req.user = user
    b = billing_context(req)["billing"]

    assert b.is_unlimited_users is True
    assert b.user_limit != 0, "unlimited seats must not read as a zero seat cap"
