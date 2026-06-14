"""Model tests for Platform CRM core models (CRM-1B)."""

import pytest

from apps.platform_admin.models import (
    CustomerActivity,
    CustomerNote,
    SupportTicket,
    TicketMessage,
)

pytestmark = pytest.mark.django_db


def test_support_ticket_defaults(organization, owner_user):
    ticket = SupportTicket.objects.create(
        organization=organization,
        created_by=owner_user,
        title="Cannot upload invoice",
        description="Upload fails at 50%.",
    )
    assert ticket.status == SupportTicket.Status.OPEN
    assert ticket.priority == SupportTicket.Priority.MEDIUM
    assert ticket.category == SupportTicket.Category.GENERAL
    assert ticket.organization_id == organization.id
    assert ticket.resolved_at is None
    assert str(ticket)  # __str__ must not raise


def test_support_ticket_linked_to_organization(organization, owner_user):
    SupportTicket.objects.create(
        organization=organization,
        created_by=owner_user,
        title="T1",
        description="d",
    )
    assert organization.support_tickets.count() == 1


def test_ticket_message_linked_to_ticket(organization, support_user):
    ticket = SupportTicket.objects.create(
        organization=organization,
        created_by=support_user,
        title="T",
        description="d",
    )
    msg = TicketMessage.objects.create(
        ticket=ticket, sender=support_user, message="Looking into it"
    )
    assert msg.internal_only is False
    assert ticket.messages.count() == 1
    assert str(msg)


def test_customer_note_created(organization, support_user):
    note = CustomerNote.objects.create(
        organization=organization,
        author=support_user,
        category=CustomerNote.Category.SUPPORT,
        note="Customer prefers Arabic communication.",
    )
    assert note.category == CustomerNote.Category.SUPPORT
    assert organization.crm_notes.count() == 1
    assert str(note)


def test_customer_activity_with_metadata(organization, owner_user):
    activity = CustomerActivity.objects.create(
        organization=organization,
        actor=owner_user,
        activity_type=CustomerActivity.ActivityType.NOTE_ADDED,
        description="Note added",
        metadata={"note_id": "abc", "category": "support"},
    )
    assert activity.metadata["category"] == "support"
    assert activity.activity_type == CustomerActivity.ActivityType.NOTE_ADDED
    assert str(activity)


def test_customer_activity_metadata_defaults_to_dict(organization):
    activity = CustomerActivity.objects.create(
        organization=organization,
        activity_type=CustomerActivity.ActivityType.GENERAL,
    )
    assert activity.metadata == {}
    assert activity.actor is None  # nullable actor (system event)
