"""Selector tests for the read-only CRM query layer (CRM-1C)."""

import pytest

from apps.platform_admin import selectors
from apps.platform_admin.models import (
    CustomerActivity,
    CustomerNote,
    SupportTicket,
)
from apps.platform_admin.services.crm_operations import create_support_ticket

pytestmark = pytest.mark.django_db


def _ticket(organization, user, **kw):
    defaults = dict(
        organization=organization,
        created_by=user,
        title="T",
        description="d",
    )
    defaults.update(kw)
    return SupportTicket.objects.create(**defaults)


def test_dashboard_summary_counts(organization, support_user):
    _ticket(organization, support_user, status=SupportTicket.Status.OPEN,
            priority=SupportTicket.Priority.URGENT)
    _ticket(organization, support_user, status=SupportTicket.Status.RESOLVED)
    CustomerNote.objects.create(organization=organization, author=support_user, note="n")

    summary = selectors.get_dashboard_summary()
    assert summary["customers_total"] == 1
    assert summary["customers_active"] == 1
    assert summary["tickets_total"] == 2
    assert summary["tickets_open"] == 1
    assert summary["tickets_unresolved"] == 1
    assert summary["tickets_high_priority"] == 1
    assert summary["notes_total"] == 1


def test_list_tickets_filters_by_status_and_priority(organization, support_user):
    _ticket(organization, support_user, title="open-urgent",
            status=SupportTicket.Status.OPEN, priority=SupportTicket.Priority.URGENT)
    _ticket(organization, support_user, title="closed-low",
            status=SupportTicket.Status.CLOSED, priority=SupportTicket.Priority.LOW)

    by_status = list(selectors.list_tickets(status=SupportTicket.Status.OPEN))
    assert len(by_status) == 1
    assert by_status[0].title == "open-urgent"

    by_priority = list(selectors.list_tickets(priority=SupportTicket.Priority.LOW))
    assert len(by_priority) == 1
    assert by_priority[0].title == "closed-low"


def test_list_tickets_search_matches_title_and_customer(organization, support_user):
    _ticket(organization, support_user, title="payment glitch")
    results = list(selectors.list_tickets(q="payment"))
    assert len(results) == 1
    # search by organization name
    assert len(list(selectors.list_tickets(q=organization.name[:4]))) == 1


def test_list_tickets_ignores_invalid_filter_values(organization, support_user):
    _ticket(organization, support_user)
    # invalid status / priority / uuid must be ignored, not raise
    qs = selectors.list_tickets(
        status="not_a_status", priority="nope", assigned_to="not-a-uuid"
    )
    assert qs.count() == 1


def test_list_customers_search_and_status(organization):
    active = list(selectors.list_customers(status="active"))
    assert organization in active
    assert list(selectors.list_customers(status="inactive")) == []
    assert organization in list(selectors.list_customers(q=organization.name[:3]))


def test_list_notes_filter_by_category(organization, support_user):
    CustomerNote.objects.create(
        organization=organization, author=support_user,
        category=CustomerNote.Category.FINANCE, note="finance note",
    )
    CustomerNote.objects.create(
        organization=organization, author=support_user,
        category=CustomerNote.Category.SUPPORT, note="support note",
    )
    finance = list(selectors.list_notes(category=CustomerNote.Category.FINANCE))
    assert len(finance) == 1
    assert finance[0].note == "finance note"


def test_list_activities_filter_by_type(organization, owner_user):
    create_support_ticket(
        actor=owner_user, organization=organization,
        title="t", description="d",
    )
    filtered = list(
        selectors.list_activities(
            activity_type=CustomerActivity.ActivityType.TICKET_CREATED
        )
    )
    assert len(filtered) == 1


def test_paginate_returns_page(organization, support_user):
    for i in range(30):
        _ticket(organization, support_user, title=f"T{i}")
    paginator, page = selectors.paginate(
        selectors.list_tickets(), page_number=1, per_page=25
    )
    assert paginator.count == 30
    assert len(page.object_list) == 25
    assert page.has_next()


def test_get_ticket_messages_and_audits(organization, owner_user):
    ticket = create_support_ticket(
        actor=owner_user, organization=organization, title="t", description="d",
    )
    # create_support_ticket wrote an AuditLog scoped to this ticket
    audits = list(selectors.get_ticket_audits(ticket))
    assert any(a.details.get("action_type") == "support_ticket_created" for a in audits)
    # messages selector returns empty for a fresh ticket
    assert list(selectors.get_ticket_messages(ticket)) == []


def test_recent_crm_audits_are_scoped(organization, owner_user):
    create_support_ticket(
        actor=owner_user, organization=organization, title="t", description="d",
    )
    audits = list(selectors.get_recent_crm_audits())
    assert audits, "CRM audit entries should be returned"
    assert all(
        a.resource_type in selectors.CRM_AUDIT_RESOURCE_TYPES for a in audits
    )
