"""Both limit dimensions must be frozen onto the subscription, by every path
that creates one.

Phase 3A added ``user_limit`` and ``SeatService``, but the three creation paths
in ``SubscriptionService`` froze only ``invoice_limit``. ``user_limit`` stayed
NULL — which this codebase reads as *unlimited* — so seat enforcement was live
in unit tests (which set the column by hand) and dead for every real customer.
These tests go through the real service path for that reason.

They also pin the custom-quote refusal: ``payments.pricing`` resolves a
subscription's amount with ``Decimal(sub.plan.price)``, so a subscription
pointing at a NULL-priced plan is a TypeError waiting for a payment attempt.
"""
from io import StringIO

import pytest
from django.core.management import call_command

pytestmark = pytest.mark.django_db


@pytest.fixture
def plans(db):
    call_command("seed_billing_plans", stdout=StringIO())


def _org(name="Snapshot Co"):
    from apps.authentication.models import Organization
    return Organization.objects.create(name=name)


def test_paid_subscription_freezes_the_seat_limit(plans):
    from apps.billing.choices import PlanCode
    from apps.billing.models import Plan
    from apps.billing.services.subscription_service import SubscriptionService

    plan = Plan.objects.get(code=PlanCode.STARTER)   # user_limit = 1
    sub = SubscriptionService().create_pending_paid_subscription(_org(), plan)
    assert sub.user_limit == plan.user_limit, (
        "creation froze invoice_limit but left user_limit NULL (= unlimited)"
    )
    activated = SubscriptionService().activate_subscription(sub)
    assert activated.user_limit == plan.user_limit


def test_trial_subscription_freezes_the_seat_limit(plans):
    from apps.billing.choices import PlanCode
    from apps.billing.models import Plan
    from apps.billing.services.subscription_service import SubscriptionService

    plan = Plan.objects.get(code=PlanCode.FREE_TRIAL)
    sub = SubscriptionService().create_free_trial(_org("Trial Co"))
    assert sub.user_limit == plan.user_limit


def test_seat_enforcement_is_live_through_the_real_service_path(plans):
    """End-to-end: seed -> subscribe -> SeatService must refuse the 2nd user."""
    from apps.authentication.models import User
    from apps.billing.choices import PlanCode
    from apps.billing.models import Plan
    from apps.billing.services.quota_service import SeatLimitExceeded, SeatService
    from apps.billing.services.subscription_service import SubscriptionService

    org = _org("Seat Co")
    plan = Plan.objects.get(code=PlanCode.STARTER)          # 1 seat
    sub = SubscriptionService().create_pending_paid_subscription(org, plan)
    SubscriptionService().activate_subscription(sub)

    User.objects.create_user(
        username="owner", email="owner@seat.co", password="x", organization=org,
    )
    assert SeatService().seat_limit(org) == 1
    with pytest.raises(SeatLimitExceeded):
        SeatService().assert_can_add_user(org)


def test_custom_quote_plan_cannot_become_a_pending_paid_subscription(plans):
    """Otherwise the payment resolver does Decimal(None) -> TypeError 500."""
    from apps.billing.choices import PlanCode
    from apps.billing.models import Plan
    from apps.billing.services.subscription_service import (
        SubscriptionError, SubscriptionService,
    )

    plan = Plan.objects.get(code=PlanCode.ENTERPRISE)
    assert plan.is_custom_quote and plan.price is None
    with pytest.raises(SubscriptionError):
        SubscriptionService().create_pending_paid_subscription(_org("Ent Co"), plan)


def test_price_resolver_refuses_a_custom_quote_plan_cleanly(plans):
    """``_subscription_resolver`` must raise PriceResolutionError, not TypeError.

    It is the server-side authority on payable amounts; a crash there is a 500
    on a payment attempt rather than a refusal.
    """
    from apps.billing.choices import PlanCode, SubscriptionStatus
    from apps.billing.models import OrganizationSubscription, Plan
    from apps.payments.pricing import PriceResolutionError, resolve_or_validate

    org = _org("Resolver Co")
    plan = Plan.objects.get(code=PlanCode.ENTERPRISE)
    # Bypass the service guard on purpose: this pins the *resolver's* behaviour
    # for any row that reaches it, however it got created (fixture, shell, admin).
    sub = OrganizationSubscription.objects.create(
        organization=org, plan=plan,
        status=SubscriptionStatus.PENDING_PAYMENT,
        invoice_limit=plan.invoice_limit, user_limit=plan.user_limit,
    )
    with pytest.raises(PriceResolutionError):
        resolve_or_validate(
            purpose="subscription",
            reference_type="organization_subscription",
            reference_id=str(sub.id),
            organization=org,
            requested_amount=None,
        )


def test_manual_payment_refuses_a_custom_quote_plan_cleanly(plans):
    """Same defect class on the staff-operated manual payment path."""
    from apps.authentication.models import User
    from apps.billing.choices import PlanCode, SubscriptionStatus
    from apps.billing.models import OrganizationSubscription, Plan
    from apps.payments.services.payment_service import (
        PaymentService, PaymentValidationError,
    )
    from decimal import Decimal

    org = _org("Manual Co")
    staff = User.objects.create_user(
        username="ops", email="ops@tadgeeg.test", password="x", is_staff=True,
    )
    plan = Plan.objects.get(code=PlanCode.ENTERPRISE)
    sub = OrganizationSubscription.objects.create(
        organization=org, plan=plan,
        status=SubscriptionStatus.PENDING_PAYMENT,
        invoice_limit=plan.invoice_limit, user_limit=plan.user_limit,
    )
    with pytest.raises(PaymentValidationError):
        PaymentService().create_manual_payment(
            organization=org, user=staff, subscription=sub,
            amount=Decimal("5000.00"), currency="SAR",
            reference="NEGOTIATED-001", reason="negotiated enterprise deal",
        )
