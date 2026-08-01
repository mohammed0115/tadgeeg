"""Permission contract for the /api/platform-admin/ surface.

Phase 0-A mounted ``apps/platform_management/api_urls.py`` at
``/api/platform-admin/``. Before that mount every one of the admin console's
61 API call sites returned 404 — the console rendered but could neither load
nor save anything.

These tests exist because ``resolve()`` proves nothing: it succeeds for a view
that raises at runtime, and it says nothing about who may call it. Every test
here issues a real HTTP request and asserts on the response body.

There is **no middleware fronting this prefix**. ``core/namespace_access.py``
defines ``PLATFORM_PREFIXES`` covering ``/api/platform-admin/``, but
``NamespaceAccessControlMiddleware`` is absent from ``settings.MIDDLEWARE``
(the docstring in ``apps/platform_admin/crm_views.py`` claiming otherwise is
stale; ``apps/platform_admin/tests/test_crm_views_access.py`` records the
truth). Per-view permission classes are therefore the ONLY layer, which is
exactly why this file asserts them per endpoint rather than sampling.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.authentication.models import Organization

pytestmark = pytest.mark.django_db

User = get_user_model()


# Every GET-able endpoint mounted in STEP 4 that needs no primary key.
# Detail routes are covered by the escalation tests below; the point of this
# list is that no listed endpoint may be reachable by a non-staff user.
PLATFORM_GET_ENDPOINTS = [
    "/api/platform-admin/stats/",
    "/api/platform-admin/organizations/",
    "/api/platform-admin/intro-video/",
    "/api/platform-admin/faq/",
    "/api/platform-admin/cms/pages/",
    "/api/platform-admin/cms/pages/stats/",
    "/api/platform-admin/homepage/",
    "/api/platform-admin/about/",
    "/api/platform-admin/services/",
    "/api/platform-admin/pricing/",
    "/api/platform-admin/faq/categories/",
    "/api/platform-admin/faq/items/",
    "/api/platform-admin/leads/",
    "/api/platform-admin/leads/stats/",
    "/api/platform-admin/seo/list/",
    "/api/platform-admin/media/",
    "/api/platform-admin/storage/providers/",
    "/api/platform-admin/settings/",
    "/api/platform-admin/activity-logs/",
    "/api/platform-admin/activity-logs/stats/",
]


@pytest.fixture
def organization(db):
    return Organization.objects.create(
        name="Acme Audit Co",
        country=Organization.Country.SAUDI_ARABIA,
        currency=Organization.Currency.SAR,
    )


@pytest.fixture
def staff_user(db):
    """Platform staff — the only identity this surface is for."""
    u = User.objects.create_user(
        email="staff@tadgeeg.test",
        password="StrongPass123!",
        full_name="Platform Staff",
    )
    u.is_staff = True
    u.email_verified_at = timezone.now()
    u.save(update_fields=["is_staff", "email_verified_at"])
    return u


@pytest.fixture
def org_admin_user(db, organization):
    """A normal customer.

    ``role=User.Role.ADMIN`` is what EVERY self-service registrant receives
    (apps/authentication/serializers.py). Before Phase 0-A this role satisfied
    ``CMSAdminPermission`` and ``apps.leads._AdminPermission``, making both
    equivalent to ``IsAuthenticated``.

    The organisation is given a usable subscription on purpose: without one,
    ``SubscriptionRequiredMiddleware`` would return 402 before the request ever
    reached the permission class, and the test would pass for the wrong reason
    — proving the billing wall works rather than proving the escalation is
    closed.
    """
    u = User.objects.create_user(
        email="customer@example.com",
        password="StrongPass123!",
        full_name="Customer Owner",
        role=User.Role.ADMIN,
        organization=organization,
    )
    u.email_verified_at = timezone.now()
    u.save(update_fields=["email_verified_at"])

    from io import StringIO

    from django.core.management import call_command

    from apps.billing.services.subscription_service import SubscriptionService

    call_command("seed_billing_plans", stdout=StringIO())
    SubscriptionService().create_free_trial(organization)
    return u


# ── the escalation this phase closed ─────────────────────────────────────────

@pytest.mark.parametrize("path", PLATFORM_GET_ENDPOINTS)
def test_org_admin_role_is_forbidden(client, org_admin_user, path):
    """A customer with role="admin" must NOT reach the platform surface."""
    client.force_login(org_admin_user)
    resp = client.get(path)
    assert resp.status_code == 403, (
        f"{path} returned {resp.status_code} for a non-staff user whose role is "
        f'"admin". Every registrant gets that role, so anything but 403 means '
        f"the platform console is reachable by customers."
    )


@pytest.mark.parametrize("path", PLATFORM_GET_ENDPOINTS)
def test_anonymous_is_rejected(client, path):
    resp = client.get(path)
    assert resp.status_code in (401, 403), (
        f"{path} returned {resp.status_code} for an anonymous request."
    )


# ── the view body actually executes for staff ────────────────────────────────

@pytest.mark.parametrize("path", PLATFORM_GET_ENDPOINTS)
def test_staff_reaches_the_view_body(client, staff_user, path):
    """200 AND a parsed body.

    A bare status assertion would pass for a view that resolves but raises,
    so we require the response to render — which means the view body ran.
    """
    client.force_login(staff_user)
    resp = client.get(path)
    assert resp.status_code == 200, (
        f"{path} returned {resp.status_code} for staff; body={resp.content[:400]!r}"
    )
    assert resp["Content-Type"].startswith("application/json"), (
        f"{path} did not return JSON: {resp['Content-Type']}"
    )
    resp.json()  # raises if the body is not valid JSON


def test_stats_payload_keeps_jobs_keys_and_flags_them_disabled(client, staff_user):
    """apps.jobs is quarantined; the response shape must not change for it.

    ADR 0003: keys stay, values are None (not 0 — "unknown, feature off" is a
    different claim from "no open jobs"), and a companion boolean lets the UI
    render an honest disabled state.
    """
    client.force_login(staff_user)
    body = client.get("/api/platform-admin/stats/").json()

    assert "active_jobs" in body, "response shape changed: active_jobs was dropped"
    assert body["active_jobs"] is None
    assert body["jobs_feature_enabled"] is False
    # Non-jobs counters must still be real numbers.
    assert isinstance(body["total_organizations"], int)


def test_jobs_endpoints_are_not_routed(client, staff_user):
    """The quarantined routes stay 404 — deliberately, per ADR 0003."""
    client.force_login(staff_user)
    for path in (
        "/api/platform-admin/jobs/",
        "/api/platform-admin/jobs/stats/",
        "/api/platform-admin/jobs/applications/",
    ):
        assert client.get(path).status_code == 404, (
            f"{path} resolved — importing apps.jobs breaks process startup."
        )


def test_jobs_console_page_renders_unavailable_not_a_broken_screen(client, staff_user):
    """/platform-admin/jobs/ must not serve a page whose every call 404s."""
    client.force_login(staff_user)
    resp = client.get("/platform-admin/jobs/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "not enabled" in body.lower()
    # The Alpine controller from the real screen must not be present.
    assert "jobsManager()" not in body
