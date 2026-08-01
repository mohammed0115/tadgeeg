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
