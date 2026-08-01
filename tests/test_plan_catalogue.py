"""Plan catalogue, limit dimensions and backend enforcement (Phase 3A, §H/§J).

The single most important test here is
``test_an_existing_active_subscription_is_untouched_by_a_catalogue_edit``:
this phase changes published prices, and a catalogue edit must never silently
reprice or re-limit somebody who is already paying.

Prices and limits are asserted **literally**. Reading the same constant the
code reads would prove only that the code is self-consistent, not that it
matches the spec.
"""

from __future__ import annotations

from decimal import Decimal
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.utils import timezone

from apps.authentication.models import Organization
from apps.billing.choices import ACCOUNTING_PLAN_CODES, PlanCode, SubscriptionStatus
from apps.billing.models import OrganizationSubscription, Plan
from apps.billing.services.plan_service import list_checkout_plans, list_purchasable_plans
from apps.billing.services.quota_service import (
    QuotaService,
    SeatLimitExceeded,
    SeatService,
)

pytestmark = pytest.mark.django_db

User = get_user_model()


#: The spec tables, transcribed. (code, price, users, invoices, custom_quote)
#: None = unlimited / custom quote.
SPEC = [
    ("free_trial",              Decimal("0.00"),    1,    20, False),
    ("starter",                 Decimal("149.00"),  1,   100, False),
    ("basic",                   Decimal("299.00"),  3,   500, False),
    ("business",                Decimal("599.00"), 10,  2000, False),
    ("professional",            Decimal("999.00"), 25,  5000, False),
    ("enterprise",              None,            None,  None, True),
    ("accounting_partner",      Decimal("990.00"), 10, 10000, False),
    ("accounting_professional", Decimal("1990.00"),25, 30000, False),
    ("accounting_enterprise",   None,            None,  None, True),
]


@pytest.fixture
def seeded(db):
    call_command("seed_billing_plans", stdout=StringIO())


# ═══ catalogue ═══════════════════════════════════════════════════════════════

def test_nine_plans_are_seeded(seeded):
    assert Plan.objects.count() == 9
    assert set(Plan.objects.values_list("code", flat=True)) == {c for c, *_ in SPEC}


@pytest.mark.parametrize("code,price,users,invoices,custom", SPEC)
def test_plan_matches_the_spec_exactly(seeded, code, price, users, invoices, custom):
    plan = Plan.objects.get(code=code)
    assert plan.price == price, f"{code}: price {plan.price} != spec {price}"
    assert plan.user_limit == users, f"{code}: user_limit {plan.user_limit} != spec {users}"
    assert plan.invoice_limit == invoices, f"{code}: invoice_limit {plan.invoice_limit} != spec {invoices}"
    assert plan.is_custom_quote is custom
    assert plan.currency == "SAR"


def test_seed_is_idempotent(seeded):
    call_command("seed_billing_plans", stdout=StringIO())
    assert Plan.objects.count() == 9


def test_plans_are_ordered_by_the_commercial_ladder(seeded):
    codes = [p.code for p in list_purchasable_plans()]
    assert codes == [c for c, *_ in SPEC]


def test_accounting_plans_are_identifiable_as_a_family(seeded):
    assert ACCOUNTING_PLAN_CODES == {
        "accounting_partner", "accounting_professional", "accounting_enterprise",
    }


# ═══ THE money test ══════════════════════════════════════════════════════════

def test_an_existing_active_subscription_is_untouched_by_a_catalogue_edit(seeded):
    """The most important test in this phase.

    A customer on an ACTIVE subscription keeps the limits they were sold, even
    after the catalogue is re-seeded with different figures. The guarantee is
    structural: OrganizationSubscription snapshots the limits at activation
    (subscription_service.activate_subscription), so the catalogue and the
    contract are separate rows.
    """
    org = Organization.objects.create(name="Existing Customer")
    plan = Plan.objects.get(code=PlanCode.STARTER)

    now = timezone.now()
    sub = OrganizationSubscription.objects.create(
        organization=org, plan=plan, status=SubscriptionStatus.ACTIVE,
        starts_at=now, ends_at=now + timezone.timedelta(days=30),
        invoice_limit=plan.invoice_limit, user_limit=plan.user_limit,
        used_invoices=17,
    )
    sold_invoice_limit = sub.invoice_limit
    sold_user_limit = sub.user_limit

    # Ops edits the catalogue — a drastic change, to make any leak obvious.
    Plan.objects.filter(code=PlanCode.STARTER).update(
        price=Decimal("9999.00"), invoice_limit=1, user_limit=1,
    )

    sub.refresh_from_db()
    assert sub.invoice_limit == sold_invoice_limit, "a catalogue edit re-limited a paying customer"
    assert sub.user_limit == sold_user_limit, "a catalogue edit changed a customer's seats"
    assert sub.used_invoices == 17, "usage was disturbed"
    assert sub.status == SubscriptionStatus.ACTIVE


def test_reseeding_does_not_disturb_existing_subscription_rows(seeded):
    """Running the seed command again must not touch subscriptions at all."""
    org = Organization.objects.create(name="Customer")
    plan = Plan.objects.get(code=PlanCode.BUSINESS)
    now = timezone.now()
    sub = OrganizationSubscription.objects.create(
        organization=org, plan=plan, status=SubscriptionStatus.ACTIVE,
        starts_at=now, ends_at=now + timezone.timedelta(days=30),
        invoice_limit=500, user_limit=3, used_invoices=42,   # deliberately OLD figures
    )
    before = (sub.invoice_limit, sub.user_limit, sub.used_invoices, sub.updated_at)

    call_command("seed_billing_plans", stdout=StringIO())

    sub.refresh_from_db()
    assert (sub.invoice_limit, sub.user_limit, sub.used_invoices) == before[:3]


def test_quota_enforcement_uses_the_snapshot_not_the_catalogue(seeded):
    """Enforcement must read the subscription's frozen limit."""
    org = Organization.objects.create(name="Snapshot Customer")
    plan = Plan.objects.get(code=PlanCode.STARTER)
    now = timezone.now()
    OrganizationSubscription.objects.create(
        organization=org, plan=plan, status=SubscriptionStatus.ACTIVE,
        starts_at=now, ends_at=now + timezone.timedelta(days=30),
        invoice_limit=100, used_invoices=99,
    )
    # Catalogue says 1; the customer bought 100.
    Plan.objects.filter(code=PlanCode.STARTER).update(invoice_limit=1)

    decision = QuotaService().can_audit(org, quantity=1)
    assert decision["allowed"] is True, "enforcement read the catalogue instead of the contract"


# ═══ custom quote ════════════════════════════════════════════════════════════

@pytest.mark.parametrize("code", ["enterprise", "accounting_enterprise"])
def test_custom_quote_plans_have_no_price_and_are_not_purchasable(seeded, code):
    plan = Plan.objects.get(code=code)
    assert plan.price is None, "a custom-quote plan must not carry a list price"
    assert plan.price != Decimal("0.00"), "0.00 would read as FREE"
    assert plan.is_custom_quote is True
    assert plan.is_purchasable is False


def test_checkout_list_excludes_custom_quote_plans(seeded):
    codes = [p.code for p in list_checkout_plans()]
    assert "enterprise" not in codes
    assert "accounting_enterprise" not in codes
    assert len(codes) == 7


@pytest.mark.parametrize("code", ["enterprise", "accounting_enterprise"])
def test_custom_quote_plan_cannot_be_selected_through_checkout(client, seeded, code):
    """Refused SERVER-SIDE, not merely hidden in the UI."""
    org = Organization.objects.create(name="Would-be buyer")
    user = User.objects.create_user(
        email=f"buyer-{code}@example.com", password="StrongPass123!",
        full_name="Buyer", role=User.Role.ADMIN, organization=org,
    )
    user.email_verified_at = timezone.now()
    user.save(update_fields=["email_verified_at"])
    client.force_login(user)

    resp = client.post("/billing/select-plan/", data={"plan_code": code},
                       content_type="application/json")
    assert resp.status_code == 409, resp.content[:300]
    assert resp.json()["code"] == "contact_sales"
    assert not OrganizationSubscription.objects.filter(organization=org).exists()


def test_plan_action_reports_contact_sales_for_custom_quote(seeded):
    from apps.billing.views import plan_action

    plan = Plan.objects.get(code=PlanCode.ENTERPRISE)
    action = plan_action(plan, None, used_trial=False, now=timezone.now())
    assert action == "contact_sales"


def test_plan_action_does_not_crash_comparing_a_null_price(seeded):
    """price became nullable; `None > Decimal` would raise TypeError."""
    from apps.billing.views import plan_action

    org = Organization.objects.create(name="Ranker")
    starter = Plan.objects.get(code=PlanCode.STARTER)
    now = timezone.now()
    sub = OrganizationSubscription.objects.create(
        organization=org, plan=starter, status=SubscriptionStatus.ACTIVE,
        starts_at=now, ends_at=now + timezone.timedelta(days=30), invoice_limit=100,
    )
    for plan in Plan.objects.all():
        plan_action(plan, sub, used_trial=False, now=now)   # must not raise


# ═══ unlimited is not zero ═══════════════════════════════════════════════════

def test_unlimited_is_null_not_zero(seeded):
    plan = Plan.objects.get(code=PlanCode.ENTERPRISE)
    assert plan.invoice_limit is None
    assert plan.invoice_limit != 0, "0 means 'no allowance' — the opposite of unlimited"
    assert Plan.has_limit(plan.invoice_limit) is False
    assert Plan.has_limit(0) is True, "zero IS a limit — a very restrictive one"


def test_unlimited_subscription_bypasses_invoice_enforcement(seeded):
    org = Organization.objects.create(name="Unlimited Customer")
    plan = Plan.objects.get(code=PlanCode.ENTERPRISE)
    now = timezone.now()
    OrganizationSubscription.objects.create(
        organization=org, plan=plan, status=SubscriptionStatus.ACTIVE,
        starts_at=now, ends_at=now + timezone.timedelta(days=30),
        invoice_limit=None, user_limit=None, used_invoices=10_000_000,
    )
    decision = QuotaService().can_audit(org, quantity=5000)
    assert decision["allowed"] is True
    assert decision["remaining"] is None, "unlimited must report None, not a sentinel number"


def test_zero_limit_refuses_everything(seeded):
    """The other end of the convention: 0 really does mean nothing allowed."""
    org = Organization.objects.create(name="Exhausted")
    plan = Plan.objects.get(code=PlanCode.STARTER)
    now = timezone.now()
    OrganizationSubscription.objects.create(
        organization=org, plan=plan, status=SubscriptionStatus.ACTIVE,
        starts_at=now, ends_at=now + timezone.timedelta(days=30),
        invoice_limit=0, used_invoices=0,
    )
    assert QuotaService().can_audit(org, quantity=1)["allowed"] is False


def test_unlimited_survives_json_serialisation(seeded):
    """Rule 3: a type change must be checked on the JSON path."""
    from apps.billing.serializers import PlanSerializer

    data = PlanSerializer(Plan.objects.get(code=PlanCode.ENTERPRISE)).data
    assert data["invoice_limit"] is None
    assert data["user_limit"] is None
    assert data["price"] is None
    assert data["is_custom_quote"] is True

    import json
    json.dumps(data)                      # must not raise


# ═══ seat enforcement ════════════════════════════════════════════════════════

def _org_with_plan(code, *, seats_used=0, seeded_plans=True):
    org = Organization.objects.create(name=f"Seats {code} {seats_used}")
    plan = Plan.objects.get(code=code)
    now = timezone.now()
    OrganizationSubscription.objects.create(
        organization=org, plan=plan, status=SubscriptionStatus.ACTIVE,
        starts_at=now, ends_at=now + timezone.timedelta(days=30),
        invoice_limit=plan.invoice_limit, user_limit=plan.user_limit,
    )
    for i in range(seats_used):
        User.objects.create_user(
            email=f"seat{i}-{org.id}@example.com", password="StrongPass123!",
            full_name=f"Seat {i}", organization=org,
        )
    return org


def test_seats_below_the_limit_are_allowed(seeded):
    org = _org_with_plan(PlanCode.BASIC, seats_used=2)      # limit 3
    decision = SeatService().can_add_user(org)
    assert decision["allowed"] is True
    assert decision["limit"] == 3
    assert decision["used"] == 2


def test_at_the_limit_the_next_seat_is_refused(seeded):
    org = _org_with_plan(PlanCode.BASIC, seats_used=3)      # limit 3, full
    decision = SeatService().can_add_user(org)
    assert decision["allowed"] is False
    assert decision["reason"] == "seat_limit_exceeded"


def test_seat_refusal_names_the_limit_that_was_hit(seeded):
    org = _org_with_plan(PlanCode.STARTER, seats_used=1)    # limit 1
    with pytest.raises(SeatLimitExceeded) as exc:
        SeatService().assert_can_add_user(org)
    message = str(exc.value)
    assert "User limit" in message, "the error must say WHICH limit — seats, not invoices"
    assert "1" in message


def test_unlimited_plan_bypasses_seat_enforcement(seeded):
    org = _org_with_plan(PlanCode.ENTERPRISE, seats_used=500)
    decision = SeatService().can_add_user(org)
    assert decision["allowed"] is True
    assert decision["limit"] is None
    assert decision["remaining"] is None


def test_inactive_users_do_not_consume_seats(seeded):
    org = _org_with_plan(PlanCode.STARTER, seats_used=1)
    User.objects.filter(organization=org).update(is_active=False)
    assert SeatService().can_add_user(org)["allowed"] is True


def test_seat_limit_is_enforced_at_the_api(client, seeded):
    """Domain-layer enforcement, reached through the real endpoint."""
    org = _org_with_plan(PlanCode.STARTER, seats_used=0)    # limit 1
    admin = User.objects.create_user(
        email="orgadmin@example.com", password="StrongPass123!",
        full_name="Org Admin", role=User.Role.ADMIN, organization=org,
    )
    admin.email_verified_at = timezone.now()
    admin.save(update_fields=["email_verified_at"])
    client.force_login(admin)

    # The admin already occupies the single seat.
    resp = client.post(
        "/api/v1/auth/users/",
        data={"email": "colleague@example.com", "full_name": "Colleague",
              "role": "junior_auditor", "password": "StrongPass123!"},
        content_type="application/json",
    )
    assert resp.status_code == 400, resp.content[:300]
    # The project wraps DRF errors in {"error": true, "detail": {...}} via
    # core.utils.exceptions.custom_exception_handler, so the field key lives
    # one level down.
    body = resp.json()
    assert "user_limit" in body["detail"], body
    assert "User limit reached" in body["detail"]["user_limit"]
    assert not User.objects.filter(email="colleague@example.com").exists()


# ═══ pricing page ════════════════════════════════════════════════════════════

def test_pricing_page_renders_all_nine_plans(client, seeded):
    body = client.get("/pricing/").content.decode()
    for code, *_ in SPEC:
        assert f'data-plan="{code}"' in body, f"{code} is missing from /pricing/"


def test_pricing_page_shows_exact_prices(client, seeded):
    body = client.get("/pricing/").content.decode()
    for price in ("149", "299", "599", "999", "990", "1990"):
        assert price in body, f"price {price} missing from the pricing page"


def test_custom_quote_plans_show_no_purchase_button(client, seeded):
    """A plan with no list price must never offer a way to buy it."""
    import re

    body = client.get("/pricing/").content.decode()
    for code in ("enterprise", "accounting_enterprise"):
        block = re.search(
            rf'data-plan="{code}".*?</article>', body, re.S,
        )
        assert block, f"{code} card not found"
        card = block.group(0)
        assert "Custom quote" in card or "حسب العرض" in card
        assert "/billing/plans/" not in card, f"{code} offered a purchase path"
        assert "Subscribe" not in card


def test_accounting_plans_are_in_their_own_section(client, seeded):
    body = client.get("/pricing/").content.decode()
    assert "accounting" in body.lower()
    # The section marker from §L.4.
    assert "Competitive advantage" in body or "ميزة تنافسية" in body


def test_business_badge_stays_on_business(client, seeded):
    """Exactly one card is featured, and it is `business`.

    The badge itself is drawn by `.card.featured::before` in CSS, so asserting
    on its *text* would pass while a second card also carried the class — which
    is what happened when Phase 3A added a duplicate inline badge and shipped
    two "Most popular" labels on the same card. The class is the mechanism, so
    the class is what this pins.
    """
    import re

    body = client.get("/pricing/").content.decode()
    featured = re.findall(r'<article class="card ([^"]*)"[^>]*data-plan="([^"]+)"', body)
    marked = [code for classes, code in featured if "featured" in classes.split()]
    assert marked == ["business"], f"expected only business featured, got {marked}"

    # And the badge text is not also hard-coded into the markup (CSS draws it).
    card = re.search(r'data-plan="business".*?</article>', body, re.S).group(0)
    assert "Most popular" not in card and "الأكثر شيوعًا" not in card, (
        "the badge is rendered twice: once by .card.featured::before and once "
        "inline in the template"
    )


def test_unlimited_renders_as_words_not_none(client, seeded):
    """NULL limits must not leak as 'None' or an empty string."""
    body = client.get("/pricing/").content.decode()
    assert "None invoices" not in body
    assert "None users" not in body
    assert "Unlimited" in body or "غير محدود" in body


# ═══ STEP 0 — review console permissions ═════════════════════════════════════

def test_review_console_renders_for_staff(client, seeded):
    staff = User.objects.create_user(
        email="reviewer@tadgeeg.test", password="StrongPass123!", full_name="Reviewer",
    )
    staff.is_staff = True
    staff.save(update_fields=["is_staff"])
    client.force_login(staff)

    resp = client.get("/platform-admin/partner-applications/")
    assert resp.status_code == 200
    assert "applicationsConsole()" in resp.content.decode()


def test_review_console_rejects_org_admin_role(client, seeded):
    from apps.billing.services.subscription_service import SubscriptionService

    org = Organization.objects.create(name="Customer Co")
    user = User.objects.create_user(
        email="customer-console@example.com", password="StrongPass123!",
        full_name="Customer", role=User.Role.ADMIN, organization=org,
    )
    SubscriptionService().create_free_trial(org)
    client.force_login(user)
    assert client.get("/platform-admin/partner-applications/").status_code in (302, 403)


def test_review_console_rejects_anonymous(client, seeded):
    resp = client.get("/platform-admin/partner-applications/")
    assert resp.status_code in (302, 403)


@pytest.mark.django_db
def test_pricing_page_has_no_untranslated_strings_in_arabic(client, seeded):
    """Arabic is this product's primary language, not a localisation of English.

    Phase 3A added ten customer-facing strings (custom quote, unlimited, the
    accounting section) and every one of them rendered in English on the Arabic
    page until the catalogue was updated — visible to any Arabic visitor. This
    pins the English markers out of the Arabic render so the next new string
    fails here instead of on the live site.
    """
    from django.utils import translation

    with translation.override("ar"):
        body = client.get("/pricing/", HTTP_ACCEPT_LANGUAGE="ar").content.decode()

    forbidden = [
        "Custom quote", "Unlimited users", "Unlimited invoices",
        "Unlimited invoice audits", "Contact sales", "Competitive advantage",
        "Plans for accounting firms",
        "Built for practices auditing on behalf of multiple clients.",
    ]
    leaked = [s for s in forbidden if s in body]
    assert not leaked, (
        f"untranslated English on the Arabic pricing page: {leaked}. "
        f"Add them to locale/ar/LC_MESSAGES/django.po and run compilemessages."
    )
    # …and the Arabic actually arrived, so an empty page cannot pass the above.
    assert "تسعير حسب العرض" in body
    assert "باقات مكاتب المحاسبة" in body
