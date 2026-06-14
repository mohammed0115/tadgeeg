"""
Minimal CRM write services (CRM-1B).

Thin, transactional helpers that create a record, append a customer timeline
entry, and write the formal AuditLog — atomically. They intentionally contain
NO status-transition workflow, NO forms, NO UI, and NO billing/payments logic.

Permission note: these services do not enforce permissions themselves. The
protected operational views added in CRM-1C+ are responsible for gating callers
via ``apps.platform_admin.permissions``. No operational view calls these in
CRM-1B; they exist to support tests and to fix the write shape early.
"""

from django.db import transaction

from apps.platform_admin.models import (
    CustomerActivity,
    CustomerNote,
    SupportTicket,
    TicketMessage,
)
from apps.platform_admin.services.crm_activity import record_customer_activity
from apps.platform_admin.services.crm_audit import log_crm_action


def create_support_ticket(
    *,
    organization,
    created_by,
    title: str,
    description: str,
    category: str = SupportTicket.Category.GENERAL,
    priority: str = SupportTicket.Priority.MEDIUM,
    assigned_to=None,
    ip_address: str = None,
) -> SupportTicket:
    """Create a ticket + timeline entry + audit record, atomically."""
    with transaction.atomic():
        ticket = SupportTicket.objects.create(
            organization=organization,
            created_by=created_by,
            assigned_to=assigned_to,
            title=title,
            description=description,
            category=category,
            priority=priority,
        )
        record_customer_activity(
            organization=organization,
            actor=created_by,
            activity_type=CustomerActivity.ActivityType.TICKET_CREATED,
            description=f"Ticket created: {title}",
            metadata={"ticket_id": str(ticket.id), "category": category, "priority": priority},
        )
        log_crm_action(
            actor=created_by,
            organization=organization,
            action_type="ticket_created",
            resource_type="support_ticket",
            resource_id=ticket.id,
            new_value={"title": title, "category": category, "priority": priority},
            # The domain timeline entry above is the customer-facing one; avoid a
            # duplicate by suppressing the audit helper's own activity row.
            record_activity=False,
        )
    return ticket


def add_ticket_message(
    *,
    ticket: SupportTicket,
    sender,
    message: str,
    internal_only: bool = False,
    ip_address: str = None,
) -> TicketMessage:
    """Append a message + timeline entry + audit record, atomically."""
    with transaction.atomic():
        msg = TicketMessage.objects.create(
            ticket=ticket,
            sender=sender,
            message=message,
            internal_only=internal_only,
        )
        record_customer_activity(
            organization=ticket.organization,
            actor=sender,
            activity_type=CustomerActivity.ActivityType.TICKET_MESSAGE_ADDED,
            description=f"Message added to ticket {ticket.id}",
            metadata={"ticket_id": str(ticket.id), "internal_only": internal_only},
        )
        log_crm_action(
            actor=sender,
            organization=ticket.organization,
            action_type="ticket_message_added",
            resource_type="ticket_message",
            resource_id=msg.id,
            metadata={"ticket_id": str(ticket.id), "internal_only": internal_only},
            record_activity=False,
        )
    return msg


def add_customer_note(
    *,
    organization,
    author,
    note: str,
    category: str = CustomerNote.Category.GENERAL,
    ip_address: str = None,
) -> CustomerNote:
    """Create an internal customer note + timeline entry + audit record."""
    with transaction.atomic():
        customer_note = CustomerNote.objects.create(
            organization=organization,
            author=author,
            note=note,
            category=category,
        )
        record_customer_activity(
            organization=organization,
            actor=author,
            activity_type=CustomerActivity.ActivityType.NOTE_ADDED,
            description="Internal customer note added",
            metadata={"note_id": str(customer_note.id), "category": category},
        )
        log_crm_action(
            actor=author,
            organization=organization,
            action_type="note_added",
            resource_type="customer_note",
            resource_id=customer_note.id,
            metadata={"category": category},
            record_activity=False,
        )
    return customer_note
