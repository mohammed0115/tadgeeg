"""PLATFORM-ADMIN-CONSISTENCY-A — overview and CRM share ONE data source for the
org count (no "0 vs 4" contradiction), Arabic UI is not mixed with English, and
the identity is unified. HTML assertions (visual confirmation still on server).
"""
import pathlib

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import translation

from apps.authentication.models import Organization
from apps.platform_admin.models import CustomerActivity
from apps.platform_admin.templatetags.crm_labels import (
    activity_label,
    payment_status_label,
)

pytestmark = pytest.mark.django_db

_OVERVIEW = reverse("platform_admin:dashboard")
_CRM = reverse("platform_admin:crm:dashboard")

_REPO = pathlib.Path(__file__).resolve().parents[3]
_ADMIN_CSS = _REPO / "static" / "platform_admin" / "css" / "admin_console.css"
_BASE_TPL = _REPO / "templates" / "layouts" / "base_platform_admin.html"


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


# ── PLATFORM-ADMIN-SHELL-RESET-C2 ──────────────────────────────────────────────
# Remaining English strings that were leaking into the Arabic CRM UI.
_ENGLISH_LEAKS = [
    "Customer activity and operations timeline",
    "Internal notes recorded against customers",
    "Review, assign, and resolve customer tickets",
    "Browse customer companies and open Customer 360",
    "Payments needing attention",
    "Recent tickets",
    "Recent activity",
]


def test_arabic_crm_dashboard_has_no_remaining_english(owner_user, organization):
    html = _get(owner_user, _CRM, lang="ar").content.decode("utf-8")
    for english in _ENGLISH_LEAKS:
        assert english not in html, f"English leaked into Arabic CRM: {english}"
    # Arabic equivalents actually render.
    assert "مدفوعات تحتاج إلى إجراء" in html
    assert "النشاط الأخير" in html


def test_arabic_overview_has_no_remaining_english(superuser, organization):
    html = _get(superuser, _OVERVIEW, lang="ar").content.decode("utf-8")
    for english in _ENGLISH_LEAKS:
        assert english not in html, f"English leaked into Arabic overview: {english}"


def test_activity_type_not_shown_raw_in_arabic(owner_user, organization):
    # "ticket_assigned" is not an ActivityType enum member, so get_*_display would
    # render the raw value. The activity_label filter maps it to a translated label.
    CustomerActivity.objects.create(
        organization=organization, activity_type="ticket_assigned",
    )
    html = _get(owner_user, _CRM, lang="ar").content.decode("utf-8")
    assert "ticket_assigned" not in html, "Raw enum value leaked into the UI"
    assert "تم إسناد التذكرة" in html


def test_activity_and_payment_status_labels_are_translated():
    with translation.override("ar"):
        assert str(activity_label("ticket_assigned")) == "تم إسناد التذكرة"
        assert str(activity_label("ticket_created")) == "تم إنشاء التذكرة"
        assert str(payment_status_label("initiated")) == "قيد البدء"
        # Unknown values fall back to the raw value (never crash).
        assert activity_label("totally_unknown") == "totally_unknown"
    with translation.override("en"):
        assert str(payment_status_label("initiated")) == "Initiated"


# ── shell layout: the structural overflow fix, asserted on the source files ────
def test_shell_markup_has_layout_classes(superuser):
    html = _get(superuser, _OVERVIEW, lang="en").content.decode("utf-8")
    for cls in ["platform-layout", "platform-main", "app-drawer"]:
        assert cls in html, f"Shell layout class missing from rendered page: {cls}"


def test_admin_css_has_decisive_layout_rule():
    css = _ADMIN_CSS.read_text(encoding="utf-8")
    # The content column must be allowed to shrink (the real overflow cause) and
    # grid tracks must use minmax(0, 1fr) — not just overflow hiding.
    assert ".platform-main" in css
    assert "min-width: 0" in css
    assert "minmax(0, 1fr)" in css
    # Backstop is present but is not the only mechanism.
    assert "overflow-x: clip" in css


def test_shell_markup_has_no_full_viewport_width_containers():
    # A standalone `w-screen` (width:100vw) on a content child is a classic
    # horizontal-scroll source. `max-w-screen-2xl` (a bounded max-width) is fine.
    import re
    base = _BASE_TPL.read_text(encoding="utf-8")
    assert not re.search(r"(?<![\w-])w-screen\b", base), "Dangerous w-screen class in shell"
    assert "100vw" not in base, "Raw 100vw width in shell markup"
