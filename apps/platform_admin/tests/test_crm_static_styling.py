"""PLATFORM-ADMIN-STATIC-CSS-FIX-A — the CRM console links a static style
safety-net so it stays presentable even if browser-JIT Tailwind fails to load.
"""
import pytest
from django.contrib.staticfiles import finders
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_fallback_css_is_collectable():
    # The file must be discoverable by staticfiles (so collectstatic ships it).
    assert finders.find("platform_admin/fallback.css") is not None


def test_admin_console_css_is_collectable():
    assert finders.find("platform_admin/css/admin_console.css") is not None


def test_admin_console_css_has_overflow_and_rtl_shell_hardening():
    # The fix for the horizontal scrollbar / clipped content must be in the
    # shipped stylesheet: content shrinkability + viewport-bounded body +
    # deterministic (in-flow) sidebar on desktop.
    path = finders.find("platform_admin/css/admin_console.css")
    css = open(path, encoding="utf-8").read()
    assert "overflow-x: clip" in css
    assert "min-width: 0" in css
    assert "position: static" in css        # sidebar in flow on desktop
    assert 'form[action="/i18n/setlang/"]' in css   # styled language switcher


def test_crm_dashboard_links_admin_console_css(owner_user):
    client = Client()
    client.force_login(owner_user)
    html = client.get(reverse("platform_admin:crm:dashboard")).content.decode("utf-8")
    assert "platform_admin/css/admin_console" in html


def test_crm_dashboard_has_layout_shell_and_cards(owner_user, organization):
    # With at least one customer the dashboard renders the full console
    # (KPI grid + cards), not the empty state.
    client = Client()
    client.force_login(owner_user)
    html = client.get(reverse("platform_admin:crm:dashboard")).content.decode("utf-8")
    # Shell wrapper + card grid + dashboard cards present (styled, not default).
    assert 'class="platform-shell"' in html
    assert "platform-card" in html
    assert "grid" in html


def test_crm_dashboard_links_static_fallback_css(owner_user):
    client = Client()
    client.force_login(owner_user)
    resp = client.get(reverse("platform_admin:crm:dashboard"))
    assert resp.status_code == 200
    html = resp.content.decode("utf-8")
    # A real stylesheet <link> to our fallback is present (not JIT-only styling).
    assert "platform_admin/fallback" in html
    assert 'rel="stylesheet"' in html
    # Shell wrapper that the fallback is scoped to.
    assert 'class="platform-shell"' in html


def test_crm_customer_page_also_styled(owner_user, organization):
    client = Client()
    client.force_login(owner_user)
    resp = client.get(
        reverse("platform_admin:crm:customer_detail", args=[organization.id])
    )
    assert resp.status_code == 200
    assert "platform_admin/fallback" in resp.content.decode("utf-8")


def test_billing_page_does_not_load_platform_fallback():
    # The fallback is scoped to the platform console only — billing/public
    # pages must not pull it in.
    from apps.billing.tests._factories import make_org, make_user
    org = make_org()
    user = make_user(organization=org)
    client = Client()
    client.force_login(user)
    resp = client.get("/billing/subscription/",
                      HTTP_ACCEPT="text/html,*/*", HTTP_ACCEPT_LANGUAGE="en")
    assert resp.status_code == 200
    assert "platform_admin/fallback" not in resp.content.decode("utf-8")


def test_permissions_unchanged_non_crm_user_denied(staff_no_group, organization):
    client = Client()
    client.force_login(staff_no_group)
    resp = client.get(
        reverse("platform_admin:crm:customer_detail", args=[organization.id])
    )
    assert resp.status_code == 403
