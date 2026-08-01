"""Add-ons are three billing types, and quota composes in one place.

Two things are being pinned here.

**§I insists the three types are not one.** So the decisive tests are that a
recurring add-on renews and a one-time one does not — driven by the stored
type, not by a caller remembering which is which.

**§I.5's sum has to be visible to enforcement.** Composing it in a helper that
only the advisory path calls would leave the row-locked write path refusing a
customer who had paid — so the tests exercise `reserve_invoice_audit`, which is
what actually says no, and not only `can_audit`, which only advises.

Everything goes through the services. 3A shipped a dead `user_limit` because
its tests set the column by hand and never asked the service to write it.
"""

from __future__ import annotations

from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

pytestmark = pytest.mark.django_db


@pytest.fixture
def catalogue(db):
    call_command("seed_billing_plans", stdout=StringIO())
    call_command("seed_addons", stdout=StringIO())


def _org(name):
    from apps.authentication.models import Organization

    return Organization.objects.create(name=name)


def _active_sub(code, org):
    from apps.billing.models import Plan
    from apps.billing.services.subscription_service import SubscriptionService

    svc = SubscriptionService()
    sub = svc.create_pending_paid_subscription(org, Plan.objects.get(code=code))
    return svc.activate_subscription(sub)


def _addon(code):
    from apps.billing.models import Addon

    return Addon.objects.get(code=code)


# ── §I prices, transcribed exactly ───────────────────────────────────────────

SPEC = [
    ("user_extra_1",       "recurring",    "users",    1,     Decimal("30.00")),
    ("user_pack_10",       "recurring",    "users",    10,    Decimal("250.00")),
    ("user_pack_25",       "recurring",    "users",    25,    Decimal("550.00")),
    ("invoice_pack_500",   "one_time",     "invoices", 500,   Decimal("50.00")),
    ("invoice_pack_1000",  "one_time",     "invoices", 1000,  Decimal("90.00")),
    ("invoice_pack_5000",  "one_time",     "invoices", 5000,  Decimal("350.00")),
    ("invoice_pack_10000", "one_time",     "invoices", 10000, Decimal("600.00")),
    ("svc_training_remote","one_time",     "none",     None,  Decimal("500.00")),
    ("svc_training_onsite","custom_quote", "none",     None,  None),
    ("svc_erp_other",      "custom_quote", "none",     None,  None),
    ("svc_white_label",    "custom_quote", "none",     None,  None),
]


@pytest.mark.parametrize("code,btype,dim,qty,price", SPEC)
def test_addon_matches_the_spec_exactly(catalogue, code, btype, dim, qty, price):
    """Literal assertions — reading the same constant the seeder reads proves
    nothing about whether it matches §I."""
    a = _addon(code)
    assert a.billing_type == btype
    assert a.dimension == dim
    assert a.quantity == qty
    assert a.price == price


def test_seed_is_idempotent(catalogue):
    from apps.billing.models import Addon

    before = Addon.objects.count()
    call_command("seed_addons", stdout=StringIO())
    assert Addon.objects.count() == before


# ── the distinction §I insists on ────────────────────────────────────────────

def test_a_recurring_addon_renews(catalogue):
    from apps.billing.services.addon_service import AddonService

    org = _org("Recurring Co")
    sub = _active_sub("business", org)
    svc = AddonService()
    svc.purchase(sub, _addon("user_pack_10"))

    result = svc.renew_for_cycle(sub)
    assert result["renewed"] == 1

    sub.refresh_from_db()
    assert sub.addons.filter(is_active=True).count() == 1, (
        "a recurring add-on was dropped at renewal"
    )


def test_a_one_time_addon_does_not_renew(catalogue):
    """The other half of the distinction. Fully consumed credit ends."""
    from apps.billing.services.addon_service import AddonService

    org = _org("OneTime Co")
    sub = _active_sub("business", org)
    svc = AddonService()
    sa = svc.purchase(sub, _addon("invoice_pack_1000"))

    sa.used_units = sa.quantity_at_purchase          # fully consumed
    sa.save(update_fields=["used_units"])

    result = svc.renew_for_cycle(sub)
    assert result["renewed"] == 0, "a one-time add-on renewed"
    assert result["expired"] == 1

    sa.refresh_from_db()
    assert sa.is_active is False


def test_custom_quote_addons_cannot_be_bought_self_service(catalogue):
    from apps.billing.services.addon_service import AddonError, AddonService

    org = _org("Quote Co")
    sub = _active_sub("business", org)
    for code in ("svc_training_onsite", "svc_erp_other", "svc_white_label"):
        with pytest.raises(AddonError) as exc:
            AddonService().purchase(sub, _addon(code))
        assert "quotation" in str(exc.value).lower()


def test_starts_from_services_are_not_self_service_either(catalogue):
    """§I.3 "يبدأ من" is a floor under a negotiation, not a payable price."""
    from apps.billing.services.addon_service import AddonError, AddonService

    org = _org("From Co")
    sub = _active_sub("business", org)
    for code in ("svc_odoo", "svc_custom_reports", "svc_api_advanced"):
        assert _addon(code).is_purchasable is False
        with pytest.raises(AddonError):
            AddonService().purchase(sub, _addon(code))


def test_a_negotiated_amount_makes_a_quoted_addon_sellable(catalogue):
    from apps.billing.services.addon_service import AddonService

    org = _org("Negotiated Co")
    sub = _active_sub("business", org)
    sa = AddonService().purchase(
        sub, _addon("svc_white_label"), negotiated_price=Decimal("25000.00"),
    )
    assert sa.price_at_purchase == Decimal("25000.00")


# ── §I.5 — effective quota ───────────────────────────────────────────────────

def test_the_worked_example_from_the_spec(catalogue):
    """Business + 10-user pack + 1,000-invoice pack → 20 users, 3,000 invoices."""
    from apps.billing.services.addon_service import AddonService
    from apps.billing.services.entitlements import (
        effective_invoice_quota, effective_seat_quota,
    )

    org = _org("Example Co")
    sub = _active_sub("business", org)              # 10 users · 2,000 invoices
    assert effective_seat_quota(sub).total == 10
    assert effective_invoice_quota(sub).total == 2000

    svc = AddonService()
    svc.purchase(sub, _addon("user_pack_10"))
    svc.purchase(sub, _addon("invoice_pack_1000"))

    assert effective_seat_quota(sub).total == 20
    assert effective_invoice_quota(sub).total == 3000


def test_the_ceiling_drops_when_a_recurring_addon_lapses(catalogue):
    """Test the drop, not only the raise."""
    from apps.billing.services.addon_service import AddonService
    from apps.billing.services.entitlements import effective_seat_quota

    org = _org("Lapse Co")
    sub = _active_sub("business", org)
    svc = AddonService()
    sa = svc.purchase(sub, _addon("user_pack_10"))
    assert effective_seat_quota(sub).total == 20

    svc.lapse(sa)
    assert effective_seat_quota(sub).total == 10, (
        "the ceiling did not fall back when the add-on lapsed"
    )


def test_unlimited_plus_an_addon_stays_unlimited_and_does_no_arithmetic(catalogue):
    from apps.billing.services.addon_service import AddonService
    from apps.billing.services.entitlements import (
        effective_invoice_quota, effective_seat_quota,
    )

    # Enterprise is custom-quote, so it is built through the negotiated path
    # D1 added rather than through the ordinary helper.
    from apps.billing.models import Plan
    from apps.billing.services.subscription_service import SubscriptionService

    org = _org("Unlimited Co")

    svc = SubscriptionService()
    pending = svc.create_pending_paid_subscription(
        org, Plan.objects.get(code="enterprise"), negotiated_price=Decimal("9000"),
    )
    sub = svc.activate_subscription(pending)
    assert sub.invoice_limit is None and sub.user_limit is None

    AddonService().purchase(sub, _addon("invoice_pack_1000"))
    AddonService().purchase(sub, _addon("user_pack_10"))

    inv, seats = effective_invoice_quota(sub), effective_seat_quota(sub)
    assert inv.is_unlimited and inv.total is None
    assert seats.is_unlimited and seats.total is None


# ── enforcement actually uses the composed value ─────────────────────────────

def test_the_row_locked_reserve_path_honours_addon_credit(catalogue):
    """The decisive one: `can_audit` advises, `reserve_invoice_audit` refuses.

    If only the advisory path composed the sum, a customer who bought a pack
    would be told they had room and then refused.
    """
    from apps.billing.services.addon_service import AddonService
    from apps.billing.services.quota_service import QuotaExceeded, QuotaService

    org = _org("Reserve Co")
    sub = _active_sub("starter", org)               # 100 invoices
    sub.used_invoices = 100
    sub.save(update_fields=["used_invoices"])

    qs = QuotaService()
    with pytest.raises(QuotaExceeded):
        qs.reserve_invoice_audit(org, quantity=1)

    AddonService().purchase(sub, _addon("invoice_pack_500"))

    ledger = qs.reserve_invoice_audit(org, quantity=1)
    assert ledger is not None, "paid-for add-on credit was refused at the lock"


def test_seat_enforcement_uses_the_composed_ceiling(catalogue):
    from apps.authentication.models import User
    from apps.billing.services.addon_service import AddonService
    from apps.billing.services.quota_service import SeatLimitExceeded, SeatService

    org = _org("Seat Addon Co")
    sub = _active_sub("starter", org)               # 1 seat
    User.objects.create_user(
        username="only", email="only@seat.co", password="x", organization=org,
    )

    seats = SeatService()
    with pytest.raises(SeatLimitExceeded):
        seats.assert_can_add_user(org)

    AddonService().purchase(sub, _addon("user_pack_10"))
    assert seats.seat_limit(org) == 11
    seats.assert_can_add_user(org)                  # must not raise


def test_prices_and_quantities_are_frozen_at_purchase(catalogue):
    """A catalogue edit must not move an existing customer's ceiling."""
    from apps.billing.services.addon_service import AddonService
    from apps.billing.services.entitlements import effective_seat_quota

    org = _org("Frozen Addon Co")
    sub = _active_sub("business", org)
    AddonService().purchase(sub, _addon("user_pack_10"))

    a = _addon("user_pack_10")
    a.quantity = 999
    a.price = Decimal("9999.00")
    a.save(update_fields=["quantity", "price"])

    assert effective_seat_quota(sub).total == 20, (
        "a catalogue edit changed an existing customer's seat ceiling"
    )
