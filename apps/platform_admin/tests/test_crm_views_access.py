"""Access-control + render tests for the read-only CRM shell (CRM-1C)."""

import pytest
from django.urls import reverse

from apps.platform_admin.models import (
    CustomerActivity,
    CustomerNote,
    SupportTicket,
)

pytestmark = pytest.mark.django_db


# Static list/dashboard routes (no path args).
LIST_ROUTE_NAMES = [
    "platform_admin:crm:dashboard",
    "platform_admin:crm:customers",
    "platform_admin:crm:tickets",
    "platform_admin:crm:notes",
    "platform_admin:crm:activities",
]


@pytest.fixture
def ticket(organization, support_user):
    return SupportTicket.objects.create(
        organization=organization,
        created_by=support_user,
        title="Login fails",
        description="Cannot sign in.",
        priority=SupportTicket.Priority.HIGH,
    )


# Access is enforced by the crm_read_required decorator (the project guards
# platform pages with decorators; NamespaceAccessControlMiddleware is not wired
# into MIDDLEWARE). Anonymous → login redirect; any authenticated user lacking
# CRM access → 403.
@pytest.mark.parametrize("route", LIST_ROUTE_NAMES)
def test_anonymous_redirected(client, route):
    resp = client.get(reverse(route))
    assert resp.status_code == 302
    assert "/login/" in resp["Location"]


@pytest.mark.parametrize("route", LIST_ROUTE_NAMES)
def test_regular_non_staff_user_blocked(client, regular_user, route):
    client.force_login(regular_user)
    resp = client.get(reverse(route))
    # Non-staff customer user has no CRM access → forbidden (never 200).
    assert resp.status_code == 403


# ── Staff WITHOUT a CRM group is blocked by the CRM permission layer (403)
@pytest.mark.parametrize("route", LIST_ROUTE_NAMES)
def test_staff_without_crm_group_forbidden(client, staff_no_group, route):
    client.force_login(staff_no_group)
    resp = client.get(reverse(route))
    assert resp.status_code == 403


# ── CRM users get through ────────────────────────────────────────────────────
@pytest.mark.parametrize("route", LIST_ROUTE_NAMES)
def test_owner_can_access(client, owner_user, route):
    client.force_login(owner_user)
    assert client.get(reverse(route)).status_code == 200


@pytest.mark.parametrize("route", LIST_ROUTE_NAMES)
def test_readonly_auditor_can_view(client, readonly_user, route):
    client.force_login(readonly_user)
    assert client.get(reverse(route)).status_code == 200


@pytest.mark.parametrize("route", LIST_ROUTE_NAMES)
def test_support_agent_can_view(client, support_user, route):
    client.force_login(support_user)
    assert client.get(reverse(route)).status_code == 200


# ── Detail views ─────────────────────────────────────────────────────────────
def test_customer_detail_access(client, owner_user, readonly_user, staff_no_group, organization):
    url = reverse("platform_admin:crm:customer_detail", args=[organization.id])
    # forbidden for staff without CRM group
    client.force_login(staff_no_group)
    assert client.get(url).status_code == 403
    # allowed for CRM users
    client.force_login(owner_user)
    assert client.get(url).status_code == 200
    client.force_login(readonly_user)
    assert client.get(url).status_code == 200


def test_ticket_detail_access(client, owner_user, staff_no_group, ticket):
    url = reverse("platform_admin:crm:ticket_detail", args=[ticket.id])
    client.force_login(staff_no_group)
    assert client.get(url).status_code == 403
    client.force_login(owner_user)
    assert client.get(url).status_code == 200


def test_detail_404_for_missing_objects(client, owner_user):
    client.force_login(owner_user)
    import uuid

    missing = uuid.uuid4()
    assert client.get(
        reverse("platform_admin:crm:customer_detail", args=[missing])
    ).status_code == 404
    assert client.get(
        reverse("platform_admin:crm:ticket_detail", args=[missing])
    ).status_code == 404


# ── Render correctness ───────────────────────────────────────────────────────
def test_dashboard_renders_with_data(client, owner_user, ticket):
    client.force_login(owner_user)
    resp = client.get(reverse("platform_admin:crm:dashboard"))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Login fails" in body  # recent ticket surfaced


def test_list_renders_empty_state(client, owner_user):
    client.force_login(owner_user)
    resp = client.get(reverse("platform_admin:crm:tickets"))
    assert resp.status_code == 200
    assert "No tickets" in resp.content.decode()


def test_tickets_list_shows_ticket(client, owner_user, ticket):
    client.force_login(owner_user)
    resp = client.get(reverse("platform_admin:crm:tickets"))
    assert "Login fails" in resp.content.decode()


def test_customer_detail_shows_related_records(client, owner_user, organization, support_user, ticket):
    CustomerNote.objects.create(
        organization=organization, author=support_user, note="VIP customer"
    )
    CustomerActivity.objects.create(
        organization=organization,
        activity_type=CustomerActivity.ActivityType.TICKET_CREATED,
        description="Ticket created",
    )
    client.force_login(owner_user)
    body = client.get(
        reverse("platform_admin:crm:customer_detail", args=[organization.id])
    ).content.decode()
    assert "VIP customer" in body
    assert "Login fails" in body


# ── No mutation surface ──────────────────────────────────────────────────────
@pytest.mark.parametrize("route", LIST_ROUTE_NAMES)
def test_post_is_method_not_allowed(client, owner_user, route):
    client.force_login(owner_user)
    resp = client.post(reverse(route), {"x": "1"})
    assert resp.status_code == 405  # GET/HEAD only — no POST mutation surface


def test_post_does_not_mutate(client, owner_user, organization):
    client.force_login(owner_user)
    before = SupportTicket.objects.count()
    client.post(reverse("platform_admin:crm:tickets"), {"title": "hack"})
    assert SupportTicket.objects.count() == before
