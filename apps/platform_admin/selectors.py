"""
Platform CRM read-only query layer (CRM-1C).

Pure read helpers for the CRM dashboard shell. NO writes, NO mutations, NO
billing/payments/subscription access. Every function returns querysets or plain
data for templates. Filtering inputs (from GET) are validated against the real
model choices before they ever touch the ORM.

Models used (all real, from CRM-1B + existing apps):
  * authentication.Organization   — the CRM "customer"
  * authentication.AuditLog        — formal audit trail (read-only)
  * platform_admin.SupportTicket / TicketMessage / CustomerNote / CustomerActivity
"""

from __future__ import annotations

import uuid

from django.core.paginator import Paginator
from django.db.models import Q
from django.utils.dateparse import parse_date

from apps.authentication.models import AuditLog, Organization
from apps.platform_admin.models import (
    CustomerActivity,
    CustomerNote,
    SupportTicket,
)

DEFAULT_PAGE_SIZE = 25
RECENT_LIMIT = 10

# resource_type values that CRM writes into AuditLog (see services/crm_audit.py
# and services/crm_operations.py). Used to scope the security trail to CRM.
CRM_AUDIT_RESOURCE_TYPES = (
    "organization",
    "support_ticket",
    "ticket_message",
    "customer_note",
)

UNRESOLVED_TICKET_STATUSES = (
    SupportTicket.Status.OPEN,
    SupportTicket.Status.PENDING_CUSTOMER,
    SupportTicket.Status.PENDING_INTERNAL,
)
HIGH_PRIORITIES = (SupportTicket.Priority.HIGH, SupportTicket.Priority.URGENT)


# ── small input guards ────────────────────────────────────────────────────────
def _safe_uuid(value):
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _valid_choice(value, choices_cls):
    return value if value in set(choices_cls.values) else None


def paginate(queryset, page_number, per_page: int = DEFAULT_PAGE_SIZE):
    """Return ``(paginator, page_obj)`` for a queryset. Out-of-range is clamped."""
    paginator = Paginator(queryset, per_page)
    return paginator, paginator.get_page(page_number)


# ── dashboard ─────────────────────────────────────────────────────────────────
def get_dashboard_summary() -> dict:
    """Counts derived only from fields that actually exist on the models."""
    tickets = SupportTicket.objects.all()
    return {
        "customers_total": Organization.objects.count(),
        "customers_active": Organization.objects.filter(is_active=True).count(),
        "tickets_total": tickets.count(),
        "tickets_open": tickets.filter(status=SupportTicket.Status.OPEN).count(),
        "tickets_unresolved": tickets.filter(
            status__in=UNRESOLVED_TICKET_STATUSES
        ).count(),
        "tickets_high_priority": tickets.filter(
            status__in=UNRESOLVED_TICKET_STATUSES, priority__in=HIGH_PRIORITIES
        ).count(),
        "notes_total": CustomerNote.objects.count(),
        "activities_total": CustomerActivity.objects.count(),
    }


def get_recent_tickets(limit: int = RECENT_LIMIT):
    return (
        SupportTicket.objects.select_related(
            "organization", "assigned_to", "created_by"
        )
    )[:limit]


def get_recent_activities(limit: int = RECENT_LIMIT):
    return CustomerActivity.objects.select_related("organization", "actor")[:limit]


def get_recent_crm_audits(limit: int = RECENT_LIMIT):
    return AuditLog.objects.filter(
        resource_type__in=CRM_AUDIT_RESOURCE_TYPES
    ).select_related("user", "organization")[:limit]


# ── lists (with safe GET filters) ─────────────────────────────────────────────
def list_tickets(
    *, q=None, status=None, priority=None, assigned_to=None, date_from=None, date_to=None
):
    qs = SupportTicket.objects.select_related(
        "organization", "assigned_to", "created_by"
    )
    if q:
        qs = qs.filter(
            Q(title__icontains=q)
            | Q(description__icontains=q)
            | Q(organization__name__icontains=q)
            | Q(organization__name_ar__icontains=q)
        )
    status = _valid_choice(status, SupportTicket.Status)
    if status:
        qs = qs.filter(status=status)
    priority = _valid_choice(priority, SupportTicket.Priority)
    if priority:
        qs = qs.filter(priority=priority)
    assignee = _safe_uuid(assigned_to)
    if assignee:
        qs = qs.filter(assigned_to_id=assignee)
    df = parse_date(date_from) if date_from else None
    if df:
        qs = qs.filter(created_at__date__gte=df)
    dt = parse_date(date_to) if date_to else None
    if dt:
        qs = qs.filter(created_at__date__lte=dt)
    return qs


def list_customers(*, q=None, status=None):
    """``status`` here is account state: 'active' | 'inactive'."""
    qs = Organization.objects.all()
    if q:
        qs = qs.filter(
            Q(name__icontains=q)
            | Q(name_ar__icontains=q)
            | Q(vat_number__icontains=q)
            | Q(cr_number__icontains=q)
        )
    if status == "active":
        qs = qs.filter(is_active=True)
    elif status == "inactive":
        qs = qs.filter(is_active=False)
    return qs.order_by("-created_at")


def list_notes(*, q=None, category=None):
    qs = CustomerNote.objects.select_related("organization", "author")
    if q:
        qs = qs.filter(
            Q(note__icontains=q) | Q(organization__name__icontains=q)
        )
    category = _valid_choice(category, CustomerNote.Category)
    if category:
        qs = qs.filter(category=category)
    return qs


def list_activities(*, activity_type=None, organization_id=None):
    qs = CustomerActivity.objects.select_related("organization", "actor")
    activity_type = _valid_choice(activity_type, CustomerActivity.ActivityType)
    if activity_type:
        qs = qs.filter(activity_type=activity_type)
    org_id = _safe_uuid(organization_id)
    if org_id:
        qs = qs.filter(organization_id=org_id)
    return qs


# ── detail ────────────────────────────────────────────────────────────────────
def get_customer(org_id):
    return Organization.objects.filter(id=_safe_uuid(org_id)).first()


def get_customer_tickets(organization, limit: int = 50):
    return SupportTicket.objects.select_related("assigned_to", "created_by").filter(
        organization=organization
    )[:limit]


def get_customer_notes(organization, limit: int = 50):
    return CustomerNote.objects.select_related("author").filter(
        organization=organization
    )[:limit]


def get_customer_activities(organization, limit: int = 50):
    return CustomerActivity.objects.select_related("actor").filter(
        organization=organization
    )[:limit]


def get_customer_audits(organization, limit: int = 50):
    return AuditLog.objects.filter(
        organization=organization, resource_type__in=CRM_AUDIT_RESOURCE_TYPES
    ).select_related("user")[:limit]


def get_ticket(ticket_id):
    return (
        SupportTicket.objects.select_related(
            "organization", "assigned_to", "created_by"
        )
        .filter(id=_safe_uuid(ticket_id))
        .first()
    )


def get_ticket_messages(ticket):
    # ordered by created_at asc via TicketMessage.Meta. internal_only is shown
    # to CRM staff with a clear marker; never exposed to customers (no customer
    # surface exists in CRM-1C).
    return ticket.messages.select_related("sender").all()


def get_ticket_audits(ticket, limit: int = 50):
    return AuditLog.objects.filter(
        resource_type="support_ticket", resource_id=str(ticket.id)
    ).select_related("user")[:limit]
