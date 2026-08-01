"""The calculator recommends from the backend, and holds no rules of its own.

§K and §M require a single source of truth for pricing and limits. The failure
mode they are guarding against is a page that carries the ladder in JavaScript:
it works on the day it ships and starts lying the first time someone edits the
catalogue, because nothing connects the two.

So the assertions come in two kinds — that the recommendation is correct, and
that the page contains no thresholds to be wrong with. The second is asserted
by absence, which is the only way to check that something is not there.
"""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command

pytestmark = pytest.mark.django_db

URL = "/billing/recommend/"
TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "landing" / "pricing.html"


@pytest.fixture
def plans(db):
    call_command("seed_billing_plans", stdout=StringIO())


def _rec(client, users, invoices):
    resp = client.get(URL, {"users": users, "invoices": invoices})
    assert resp.status_code == 200, resp.status_code
    return resp.json()


# ── the recommendation ───────────────────────────────────────────────────────

def test_the_worked_example_from_the_spec(client, plans):
    """§K: 10 users + 2,000 invoices/month → Business → 599 SAR/month."""
    data = _rec(client, 10, 2000)
    assert data["plan_code"] == "business"
    assert data["price"] == "599.00"
    assert data["currency"] == "SAR"


@pytest.mark.parametrize("users,invoices,expected", [
    (1, 50, "starter"),           # 1 seat · 100 invoices
    (3, 500, "basic"),            # exactly at basic's ceilings
    (10, 2000, "business"),
    (25, 5000, "professional"),
    (26, 5000, "enterprise"),     # one seat over professional
    (25, 5001, "enterprise"),     # one invoice over professional
])
def test_the_cheapest_plan_that_fits_both_dimensions(client, plans, users, invoices, expected):
    assert _rec(client, users, invoices)["plan_code"] == expected


def test_a_plan_must_fit_BOTH_dimensions(client, plans):
    """Enough invoices but too few seats is not a fit.

    Recommending on one dimension would send someone to a checkout that cannot
    serve them.
    """
    # Basic has 500 invoices but only 3 seats.
    data = _rec(client, 10, 400)
    assert data["plan_code"] == "business", (
        "recommended a plan that covers the invoices but not the seats"
    )


def test_beyond_the_ladder_returns_a_custom_quote(client, plans):
    data = _rec(client, 500, 999_999)
    assert data["is_custom_quote"] is True
    assert data["price"] is None


def test_the_trial_is_never_recommended(client, plans):
    """A trial is time-boxed and one-per-organisation — not an answer to
    "which plan should I buy"."""
    assert _rec(client, 1, 5)["plan_code"] != "free_trial"


def test_accounting_plans_are_never_recommended(client, plans):
    """They are priced on a client-companies dimension the platform cannot
    enforce (ADR 0006). Recommending one would promise that capability."""
    for users, invoices in [(10, 10000), (25, 30000), (10, 9000)]:
        assert not (_rec(client, users, invoices)["plan_code"] or "").startswith("accounting")


def test_nonsense_input_does_not_error(client, plans):
    for params in ({"users": "abc", "invoices": "-5"}, {}, {"users": -1}):
        assert client.get(URL, params).status_code == 200


# ── the endpoint's shape ─────────────────────────────────────────────────────

def test_the_endpoint_is_public(client, plans):
    """A prospect asks this before they have an account."""
    assert client.get(URL, {"users": 5, "invoices": 100}).status_code == 200


def test_the_endpoint_is_throttled(plans):
    from apps.billing.views import pricing_recommendation

    assert getattr(pricing_recommendation, "throttle_scope", None) == "pricing_calculator"

    from django.conf import settings

    rates = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
    assert "pricing_calculator" in rates, "the scope has no configured rate"


def test_the_endpoint_exposes_nothing_beyond_the_public_catalogue(client, plans):
    data = _rec(client, 10, 2000)
    allowed = {
        "plan_code", "plan_name_en", "plan_name_ar", "price", "currency",
        "is_custom_quote", "user_limit", "invoice_limit", "requested",
    }
    assert set(data) <= allowed, f"unexpected fields: {set(data) - allowed}"


# ── the page holds no business rules — asserted by absence ───────────────────

def test_the_page_contains_no_pricing_thresholds():
    """§M: the calculator holds no business rules.

    If the ladder were duplicated in JavaScript, the page and the engine would
    drift apart at the first catalogue edit. The plan prices must not appear as
    literals in the calculator's script.
    """
    src = TEMPLATE.read_text(encoding="utf-8")
    start = src.index("function planCalculator()")
    script = src[start:]

    for literal in ("149", "299", "599", "999", "990", "1990"):
        assert literal not in script, (
            f"the calculator script contains the price literal {literal!r} — "
            f"the recommendation must come from the backend, not from a copy "
            f"of the ladder in the page"
        )
    for name in ("starter", "basic", "business", "professional", "enterprise"):
        assert f"'{name}'" not in script and f'"{name}"' not in script, (
            f"the calculator script hardcodes the plan code {name!r}"
        )


def test_the_page_asks_the_backend(client, plans):
    body = client.get("/pricing/").content.decode()
    assert "/billing/recommend/" in body, "the page never calls the endpoint"
    assert "planCalculator()" in body


def test_the_calculator_debounces_slider_input():
    """Sliders fire continuously against a throttled public endpoint."""
    src = TEMPLATE.read_text(encoding="utf-8")
    assert "clearTimeout(this._timer)" in src, "no debounce; dragging would spam"


def test_alpine_loads_from_safe_static_with_cdn_only_as_fallback():
    """2B shipped a CDN-only load on a public page and corrected it."""
    src = TEMPLATE.read_text(encoding="utf-8")
    assert "safe_static 'vendor/alpine.min.js'" in src
    assert "onerror=" in src, "no local-first load with a CDN fallback"


# ── §I.4 — savings are derived, never written ────────────────────────────────

@pytest.fixture
def catalogue(db):
    call_command("seed_billing_plans", stdout=StringIO())
    call_command("seed_addons", stdout=StringIO())


def test_the_advertised_savings_match_the_spec_when_computed(catalogue):
    """§I.4 claims 27% on user packs and 40% per invoice.

    Computed from the seeded prices rather than asserted against a constant the
    page also reads — that would only prove two copies agree.
    """
    from apps.billing.services.plan_service import addon_savings

    s = addon_savings()
    assert s["users_percent"] == 27
    assert s["invoices_percent"] == 40


def test_savings_follow_a_price_change_instead_of_going_stale(catalogue):
    """The reason they are computed at all.

    Make the 25-seat pack far cheaper and the advertised saving must move. A
    hardcoded percentage would keep claiming the old number.
    """
    from decimal import Decimal

    from apps.billing.models import Addon
    from apps.billing.services.plan_service import addon_savings

    before = addon_savings()["users_percent"]

    pack = Addon.objects.get(code="user_pack_25")
    pack.price = Decimal("150.00")          # 25 seats for the price of five
    pack.save(update_fields=["price"])

    after = addon_savings()["users_percent"]
    assert after > before, (
        f"the advertised saving did not follow the price ({before}% -> {after}%)"
    )


def test_the_page_renders_no_hardcoded_savings_percentage():
    """Asserted by absence: the literals must not appear in the template."""
    src = TEMPLATE.read_text(encoding="utf-8")
    body = src[src.index("<body"):]
    for literal in ("27%", "40%", "٢٧٪", "٤٠٪"):
        assert literal not in body, (
            f"the pricing page hardcodes {literal!r} — §I.4 requires it be "
            f"computed from the add-on prices at render time"
        )


def test_the_savings_claim_disappears_when_there_is_nothing_to_claim(catalogue):
    """A claim with no arithmetic behind it must not linger."""
    from apps.billing.choices import AddonDimension
    from apps.billing.models import Addon
    from apps.billing.services.plan_service import addon_savings

    Addon.objects.filter(dimension=AddonDimension.USERS).exclude(
        code="user_extra_1",
    ).update(is_active=False)

    assert addon_savings()["users_percent"] is None


# ── 2.3 — accounting plans promise nothing the platform cannot enforce ───────

def test_accounting_cards_do_not_advertise_a_company_allowance(client, catalogue):
    """§J prices these on 20 / 50 / unlimited client companies.

    3A established the tenant architecture cannot express one subscription
    covering many organizations (ADR 0006), so that dimension is not built and
    cannot be enforced. A number on a pricing page is a promise, so the page
    must not show one.
    """
    body = client.get("/pricing/").content.decode()

    for claim in ("20 شركة", "50 شركة", "20 companies", "50 companies",
                  "client companies", "شركة عميلة"):
        assert claim not in body, (
            f"the pricing page advertises {claim!r}, a company allowance "
            f"nothing in the system can enforce"
        )


def test_accounting_plans_still_show_their_real_limits(client, catalogue):
    """Omitting the unenforceable dimension must not hide the real ones."""
    body = client.get("/pricing/").content.decode()
    assert "990" in body and "1990" in body          # §J prices
    assert "10000" in body or "10,000" in body       # accounting_partner invoices
