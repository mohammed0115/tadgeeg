from __future__ import annotations

from apps.activity_logs.service import ActivityLogService

from .exceptions import LeadNotFoundError, LeadsError
from .models import ContactLead, LeadNote
from .selectors import get_lead_by_id


def submit_contact_form(data: dict) -> ContactLead:
    """Public submission: create a ContactLead. No user context required."""
    lead = ContactLead.objects.create(
        full_name=data.get('full_name', ''),
        email=data.get('email', '').strip().lower(),
        phone=data.get('phone', ''),
        company=data.get('company', ''),
        country=data.get('country', 'Saudi Arabia'),
        subject=data.get('subject', ''),
        message=data.get('message', ''),
        source=data.get('source', ContactLead.Source.CONTACT_FORM),
        status=ContactLead.Status.NEW,
        is_read=False,
    )
    return lead


def update_lead_status(lead_id, status: str, user) -> ContactLead:
    """Update the status of a lead."""
    lead = get_lead_by_id(lead_id)
    if lead is None:
        raise LeadNotFoundError(f"Lead {lead_id} not found.")

    old_status = lead.status
    lead.status = status
    lead.save(update_fields=['status', 'updated_at'])

    ActivityLogService.log(
        action='lead_status_updated',
        user=user,
        organization=getattr(user, 'organization', None),
        entity_type='ContactLead',
        entity_id=str(lead.pk),
        description=f"Lead from '{lead.full_name}' status changed from '{old_status}' to '{status}'.",
    )
    return lead


def assign_lead(lead_id, assignee_id, user) -> ContactLead:
    """Assign a lead to an internal user."""
    from django.contrib.auth import get_user_model

    lead = get_lead_by_id(lead_id)
    if lead is None:
        raise LeadNotFoundError(f"Lead {lead_id} not found.")

    UserModel = get_user_model()
    try:
        assignee = UserModel.objects.get(pk=assignee_id)
    except UserModel.DoesNotExist:
        raise LeadsError(f"User {assignee_id} not found.")

    lead.assigned_to = assignee
    lead.save(update_fields=['assigned_to', 'updated_at'])

    ActivityLogService.log(
        action='lead_assigned',
        user=user,
        organization=getattr(user, 'organization', None),
        entity_type='ContactLead',
        entity_id=str(lead.pk),
        description=f"Lead from '{lead.full_name}' assigned to '{assignee.full_name}'.",
    )
    return lead


def mark_lead_read(lead_id, user) -> ContactLead:
    """Mark a lead as read."""
    lead = get_lead_by_id(lead_id)
    if lead is None:
        raise LeadNotFoundError(f"Lead {lead_id} not found.")

    if not lead.is_read:
        lead.is_read = True
        lead.save(update_fields=['is_read', 'updated_at'])

        ActivityLogService.log(
            action='lead_marked_read',
            user=user,
            organization=getattr(user, 'organization', None),
            entity_type='ContactLead',
            entity_id=str(lead.pk),
            description=f"Lead from '{lead.full_name}' marked as read.",
        )
    return lead


def add_lead_note(lead_id, note_text: str, user) -> LeadNote:
    """Add a note to a lead."""
    lead = get_lead_by_id(lead_id)
    if lead is None:
        raise LeadNotFoundError(f"Lead {lead_id} not found.")

    note = LeadNote.objects.create(
        lead=lead,
        note=note_text,
        created_by=user,
    )

    ActivityLogService.log(
        action='lead_note_added',
        user=user,
        organization=getattr(user, 'organization', None),
        entity_type='ContactLead',
        entity_id=str(lead.pk),
        description=f"Note added to lead from '{lead.full_name}'.",
    )
    return note


def delete_lead(lead_id, user) -> None:
    """Delete a ContactLead and all its notes."""
    lead = get_lead_by_id(lead_id)
    if lead is None:
        raise LeadNotFoundError(f"Lead {lead_id} not found.")

    name = lead.full_name
    ActivityLogService.log(
        action='lead_deleted',
        user=user,
        organization=getattr(user, 'organization', None),
        entity_type='ContactLead',
        entity_id=str(lead.pk),
        description=f"Lead from '{name}' deleted.",
    )
    lead.delete()


def mark_as_spam(lead_id, user) -> ContactLead:
    """Mark a lead as spam."""
    lead = get_lead_by_id(lead_id)
    if lead is None:
        raise LeadNotFoundError(f"Lead {lead_id} not found.")

    lead.status = ContactLead.Status.SPAM
    lead.save(update_fields=['status', 'updated_at'])

    ActivityLogService.log(
        action='lead_marked_spam',
        user=user,
        organization=getattr(user, 'organization', None),
        entity_type='ContactLead',
        entity_id=str(lead.pk),
        description=f"Lead from '{lead.full_name}' marked as spam.",
    )
    return lead
