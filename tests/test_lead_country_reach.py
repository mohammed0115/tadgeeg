"""Lead country must not be limited to the billing jurisdictions.

Phase 1 made ``country`` required at registration and sourced its choices from
``Organization.Country`` — six GCC members that exist to pair one-to-one with
``Organization.Currency``. That silently narrowed the product: before Phase 1
country was not asked at all, so anyone could sign up; after it, a prospect in
Egypt, Jordan or the UK could not register.

Two different concepts had been conflated:

===========================  ==========================  ==================
field                        meaning                     correct scope
===========================  ==========================  ==================
``Organization.country``     billing jurisdiction         GCC only (currency)
``TrialLeadProfile.country`` marketing qualification      any country
===========================  ==========================  ==================

The precedent was already in the same app: ``ContactLead.country`` is a free
CharField, so the contact form always accepted any country.

The critical assertion here is not just "non-GCC can register" — it is that
widening the lead field did **not** push an unsupported code into
``Organization.country``. Django does not enforce ``choices`` at the database
level, so that would store a silently invalid billing jurisdiction and break
the currency mapping. Both halves are tested.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.authentication.models import Organization
from apps.leads.models import TrialLeadProfile

pytestmark = pytest.mark.django_db

User = get_user_model()

BASE = {
    "full_name": "Nadia Hassan",
    "email": "reach@example.com",
    "password": "StrongPass123!",
    "password_confirm": "StrongPass123!",
    "phone": "+201001234567",
    "primary_benefit": "company",
}


def _register(client, country, email="reach@example.com"):
    return client.post(
        reverse("frontend:register"), data={**BASE, "email": email, "country": country}
    )


# ── the regression ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("country", ["EG", "JO", "GB", "US", "IN"])
def test_non_gcc_prospect_can_register(client, country):
    """THE regression test. Fails on the pre-fix tree with HTTP 400."""
    resp = _register(client, country)
    assert resp.status_code == 200, (
        f"A prospect in {country} was refused registration: {resp.content[:300]!r}. "
        "Lead country must span every ISO country, not just billing jurisdictions."
    )
    assert User.objects.filter(email="reach@example.com").exists()


def test_non_gcc_country_is_stored_on_the_lead_profile(client):
    _register(client, "EG")
    profile = TrialLeadProfile.objects.get(user__email="reach@example.com")
    assert profile.country == "EG"


def test_non_gcc_country_does_not_leak_into_billing_jurisdiction(client):
    """The trap: Django does not enforce choices at the DB level.

    A non-GCC lead country must NOT be written to Organization.country, which
    is paired with Organization.Currency. Recording a false jurisdiction is
    worse than recording none.
    """
    _register(client, "EG")
    org = User.objects.get(email="reach@example.com").organization

    assert org.country != "EG", "a non-GCC code leaked into the billing jurisdiction"
    assert org.country in Organization.Country.values, (
        f"Organization.country holds {org.country!r}, which is not a valid "
        "billing jurisdiction — the currency mapping is now broken."
    )
    # And the currency still maps.
    from apps.authentication.services.organization_setup import COUNTRY_CURRENCY_MAP

    assert org.country in COUNTRY_CURRENCY_MAP


# ── no behaviour change for existing markets ─────────────────────────────────

@pytest.mark.parametrize("country", ["SA", "AE", "BH", "KW", "OM", "QA"])
def test_gcc_country_still_propagates_to_the_organization(client, country):
    _register(client, country)
    user = User.objects.get(email="reach@example.com")
    assert user.organization.country == country, (
        "GCC registrants must keep propagating their country to billing — "
        "this is existing behaviour and must not regress."
    )
    assert user.trial_lead_profile.country == country


def test_gcc_registration_still_maps_currency(client):
    _register(client, "AE")
    org = User.objects.get(email="reach@example.com").organization
    assert org.currency == Organization.Currency.AED


# ── the obligation is unchanged; only the list widened ───────────────────────

def test_country_is_still_required(client):
    payload = dict(BASE)
    resp = client.post(reverse("frontend:register"), data=payload)
    assert resp.status_code == 400
    assert not User.objects.filter(email="reach@example.com").exists()


def test_blank_country_is_still_rejected(client):
    assert _register(client, "").status_code == 400


def test_garbage_country_is_still_rejected(client):
    """Widened is not unvalidated — it must still be a real ISO code."""
    assert _register(client, "ZZ").status_code == 400
    assert _register(client, "XX").status_code == 400
    assert _register(client, "NOTACOUNTRY").status_code == 400


# ── the billing enum itself must not have been widened ───────────────────────

def test_organization_country_enum_is_unchanged():
    """Asserted explicitly so a future edit to the billing enum trips here.

    These six pair one-to-one with Organization.Currency. Adding a member
    without adding its currency would break organisation bootstrap.
    """
    assert set(Organization.Country.values) == {"SA", "AE", "BH", "KW", "OM", "QA"}

    from apps.authentication.services.organization_setup import COUNTRY_CURRENCY_MAP

    assert set(COUNTRY_CURRENCY_MAP) == set(Organization.Country.values), (
        "every billing jurisdiction must map to a currency"
    )


# ── downstream surfaces tolerate a non-GCC value ─────────────────────────────

def test_dashboard_grouping_handles_a_non_gcc_country(client, django_user_model):
    from apps.leads.trial_selectors import build_summary, get_dashboard_queryset

    _register(client, "EG", email="eg@example.com")
    _register(client, "SA", email="sa@example.com")

    summary = build_summary(get_dashboard_queryset())
    counts = {row["value"]: row["count"] for row in summary["by_country"]}
    assert counts.get("EG") == 1
    assert counts.get("SA") == 1


def test_exports_handle_a_non_gcc_country(client):
    from io import BytesIO
    from io import StringIO

    import openpyxl
    from django.core.management import call_command

    call_command("seed_billing_plans", stdout=StringIO())
    _register(client, "EG", email="eg@example.com")

    staff = User.objects.create_user(
        email="staff@tadgeeg.test", password="StrongPass123!", full_name="Staff",
    )
    staff.is_staff = True
    staff.save(update_fields=["is_staff"])
    client.force_login(staff)

    xlsx = client.get("/api/platform-admin/trial-users/export.xlsx")
    assert xlsx.status_code == 200
    sheet = openpyxl.load_workbook(BytesIO(xlsx.content)).active
    values = [c for row in sheet.iter_rows(values_only=True) for c in row if c]
    assert "EG" in values

    pdf = client.get("/api/platform-admin/trial-users/export.pdf")
    assert pdf.status_code in (200, 503)
