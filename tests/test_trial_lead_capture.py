"""Trial registration → lead capture (spec §A), and proof it broke nothing.

Registration is the highest-traffic flow in the product. Phase 1 widens it with
three newly-required fields, so most of this file is regression cover: the
happy path, each rejection, and — critically — that email verification,
organisation bootstrap and login still behave exactly as before.

The auto-captured block (§A.4) is asserted to be derived from the *request*,
never from POST data, because a client that can set its own `registered_ip`
or `campaign_source` makes both fields worthless.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.authentication.models import Organization
from apps.leads.models import TrialLeadProfile

pytestmark = pytest.mark.django_db

User = get_user_model()


VALID = {
    "full_name": "Mohammed Ahmed",
    "email": "newlead@example.com",
    "password": "StrongPass123!",
    "password_confirm": "StrongPass123!",
    "phone": "+966501234567",
    "country": "SA",
    "primary_benefit": "company",
}


def _post(client, **overrides):
    payload = {**VALID, **overrides}
    for key in [k for k, v in payload.items() if v is None]:
        payload.pop(key)
    return client.post(reverse("frontend:register"), data=payload)


# ── happy path ───────────────────────────────────────────────────────────────

def test_registration_succeeds_and_creates_lead_profile(client):
    resp = _post(client)
    assert resp.status_code == 200, resp.content[:400]

    user = User.objects.get(email="newlead@example.com")
    profile = TrialLeadProfile.objects.get(user=user)

    assert profile.country == "SA"
    assert profile.primary_benefit == TrialLeadProfile.PrimaryBenefit.COMPANY
    # phone lands on User, not duplicated onto the profile.
    assert user.phone == "+966501234567"


def test_optional_fields_are_stored_when_supplied(client):
    _post(
        client,
        city="Riyadh",
        company_name="Acme Trading",
        employee_count="11-50",
        sector="Retail",
        heard_about="linkedin",
    )
    profile = TrialLeadProfile.objects.get(user__email="newlead@example.com")
    assert profile.city == "Riyadh"
    assert profile.company_name == "Acme Trading"
    assert profile.employee_count == "11-50"
    assert profile.sector == "Retail"
    assert profile.heard_about == TrialLeadProfile.HeardAbout.LINKEDIN


def test_optional_fields_may_be_omitted_entirely(client):
    resp = _post(client)
    assert resp.status_code == 200
    profile = TrialLeadProfile.objects.get(user__email="newlead@example.com")
    assert profile.city == ""
    assert profile.heard_about == ""


# ── required-field rejection, one test per field ─────────────────────────────

@pytest.mark.parametrize("field", ["phone", "country", "primary_benefit"])
def test_missing_required_field_is_rejected(client, field):
    resp = _post(client, **{field: None})
    assert resp.status_code == 400, f"{field} was accepted while missing"
    assert not User.objects.filter(email="newlead@example.com").exists()


@pytest.mark.parametrize("field", ["phone", "country", "primary_benefit"])
def test_blank_required_field_is_rejected(client, field):
    resp = _post(client, **{field: ""})
    assert resp.status_code == 400, f"{field} was accepted while blank"
    assert not User.objects.filter(email="newlead@example.com").exists()


@pytest.mark.parametrize("bad_phone", ["12345", "abcdefgh", "++??"])
def test_invalid_phone_is_rejected(client, bad_phone):
    assert _post(client, phone=bad_phone).status_code == 400


def test_country_must_be_a_real_iso_code(client):
    """Widened to all of ISO 3166-1, but still validated.

    This test previously asserted that "US" was rejected, because Phase 1
    sourced the choices from Organization.Country (six GCC members). That was
    the reach defect, not the contract — a non-GCC prospect could not register
    at all. The obligation is unchanged (country is still required); only the
    permitted set widened. See tests/test_lead_country_reach.py.
    """
    assert _post(client, country="ZZ").status_code == 400
    assert _post(client, country="NOTACOUNTRY").status_code == 400


def test_primary_benefit_outside_the_choice_set_is_rejected(client):
    assert _post(client, primary_benefit="astronaut").status_code == 400


# ── transactional integrity ──────────────────────────────────────────────────

def test_failed_registration_leaves_no_user_and_no_organization(client):
    org_before = Organization.objects.count()
    _post(client, primary_benefit="not-a-choice")
    assert not User.objects.filter(email="newlead@example.com").exists()
    assert Organization.objects.count() == org_before


def test_lead_profile_failure_rolls_back_the_user(client, monkeypatch):
    """The whole point of one transaction across user + org + profile."""
    def boom(*args, **kwargs):
        raise RuntimeError("simulated profile failure")

    monkeypatch.setattr("apps.leads.services.create_trial_lead_profile", boom)
    with pytest.raises(RuntimeError):
        _post(client)

    assert not User.objects.filter(email="newlead@example.com").exists()
    assert not TrialLeadProfile.objects.filter(user__email="newlead@example.com").exists()


# ── auto-capture is server-derived, never client-supplied ────────────────────

def test_ip_and_device_are_captured_from_the_request(client):
    client.post(
        reverse("frontend:register"),
        data=VALID,
        HTTP_USER_AGENT="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) AppleWebKit/605.1",
        REMOTE_ADDR="203.0.113.9",
    )
    profile = TrialLeadProfile.objects.get(user__email="newlead@example.com")
    assert profile.registered_ip == "203.0.113.9"
    assert profile.device_type == TrialLeadProfile.DeviceType.MOBILE
    assert profile.language


def test_client_cannot_forge_the_autocaptured_block(client):
    """Posting these names must not overwrite the derived values."""
    client.post(
        reverse("frontend:register"),
        data={
            **VALID,
            "registered_ip": "1.2.3.4",
            "device_type": "tablet",
            "referral_source": "evil.example",
            "campaign_source": "forged",
        },
        REMOTE_ADDR="203.0.113.9",
        HTTP_USER_AGENT="Mozilla/5.0 (X11; Linux x86_64)",
    )
    profile = TrialLeadProfile.objects.get(user__email="newlead@example.com")
    assert profile.registered_ip == "203.0.113.9"
    assert profile.device_type == TrialLeadProfile.DeviceType.DESKTOP
    assert profile.referral_source == ""
    assert profile.campaign_source == ""


def test_referrer_is_reduced_to_a_host(client):
    client.post(
        reverse("frontend:register"),
        data=VALID,
        HTTP_REFERER="https://www.google.com/search?q=secret+search+terms&sxsrf=abc",
    )
    profile = TrialLeadProfile.objects.get(user__email="newlead@example.com")
    assert profile.referral_source == "www.google.com"
    assert "secret" not in profile.referral_source
    assert "?" not in profile.referral_source


def test_campaign_is_remembered_from_an_earlier_page_view(client):
    """utm arrives on the landing page, not on /register/."""
    client.get("/?utm_source=riyadh-expo")
    client.post(reverse("frontend:register"), data=VALID)
    profile = TrialLeadProfile.objects.get(user__email="newlead@example.com")
    assert profile.campaign_source == "riyadh-expo"


def test_first_campaign_wins(client):
    client.get("/?utm_source=first-touch")
    client.get("/pricing/?utm_source=second-touch")
    client.post(reverse("frontend:register"), data=VALID)
    profile = TrialLeadProfile.objects.get(user__email="newlead@example.com")
    assert profile.campaign_source == "first-touch"


# ── regression: the flows this must not break ────────────────────────────────

def test_organization_is_still_created_and_owned(client):
    _post(client, company_name="Acme Trading")
    user = User.objects.get(email="newlead@example.com")
    assert user.organization is not None
    assert user.role == User.Role.ADMIN, "org-owner role assignment must be unchanged"
    assert user.organization.country == "SA"


def test_email_verification_is_still_required_and_issued(client):
    resp = _post(client)
    body = resp.json()
    user = User.objects.get(email="newlead@example.com")

    assert user.email_verified_at is None, "registrant must start unverified"
    assert body.get("verification_required") or "verify" in str(body.get("redirect", ""))


def test_verified_user_can_still_log_in(client):
    from django.utils import timezone

    _post(client)
    user = User.objects.get(email="newlead@example.com")
    user.email_verified_at = timezone.now()
    user.save(update_fields=["email_verified_at"])

    resp = client.post(
        reverse("frontend:login"),
        data={"email": "newlead@example.com", "password": "StrongPass123!"},
    )
    assert resp.status_code == 200, resp.content[:300]


def test_register_page_still_renders_with_the_new_dropdowns(client):
    body = client.get(reverse("frontend:register")).content.decode()
    assert 'name="phone"' in body
    assert 'name="country"' in body
    assert 'name="primary_benefit"' in body
    # Country options come from Organization.Country, not a second list.
    for code, _label in Organization.Country.choices:
        assert f'value="{code}"' in body
