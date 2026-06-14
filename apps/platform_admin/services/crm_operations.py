"""
CRM write services.

CRM-1B introduced thin create helpers. CRM-1E expands these into the guarded
Support Ticketing operations:

  * create_support_ticket   — open a ticket
  * add_ticket_message      — append a public/internal message
  * change_ticket_status    — safe status transition (reason required)
  * assign_ticket           — (re)assign to a CRM staff member

Every write:
  - runs inside ``transaction.atomic``,
  - enforces ``can_manage_tickets(actor)`` (defense in depth; views also gate),
  - records the formal AuditLog via ``log_crm_action`` (no enum change, no
    PlatformAuditLog, no hand-written hash chain),
  - appends a ``CustomerActivity`` timeline entry,
  - raises ``ValidationError`` / ``PermissionDenied`` on bad input,
  - touches NO billing/payments/subscription state.

``add_customer_note`` is unchanged from CRM-1B (out of CRM-1E scope).
"""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.platform_admin import permissions as perms
from apps.platform_admin.models import (
    CustomerActivity,
    CustomerNote,
    SupportTicket,
    TicketMessage,
)
from apps.platform_admin.services.crm_activity import record_customer_activity
from apps.platform_admin.services.crm_audit import log_crm_action

# CustomerActivity has no "ticket_assigned" enum member; adding one would force a
# model migration, which is out of scope for CRM-1E. We record the literal value
# (valid varchar, matches the documented contract) and revisit the enum later.
ACTIVITY_TICKET_ASSIGNED = "ticket_assigned"

# Safe status transitions. Same-status is intentionally excluded (no-op).
ALLOWED_TICKET_TRANSITIONS = {
    SupportTicket.Status.OPEN: {
        SupportTicket.Status.PENDING_CUSTOMER,
        SupportTicket.Status.PENDING_INTERNAL,
        SupportTicket.Status.RESOLVED,
        SupportTicket.Status.CLOSED,
    },
    SupportTicket.Status.PENDING_CUSTOMER: {
        SupportTicket.Status.OPEN,
        SupportTicket.Status.PENDING_INTERNAL,
        SupportTicket.Status.RESOLVED,
        SupportTicket.Status.CLOSED,
    },
    SupportTicket.Status.PENDING_INTERNAL: {
        SupportTicket.Status.OPEN,
        SupportTicket.Status.PENDING_CUSTOMER,
        SupportTicket.Status.RESOLVED,
        SupportTicket.Status.CLOSED,
    },
    SupportTicket.Status.RESOLVED: {
        SupportTicket.Status.OPEN,
        SupportTicket.Status.CLOSED,
    },
    SupportTicket.Status.CLOSED: {
        SupportTicket.Status.OPEN,  # reopen only
    },
}


# ── internal guards ───────────────────────────────────────────────────────────
def _require_ticket_manager(actor):
    if not perms.can_manage_tickets(actor):
        raise PermissionDenied("Ticket management permission is required.")


def _client_ip(request):
    if request is None:
        return None
    from core.utils.coerce import get_client_ip

    return get_client_ip(request)


def _require_crm_staff_assignee(assigned_to):
    """assigned_to may be None (unassign) but otherwise must be a CRM staff user."""
    if assigned_to is not None and not perms.is_platform_crm_user(assigned_to):
        raise ValidationError("Tickets can only be assigned to platform CRM staff.")


# ── operations ────────────────────────────────────────────────────────────────
def create_support_ticket(
    *,
    actor,
    organization,
    title: str,
    description: str,
    category: str = SupportTicket.Category.GENERAL,
    priority: str = SupportTicket.Priority.MEDIUM,
    assigned_to=None,
    request=None,
) -> SupportTicket:
    """Create a ticket (+ timeline + audit), atomically. status defaults to open."""
    _require_ticket_manager(actor)
    title = (title or "").strip()
    description = (description or "").strip()
    if not title:
        raise ValidationError("Ticket title is required.")
    if not description:
        raise ValidationError("Ticket description is required.")
    _require_crm_staff_assignee(assigned_to)

    with transaction.atomic():
        ticket = SupportTicket.objects.create(
            organization=organization,
            created_by=actor,
            assigned_to=assigned_to,
            title=title,
            description=description,
            category=category,
            priority=priority,
        )
        record_customer_activity(
            organization=organization,
            actor=actor,
            activity_type=CustomerActivity.ActivityType.TICKET_CREATED,
            description=f"Ticket created: {title}",
            metadata={"ticket_id": str(ticket.id), "category": category, "priority": priority},
        )
        log_crm_action(
            actor=actor,
            organization=organization,
            action_type="support_ticket_created",
            resource_type="support_ticket",
            resource_id=ticket.id,
            new_value={"title": title, "category": category, "priority": priority},
            ip_address=_client_ip(request),
            record_activity=False,
        )
    return ticket


def add_ticket_message(
    *,
    actor,
    ticket: SupportTicket,
    message: str,
    internal_only: bool = False,
    request=None,
) -> TicketMessage:
    """Append a message (+ timeline + audit). Does NOT change ticket status."""
    _require_ticket_manager(actor)
    message = (message or "").strip()
    if not message:
        raise ValidationError("Message text is required.")

    with transaction.atomic():
        msg = TicketMessage.objects.create(
            ticket=ticket,
            sender=actor,
            message=message,
            internal_only=bool(internal_only),
        )
        record_customer_activity(
            organization=ticket.organization,
            actor=actor,
            activity_type=CustomerActivity.ActivityType.TICKET_MESSAGE_ADDED,
            description=f"Message added to ticket {ticket.id}",
            metadata={"ticket_id": str(ticket.id), "internal_only": bool(internal_only)},
        )
        log_crm_action(
            actor=actor,
            organization=ticket.organization,
            action_type="ticket_message_added",
            resource_type="ticket_message",
            resource_id=msg.id,
            metadata={"ticket_id": str(ticket.id), "internal_only": bool(internal_only)},
            ip_address=_client_ip(request),
            record_activity=False,
        )
    return msg


def change_ticket_status(
    *,
    actor,
    ticket: SupportTicket,
    new_status: str,
    reason: str,
    request=None,
) -> SupportTicket:
    """
    Transition a ticket to ``new_status`` (reason required).

    resolved_at policy (documented):
      * → resolved: set resolved_at = now
      * → closed:   set resolved_at = now if not already set
      * → open:     clear resolved_at (the ticket is no longer resolved)
    """
    _require_ticket_manager(actor)
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("A reason is required to change ticket status.")
    if new_status not in set(SupportTicket.Status.values):
        raise ValidationError("Unknown ticket status.")
    old_status = ticket.status
    if new_status not in ALLOWED_TICKET_TRANSITIONS.get(old_status, set()):
        raise ValidationError(
            f"Invalid transition: {old_status} → {new_status}."
        )

    with transaction.atomic():
        if new_status == SupportTicket.Status.RESOLVED:
            ticket.resolved_at = timezone.now()
        elif new_status == SupportTicket.Status.CLOSED:
            if ticket.resolved_at is None:
                ticket.resolved_at = timezone.now()
        elif new_status == SupportTicket.Status.OPEN:
            ticket.resolved_at = None
        ticket.status = new_status
        ticket.save(update_fields=["status", "resolved_at", "updated_at"])

        record_customer_activity(
            organization=ticket.organization,
            actor=actor,
            activity_type=CustomerActivity.ActivityType.TICKET_STATUS_CHANGED,
            description=f"Status: {old_status} → {new_status}",
            metadata={"ticket_id": str(ticket.id), "reason": reason},
        )
        log_crm_action(
            actor=actor,
            organization=ticket.organization,
            action_type="ticket_status_changed",
            resource_type="support_ticket",
            resource_id=ticket.id,
            old_value=old_status,
            new_value=new_status,
            reason=reason,
            ip_address=_client_ip(request),
            record_activity=False,
        )
    return ticket


def assign_ticket(
    *,
    actor,
    ticket: SupportTicket,
    assigned_to,
    reason: str = None,
    request=None,
) -> SupportTicket:
    """(Re)assign a ticket to a CRM staff member, or None to unassign."""
    _require_ticket_manager(actor)
    _require_crm_staff_assignee(assigned_to)
    reason = (reason or "").strip()

    old_user = ticket.assigned_to
    old_email = old_user.email if old_user else None
    new_email = assigned_to.email if assigned_to else None

    with transaction.atomic():
        ticket.assigned_to = assigned_to
        ticket.save(update_fields=["assigned_to", "updated_at"])

        record_customer_activity(
            organization=ticket.organization,
            actor=actor,
            activity_type=ACTIVITY_TICKET_ASSIGNED,
            description=f"Assigned: {old_email or '—'} → {new_email or '—'}",
            metadata={"ticket_id": str(ticket.id), "reason": reason},
        )
        log_crm_action(
            actor=actor,
            organization=ticket.organization,
            action_type="ticket_assigned",
            resource_type="support_ticket",
            resource_id=ticket.id,
            old_value=old_email,
            new_value=new_email,
            reason=reason or None,
            ip_address=_client_ip(request),
            record_activity=False,
        )
    return ticket


# ── CRM-1B note helper (unchanged; out of CRM-1E scope) ───────────────────────
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
