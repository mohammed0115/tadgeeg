"""Service tests for minimal CRM write helpers (CRM-1B)."""

import pytest

from apps.authentication.models import AuditLog
from apps.platform_admin.models import (
    CustomerActivity,
    CustomerNote,
    SupportTicket,
    TicketMessage,
)
from apps.platform_admin.services.crm_operations import (
    add_customer_note,
    add_ticket_message,
    create_support_ticket,
)

pytestmark = pytest.mark.django_db


def _activity_types(organization):
    return set(
        CustomerActivity.objects.filter(organization=organization).values_list(
            "activity_type", flat=True
        )
    )


def test_create_support_ticket_writes_ticket_audit_and_activity(organization, support_user):
    ticket = create_support_ticket(
        actor=support_user,
        organization=organization,
        title="Upload error",
        description="Fails at validation.",
        category=SupportTicket.Category.UPLOAD_ISSUE,
        priority=SupportTicket.Priority.HIGH,
    )
    assert SupportTicket.objects.filter(id=ticket.id).exists()
    assert ticket.priority == SupportTicket.Priority.HIGH

    # AuditLog written with the CRM verb in details (CRM-1E contract).
    audit = AuditLog.objects.filter(
        organization=organization, resource_id=str(ticket.id)
    ).latest("timestamp")
    assert audit.details["action_type"] == "support_ticket_created"

    # Exactly one domain timeline entry (the audit helper's own row is suppressed).
    types = _activity_types(organization)
    assert CustomerActivity.ActivityType.TICKET_CREATED in types
    assert CustomerActivity.ActivityType.CRM_AUDIT_LOGGED not in types


def test_add_ticket_message_writes_message_and_activity(organization, support_user):
    ticket = create_support_ticket(
        actor=support_user,
        organization=organization,
        title="T",
        description="d",
    )
    msg = add_ticket_message(
        actor=support_user, ticket=ticket, message="On it", internal_only=True
    )
    assert TicketMessage.objects.filter(id=msg.id).exists()
    assert msg.internal_only is True
    assert CustomerActivity.ActivityType.TICKET_MESSAGE_ADDED in _activity_types(
        organization
    )


def test_add_customer_note_writes_note_and_activity(organization, finance_user):
    note = add_customer_note(
        organization=organization,
        author=finance_user,
        note="Payment plan agreed.",
        category=CustomerNote.Category.FINANCE,
    )
    assert CustomerNote.objects.filter(id=note.id).exists()
    assert note.category == CustomerNote.Category.FINANCE
    assert CustomerActivity.ActivityType.NOTE_ADDED in _activity_types(organization)

    audit = AuditLog.objects.filter(
        organization=organization, resource_id=str(note.id)
    ).latest("timestamp")
    assert audit.details["action_type"] == "note_added"
