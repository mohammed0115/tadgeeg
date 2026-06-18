"""PLATFORM-ADMIN-FORM-UX-B — CMS forms have section/tab navigation + a sticky
action footer + a unified, RTL-safe design system (admin_forms.css). Asserts
markup/classes, not just HTTP 200.
"""
import pytest
from django.contrib.staticfiles import finders
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db


def _get(user, name):
    c = Client()
    c.force_login(user)
    return c.get(reverse(name), HTTP_ACCEPT_LANGUAGE="en")


def test_admin_forms_css_collectable():
    assert finders.find("platform_admin/css/admin_forms.css") is not None


def test_base_links_admin_forms_css(superuser):
    html = _get(superuser, "platform_admin:homepage").content.decode("utf-8")
    assert "platform_admin/css/admin_forms" in html


def test_homepage_has_tab_navigation(superuser):
    html = _get(superuser, "platform_admin:homepage").content.decode("utf-8")
    # Homepage uses an Alpine tab switcher.
    assert "activeTab" in html
    assert "btn-primary" in html


def test_about_has_section_nav_and_action_footer(superuser):
    html = _get(superuser, "platform_admin:about").content.decode("utf-8")
    assert "form-section-nav" in html
    assert "admin-action-footer" in html
    assert 'id="about-content"' in html


def test_seo_has_section_nav_and_action_footer(superuser):
    html = _get(superuser, "platform_admin:seo").content.decode("utf-8")
    assert "form-section-nav" in html
    assert "admin-action-footer" in html
    assert 'id="seo-meta"' in html


def test_intro_video_has_section_nav_and_action_footer(superuser):
    html = _get(superuser, "platform_admin:intro_video").content.decode("utf-8")
    assert "form-section-nav" in html
    assert "admin-action-footer" in html
    assert 'id="video-settings"' in html


def test_pricing_uses_unified_buttons(superuser):
    html = _get(superuser, "platform_admin:pricing").content.decode("utf-8")
    assert "btn-primary" in html


def test_cms_pages_respond_200_for_platform_staff(superuser):
    for name in ["homepage", "about", "pricing", "seo", "intro_video"]:
        assert _get(superuser, f"platform_admin:{name}").status_code == 200


def test_regular_user_denied_on_cms(regular_user):
    resp = _get(regular_user, "platform_admin:homepage")
    assert resp.status_code in (403, 302)


def test_organizations_redirect_still_works(owner_user):
    c = Client()
    c.force_login(owner_user)
    resp = c.get(reverse("platform_admin:organizations"))
    assert resp.status_code == 302
    assert reverse("platform_admin:crm:customers") in resp["Location"]
