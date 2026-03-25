from __future__ import annotations

from django.db.models import QuerySet

from .models import ContactLead, LeadNote


def get_all_leads(
    status: str | None = None,
    source: str | None = None,
    assigned_to=None,
) -> QuerySet:
    """Return all leads with optional filters."""
    qs = ContactLead.objects.select_related('assigned_to').prefetch_related('notes')
    if status:
        qs = qs.filter(status=status)
    if source:
        qs = qs.filter(source=source)
    if assigned_to is not None:
        qs = qs.filter(assigned_to=assigned_to)
    return qs


def get_lead_by_id(lead_id) -> ContactLead | None:
    """Return a single ContactLead by PK, or None if not found."""
    try:
        return ContactLead.objects.select_related('assigned_to').prefetch_related('notes__created_by').get(pk=lead_id)
    except ContactLead.DoesNotExist:
        return None


def get_lead_notes(lead_id) -> QuerySet:
    """Return all notes for a given lead, ordered oldest-first."""
    return LeadNote.objects.filter(lead_id=lead_id).select_related('created_by')


def get_lead_stats() -> dict:
    """Return aggregate counts for lead statuses and unread count."""
    from django.db.models import Count

    status_counts = dict(
        ContactLead.objects.values_list('status').annotate(count=Count('id')).values_list('status', 'count')
    )
    return {
        'total': ContactLead.objects.count(),
        'new': status_counts.get(ContactLead.Status.NEW, 0),
        'in_progress': status_counts.get(ContactLead.Status.IN_PROGRESS, 0),
        'qualified': status_counts.get(ContactLead.Status.QUALIFIED, 0),
        'converted': status_counts.get(ContactLead.Status.CONVERTED, 0),
        'closed': status_counts.get(ContactLead.Status.CLOSED, 0),
        'spam': status_counts.get(ContactLead.Status.SPAM, 0),
        'unread': ContactLead.objects.filter(is_read=False).count(),
    }
