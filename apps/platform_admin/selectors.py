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
from django.db.models import Count, Max, Q
from django.utils.dateparse import parse_date

from apps.authentication.models import AuditLog, Organization, User
from apps.billing.choices import USABLE_STATUSES
from apps.billing.models import OrganizationSubscription
from apps.payments.choices import PaymentStatus
from apps.payments.models import PaymentTransaction
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


# ══════════════════════════════════════════════════════════════════════════════
# CRM-1D — richer Customer Directory + Customer Profile (read-only)
# ══════════════════════════════════════════════════════════════════════════════

PAYMENT_SAFE_FIELDS = (
    "id",
    "provider",
    "purpose",
    "status",
    "amount",
    "currency",
    "paid_at",
    "created_at",
    "failed_reason",
)


# ── Directory ─────────────────────────────────────────────────────────────────
def list_crm_customers(*, q=None, status=None, country=None, subscription=None):
    """
    Customer directory queryset (read-only).

    Filters (all optional, validated): free-text ``q`` over Arabic/English name,
    VAT, CR, and *linked user email*; account ``status`` (active/inactive);
    ``country`` (validated against Organization.Country); ``subscription``
    (active|none) by usable subscription presence.
    """
    qs = Organization.objects.all()
    if q:
        qs = qs.filter(
            Q(name__icontains=q)
            | Q(name_ar__icontains=q)
            | Q(vat_number__icontains=q)
            | Q(cr_number__icontains=q)
            | Q(users__email__icontains=q)
        ).distinct()
    if status == "active":
        qs = qs.filter(is_active=True)
    elif status == "inactive":
        qs = qs.filter(is_active=False)
    country = _valid_choice(country, Organization.Country)
    if country:
        qs = qs.filter(country=country)
    if subscription == "active":
        qs = qs.filter(subscriptions__status__in=USABLE_STATUSES).distinct()
    elif subscription == "none":
        qs = qs.exclude(subscriptions__status__in=USABLE_STATUSES).distinct()
    return qs.order_by("-created_at")


def enrich_customer_rows(organizations, *, include_financial=False):
    """
    Attach read-only display attributes to a page of Organization rows using a
    handful of batched queries (no per-row N+1, no join fan-out).

    Sets on each org: ``crm_users_count``, ``crm_last_login``,
    ``crm_primary_email``, ``crm_open_tickets``. When ``include_financial`` is
    True also sets ``crm_plan_name`` and ``crm_sub_status`` (gated by the caller's
    financial permission).
    """
    orgs = list(organizations)
    if not orgs:
        return orgs
    ids = [o.id for o in orgs]

    user_rows = (
        User.objects.filter(organization_id__in=ids)
        .values("organization_id")
        .annotate(count=Count("id"), last_login=Max("last_login"))
    )
    users_by_org = {r["organization_id"]: r for r in user_rows}

    # Primary contact: prefer an org admin, else the earliest-created user.
    primary = {}
    for u in User.objects.filter(organization_id__in=ids, role="admin").order_by("created_at"):
        primary.setdefault(u.organization_id, u.email)
    for u in User.objects.filter(organization_id__in=ids).order_by("created_at"):
        primary.setdefault(u.organization_id, u.email)

    ticket_rows = (
        SupportTicket.objects.filter(
            organization_id__in=ids, status__in=UNRESOLVED_TICKET_STATUSES
        )
        .values("organization_id")
        .annotate(count=Count("id"))
    )
    open_tickets = {r["organization_id"]: r["count"] for r in ticket_rows}

    subs = {}
    if include_financial:
        for s in OrganizationSubscription.objects.filter(
            organization_id__in=ids, status__in=USABLE_STATUSES
        ).select_related("plan"):
            subs.setdefault(s.organization_id, s)

    for o in orgs:
        urow = users_by_org.get(o.id, {})
        o.crm_users_count = urow.get("count", 0)
        o.crm_last_login = urow.get("last_login")
        o.crm_primary_email = primary.get(o.id)
        o.crm_open_tickets = open_tickets.get(o.id, 0)
        sub = subs.get(o.id)
        o.crm_plan_name = (sub.plan.name_en if sub else None) if include_financial else None
        o.crm_sub_status = (sub.get_status_display() if sub else None) if include_financial else None
    return orgs


# ── Profile pieces ────────────────────────────────────────────────────────────
def get_customer_users(organization):
    return organization.users.all().order_by("-is_staff", "full_name", "email")


def get_customer_primary_contact(organization):
    return (
        organization.users.filter(role="admin").order_by("created_at").first()
        or organization.users.order_by("created_at").first()
    )


def get_customer_subscription_summary(organization):
    """Most relevant subscription (usable first, else most recent). May be None."""
    usable = (
        OrganizationSubscription.objects.filter(
            organization=organization, status__in=USABLE_STATUSES
        )
        .select_related("plan")
        .order_by("-created_at")
        .first()
    )
    if usable:
        return usable
    return (
        OrganizationSubscription.objects.filter(organization=organization)
        .select_related("plan")
        .order_by("-created_at")
        .first()
    )


def get_customer_payment_summary(organization, limit: int = 10) -> dict:
    """Latest payment transactions (safe fields only) + counts. Never raw payloads."""
    base = PaymentTransaction.objects.filter(organization=organization)
    return {
        "transactions": list(
            base.only(*PAYMENT_SAFE_FIELDS).order_by("-created_at")[:limit]
        ),
        "total_count": base.count(),
        "paid_count": base.filter(status=PaymentStatus.PAID).count(),
    }


def get_customer_ticket_summary(organization, limit: int = 25) -> dict:
    base = SupportTicket.objects.filter(organization=organization).select_related(
        "assigned_to", "created_by"
    )
    return {
        "tickets": list(base.order_by("-created_at")[:limit]),
        "open_count": base.filter(status__in=UNRESOLVED_TICKET_STATUSES).count(),
        "total_count": base.count(),
    }


def get_customer_activity_timeline(organization, limit: int = 50):
    return get_customer_activities(organization, limit=limit)


def get_customer_audit_timeline(organization, limit: int = 50):
    return get_customer_audits(organization, limit=limit)


def get_crm_customer_profile(organization_id, *, include_financial: bool = True):
    """
    Bundle the full read-only profile. Financial sections (subscription/payments)
    are omitted when ``include_financial`` is False (e.g. Support Agent role).
    Returns None when the organization does not exist.
    """
    organization = get_customer(organization_id)
    if organization is None:
        return None
    profile = {
        "organization": organization,
        "primary_contact": get_customer_primary_contact(organization),
        "users": get_customer_users(organization),
        "tickets": get_customer_ticket_summary(organization),
        "notes": get_customer_notes(organization),
        "activities": get_customer_activity_timeline(organization),
        "audits": get_customer_audit_timeline(organization),
        "subscription": None,
        "payments": None,
        "include_financial": include_financial,
    }
    if include_financial:
        profile["subscription"] = get_customer_subscription_summary(organization)
        profile["payments"] = get_customer_payment_summary(organization)
    return profile


# ── CRM-1F — subscription lookup scoped to a customer (read-only) ─────────────
def get_subscription_for_customer(subscription_id, organization):
    """
    Return the subscription with ``subscription_id`` ONLY if it belongs to
    ``organization`` (tenant-scoped — prevents IDOR). None otherwise.
    """
    return (
        OrganizationSubscription.objects.filter(
            id=_safe_uuid(subscription_id), organization=organization
        )
        .select_related("plan")
        .first()
    )


# ── CRM-1E — assignable staff (read-only) ─────────────────────────────────────
def get_assignable_crm_staff():
    """
    Platform CRM staff a ticket can be assigned to: staff users who belong to a
    CRM group, plus superusers. Read-only queryset used by the assign/create forms.
    """
    from apps.platform_admin.permissions import ALL_CRM_GROUPS

    return (
        User.objects.filter(is_staff=True)
        .filter(Q(groups__name__in=ALL_CRM_GROUPS) | Q(is_superuser=True))
        .distinct()
        .order_by("full_name", "email")
    )
