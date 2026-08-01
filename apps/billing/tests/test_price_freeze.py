"""The price a customer agreed to survives a catalogue edit.

3A froze the *limits* on the subscription but left the *price* resolving from
the live plan, so editing a catalogue price changed what an already-placed
subscription would be charged. That was an open money defect for a whole phase.

Everything here goes through the real service and payment paths. Asserting that
a column holds a number would prove nothing about what a customer is charged —
3A shipped a dead `user_limit` precisely because its tests set the column by
hand and never asked the service to write it.
"""

from __future__ import annotations

from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

pytestmark = pytest.mark.django_db


@pytest.fixture
def plans(db):
    call_command("seed_billing_plans", stdout=StringIO())


def _org(name="Freeze Co"):
    from apps.authentication.models import Organization

    return Organization.objects.create(name=name)


def _resolve(sub, org):
    """The authoritative amount, taken the way a payment takes it."""
    from apps.payments.pricing import resolve_or_validate

    return resolve_or_validate(
        purpose="subscription",
        reference_type="organization_subscription",
        reference_id=str(sub.id),
        organization=org,
        requested_amount=Decimal(sub.price_at_purchase or 0),
    )


# ── the defect this closes ───────────────────────────────────────────────────

def test_a_catalogue_price_edit_does_not_change_what_an_existing_subscription_pays(plans):
    """The money test. Proven end-to-end through price resolution."""
    from apps.billing.choices import PlanCode
    from apps.billing.models import Plan
    from apps.billing.services.subscription_service import SubscriptionService

    org = _org()
    plan = Plan.objects.get(code=PlanCode.STARTER)          # 149.00
    sold_at = plan.price
    sub = SubscriptionService().create_pending_paid_subscription(org, plan)

    amount_before, _ = _resolve(sub, org)
    assert amount_before == sold_at

    # The catalogue owner triples the price.
    plan.price = Decimal("447.00")
    plan.save(update_fields=["price"])

    sub.refresh_from_db()
    amount_after, currency = _resolve(sub, org)
    assert amount_after == sold_at, (
        f"an existing subscription is now charged {amount_after} after a "
        f"catalogue edit; it was sold at {sold_at}"
    )
    assert currency == "SAR"


def test_activation_does_not_re_read_the_price_from_the_catalogue(plans):
    """Limits are re-snapshotted at activation; the agreed price must not be.

    Otherwise a catalogue edit landing between creation and payment silently
    changes the amount — the same defect, through a narrower window.
    """
    from apps.billing.choices import PlanCode
    from apps.billing.models import Plan
    from apps.billing.services.subscription_service import SubscriptionService

    org = _org("Activation Co")
    plan = Plan.objects.get(code=PlanCode.BASIC)            # 299.00
    sold_at = plan.price
    svc = SubscriptionService()
    sub = svc.create_pending_paid_subscription(org, plan)

    plan.price = Decimal("999.00")
    plan.invoice_limit = 12345
    plan.save(update_fields=["price", "invoice_limit"])

    activated = svc.activate_subscription(sub)
    assert activated.price_at_purchase == sold_at, "activation re-read the price"
    # …while the limit legitimately follows the plan, as 3A established.
    assert activated.invoice_limit == 12345


def test_every_creation_path_writes_the_price(plans):
    """Rule 3: a column nothing writes is half a feature."""
    from apps.billing.choices import PlanCode
    from apps.billing.models import Plan
    from apps.billing.services.subscription_service import SubscriptionService

    svc = SubscriptionService()

    trial = svc.create_free_trial(_org("Trial Co"))
    assert trial.price_at_purchase is not None, "create_free_trial froze no price"

    paid = svc.create_pending_paid_subscription(
        _org("Paid Co"), Plan.objects.get(code=PlanCode.BUSINESS),
    )
    assert paid.price_at_purchase == Decimal("599.00")
    assert paid.currency_at_purchase == "SAR"

    activated = svc.activate_subscription(paid)
    assert activated.price_at_purchase == Decimal("599.00")


# ── rows created before the snapshot existed ─────────────────────────────────

def test_a_row_without_a_snapshot_is_refused_not_guessed(plans):
    """NULL means "unknowable", never "look it up in today's catalogue".

    Charging a pre-snapshot customer the current number would present a price
    they never agreed to as though they had. A refusal is recoverable by a
    human; a wrong charge is not.
    """
    from apps.billing.choices import PlanCode, SubscriptionStatus
    from apps.billing.models import OrganizationSubscription, Plan
    from apps.payments.pricing import PriceResolutionError

    org = _org("Legacy Co")
    plan = Plan.objects.get(code=PlanCode.STARTER)
    legacy = OrganizationSubscription.objects.create(      # as an old row looks
        organization=org, plan=plan,
        status=SubscriptionStatus.PENDING_PAYMENT,
        invoice_limit=plan.invoice_limit,
    )
    assert legacy.price_at_purchase is None
    assert legacy.has_frozen_price is False

    with pytest.raises(PriceResolutionError) as exc:
        _resolve(legacy, org)
    assert "no frozen price" in str(exc.value).lower()


# ── Enterprise: the negotiated path ──────────────────────────────────────────

def test_enterprise_can_be_sold_at_a_negotiated_price(plans):
    """A custom-quote plan becomes chargeable once an agreed price exists."""
    from apps.billing.choices import PlanCode
    from apps.billing.models import Plan
    from apps.billing.services.subscription_service import SubscriptionService

    org = _org("Enterprise Co")
    plan = Plan.objects.get(code=PlanCode.ENTERPRISE)
    assert plan.price is None and plan.is_custom_quote

    sub = SubscriptionService().create_pending_paid_subscription(
        org, plan, negotiated_price=Decimal("7500.00"),
    )
    assert sub.price_is_negotiated is True

    amount, currency = _resolve(sub, org)
    assert amount == Decimal("7500.00")
    assert currency == "SAR"


def test_self_service_still_refuses_a_custom_quote_plan(plans):
    """The negotiated path is deliberate and staff-driven, not a way in."""
    from apps.billing.choices import PlanCode
    from apps.billing.models import Plan
    from apps.billing.services.subscription_service import (
        SubscriptionError, SubscriptionService,
    )

    plan = Plan.objects.get(code=PlanCode.ENTERPRISE)
    with pytest.raises(SubscriptionError) as exc:
        SubscriptionService().create_pending_paid_subscription(_org("Walkup Co"), plan)
    assert "quotation" in str(exc.value).lower()


def test_a_negotiated_price_cannot_override_a_listed_plan(plans):
    """One amount per subscription, with a single provenance."""
    from apps.billing.choices import PlanCode
    from apps.billing.models import Plan
    from apps.billing.services.subscription_service import (
        SubscriptionError, SubscriptionService,
    )

    plan = Plan.objects.get(code=PlanCode.STARTER)
    with pytest.raises(SubscriptionError) as exc:
        SubscriptionService().create_pending_paid_subscription(
            _org("Override Co"), plan, negotiated_price=Decimal("1.00"),
        )
    assert "list price" in str(exc.value).lower()


def test_a_negotiated_price_must_be_positive(plans):
    from apps.billing.choices import PlanCode
    from apps.billing.models import Plan
    from apps.billing.services.subscription_service import (
        SubscriptionError, SubscriptionService,
    )

    plan = Plan.objects.get(code=PlanCode.ENTERPRISE)
    with pytest.raises(SubscriptionError):
        SubscriptionService().create_pending_paid_subscription(
            _org("Zero Co"), plan, negotiated_price=Decimal("0"),
        )


# ── manual payment path ──────────────────────────────────────────────────────

def test_manual_payment_validates_against_the_frozen_price(plans):
    """Staff-entered amounts match what the customer agreed, not the catalogue."""
    from apps.authentication.models import User
    from apps.billing.choices import PlanCode
    from apps.billing.models import Plan
    from apps.billing.services.subscription_service import SubscriptionService
    from apps.payments.services.payment_service import (
        PaymentService, PaymentValidationError,
    )

    org = _org("Manual Co")
    staff = User.objects.create_user(
        username="ops2", email="ops2@tadgeeg.test", password="x", is_staff=True,
    )
    plan = Plan.objects.get(code=PlanCode.STARTER)
    sub = SubscriptionService().create_pending_paid_subscription(org, plan)

    plan.price = Decimal("999.00")          # catalogue moves after the sale
    plan.save(update_fields=["price"])

    # The new catalogue price must NOT be accepted…
    with pytest.raises(PaymentValidationError):
        PaymentService().create_manual_payment(
            organization=org, user=staff, subscription=sub,
            amount=Decimal("999.00"), currency="SAR",
            reference="WRONG-1", reason="catalogue price",
        )

    # …and the agreed one must be.
    payment = PaymentService().create_manual_payment(
        organization=org, user=staff, subscription=sub,
        amount=Decimal("149.00"), currency="SAR",
        reference="RIGHT-1", reason="agreed price",
    )
    assert payment is not None
