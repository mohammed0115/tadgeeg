"""PLATFORM-ADMIN-CONSISTENCY-A — overview and CRM share ONE data source for the
org count (no "0 vs 4" contradiction), Arabic UI is not mixed with English, and
the identity is unified. HTML assertions (visual confirmation still on server).
"""
import pytest
from django.test import Client
from django.urls import reverse

from apps.authentication.models import Organization

pytestmark = pytest.mark.django_db

_OVERVIEW = reverse("platform_admin:dashboard")
_CRM = reverse("platform_admin:crm:dashboard")


def _get(user, url, lang="en"):
    c = Client()
    c.force_login(user)
    return c.get(url, HTTP_ACCEPT_LANGUAGE=lang)


def _make_orgs(n):
    for i in range(n):
        Organization.objects.create(name=f"Org {i}", country=Organization.Country.SAUDI_ARABIA)


def test_overview_org_count_is_server_rendered_not_zero(superuser):
    Organization.objects.all().delete()
    _make_orgs(3)
    html = _get(superuser, _OVERVIEW, lang="en").content.decode("utf-8")
    # Server-rendered real count present; never the JS-only "0".
    assert ">3<" in html


def test_overview_has_no_leaked_developer_comment(superuser, organization):
    # A multi-line {# #} comment is NOT stripped by Django and leaked into the
    # rendered card. The org number card must contain the number only.
    for lang in ("en", "ar"):
        html = _get(superuser, _OVERVIEW, lang=lang).content.decode("utf-8")
        for leak in ["Server-rendered", "canonical source", "Alpine only",
                     "never blank it", "refines it"]:
            assert leak not in html, f"Leaked developer text in overview ({lang}): {leak}"


def test_overview_and_crm_show_same_org_count(superuser):
    Organization.objects.all().delete()
    _make_orgs(3)
    overview = _get(superuser, _OVERVIEW, lang="en").content.decode("utf-8")
    crm = _get(superuser, _CRM, lang="en").content.decode("utf-8")
    # Both render 3 from the same canonical source — no 0-vs-N contradiction.
    assert ">3<" in overview
    assert ">3<" in crm


def test_arabic_crm_dashboard_has_no_english_labels(owner_user, organization):
    html = _get(owner_user, _CRM, lang="ar").content.decode("utf-8")
    for english in ["Customer Operations", "Pending payments",
                    "Active subscriptions", "Open tickets"]:
        assert english not in html, f"English leaked into Arabic UI: {english}"
    # Arabic actually rendered.
    assert "عمليات العملاء" in html


def test_english_crm_dashboard_shows_english(owner_user, organization):
    html = _get(owner_user, _CRM, lang="en").content.decode("utf-8")
    assert "Customer Operations" in html


def test_arabic_overview_uses_unified_identity_not_raw_english(superuser):
    html = _get(superuser, _OVERVIEW, lang="ar").content.decode("utf-8")
    # The old hardcoded "Get Solution Internal" is gone; identity is translated.
    assert "Get Solution Internal" not in html
    assert "لوحة إدارة Get Solution" in html


def test_arabic_crm_nav_readonly_is_translated(owner_user, organization):
    html = _get(owner_user, _CRM, lang="ar").content.decode("utf-8")
    assert "Read-only" not in html
    assert "للقراءة فقط" in html


# ── unaffected behavior ───────────────────────────────────────────────────────
def test_overview_200_for_platform_staff(superuser):
    assert _get(superuser, _OVERVIEW).status_code == 200


def test_regular_user_denied_on_overview(regular_user):
    assert _get(regular_user, _OVERVIEW).status_code in (403, 302)


def test_organizations_still_redirects_to_crm(owner_user):
    c = Client(); c.force_login(owner_user)
    resp = c.get(reverse("platform_admin:organizations"))
    assert resp.status_code == 302
    assert reverse("platform_admin:crm:customers") in resp["Location"]
