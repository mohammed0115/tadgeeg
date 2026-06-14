"""
Platform CRM read-only views (CRM-1C).

A read-only dashboard shell for platform CRM staff. Every view is GET-only and
renders data through the selectors layer. There are NO create/update/delete
paths, NO forms that mutate, and NO billing/payments/subscription calls.

Security: two layers.
  1. NamespaceAccessControlMiddleware already blocks non-staff from
     ``/platform-admin/*`` (anonymous → login, org users → /dashboard/).
  2. ``crm_read_required`` enforces the CRM-1B permission model on top of
     is_staff — a staff member still needs a CRM group (or be superuser).
"""

from __future__ import annotations

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponseNotAllowed
from django.shortcuts import render

from apps.platform_admin import selectors
from apps.platform_admin.models import (
    CustomerActivity,
    CustomerNote,
    SupportTicket,
)
from apps.platform_admin.permissions import can_view_crm, is_readonly_crm_user
from core.dashboard_context import build_platform_context


def crm_read_required(check=can_view_crm):
    """Require auth + the given CRM read capability. 403 if staff lacks CRM access."""

    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def _wrapped(request, *args, **kwargs):
            if not check(getattr(request, "user", None)):
                raise PermissionDenied("Platform CRM access is required.")
            # Read-only shell: never accept a mutating method. This is a hard
            # guarantee on top of having no create/update/delete logic at all.
            if request.method not in ("GET", "HEAD"):
                return HttpResponseNotAllowed(["GET", "HEAD"])
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator


def _querystring_without_page(request) -> str:
    params = request.GET.copy()
    params.pop("page", None)
    return params.urlencode()


def _crm_context(request, *, active_key, **extra):
    """Platform layout context + a read-only flag the templates rely on."""
    ctx = build_platform_context(request, active_key=active_key)
    ctx.update(
        {
            "crm_active": active_key,
            "crm_readonly_user": is_readonly_crm_user(request.user),
            "crm_breadcrumb_current": extra.pop("crm_title", "CRM"),
        }
    )
    ctx.update(extra)
    return ctx


# ── dashboard ─────────────────────────────────────────────────────────────────
@crm_read_required()
def crm_dashboard(request):
    ctx = _crm_context(
        request,
        active_key="crm_dashboard",
        crm_title="CRM Dashboard",
        summary=selectors.get_dashboard_summary(),
        recent_tickets=selectors.get_recent_tickets(),
        recent_activities=selectors.get_recent_activities(),
        recent_audits=selectors.get_recent_crm_audits(),
    )
    return render(request, "platform_admin/crm/dashboard.html", ctx)


# ── customers (Organization) ──────────────────────────────────────────────────
@crm_read_required()
def customers_list(request):
    qs = selectors.list_customers(
        q=request.GET.get("q"),
        status=request.GET.get("status"),
    )
    paginator, page_obj = selectors.paginate(qs, request.GET.get("page"))
    ctx = _crm_context(
        request,
        active_key="crm_customers",
        crm_title="Customers",
        page_obj=page_obj,
        paginator=paginator,
        querystring=_querystring_without_page(request),
        filters={"q": request.GET.get("q", ""), "status": request.GET.get("status", "")},
    )
    return render(request, "platform_admin/crm/customers_list.html", ctx)


@crm_read_required()
def customer_detail(request, org_id):
    customer = selectors.get_customer(org_id)
    if customer is None:
        raise Http404("Customer not found.")
    ctx = _crm_context(
        request,
        active_key="crm_customers",
        crm_title="Customer Detail",
        customer=customer,
        tickets=selectors.get_customer_tickets(customer),
        notes=selectors.get_customer_notes(customer),
        activities=selectors.get_customer_activities(customer),
        audits=selectors.get_customer_audits(customer),
    )
    return render(request, "platform_admin/crm/customer_detail.html", ctx)


# ── tickets ───────────────────────────────────────────────────────────────────
@crm_read_required()
def tickets_list(request):
    qs = selectors.list_tickets(
        q=request.GET.get("q"),
        status=request.GET.get("status"),
        priority=request.GET.get("priority"),
        assigned_to=request.GET.get("assigned_to"),
        date_from=request.GET.get("date_from"),
        date_to=request.GET.get("date_to"),
    )
    paginator, page_obj = selectors.paginate(qs, request.GET.get("page"))
    ctx = _crm_context(
        request,
        active_key="crm_tickets",
        crm_title="Support Tickets",
        page_obj=page_obj,
        paginator=paginator,
        querystring=_querystring_without_page(request),
        status_choices=SupportTicket.Status.choices,
        priority_choices=SupportTicket.Priority.choices,
        filters={
            "q": request.GET.get("q", ""),
            "status": request.GET.get("status", ""),
            "priority": request.GET.get("priority", ""),
            "date_from": request.GET.get("date_from", ""),
            "date_to": request.GET.get("date_to", ""),
        },
    )
    return render(request, "platform_admin/crm/tickets_list.html", ctx)


@crm_read_required()
def ticket_detail(request, ticket_id):
    ticket = selectors.get_ticket(ticket_id)
    if ticket is None:
        raise Http404("Ticket not found.")
    ctx = _crm_context(
        request,
        active_key="crm_tickets",
        crm_title="Ticket Detail",
        ticket=ticket,
        messages=selectors.get_ticket_messages(ticket),
        audits=selectors.get_ticket_audits(ticket),
    )
    return render(request, "platform_admin/crm/ticket_detail.html", ctx)


# ── notes ─────────────────────────────────────────────────────────────────────
@crm_read_required()
def notes_list(request):
    qs = selectors.list_notes(
        q=request.GET.get("q"),
        category=request.GET.get("category"),
    )
    paginator, page_obj = selectors.paginate(qs, request.GET.get("page"))
    ctx = _crm_context(
        request,
        active_key="crm_notes",
        crm_title="Customer Notes",
        page_obj=page_obj,
        paginator=paginator,
        querystring=_querystring_without_page(request),
        category_choices=CustomerNote.Category.choices,
        filters={"q": request.GET.get("q", ""), "category": request.GET.get("category", "")},
    )
    return render(request, "platform_admin/crm/notes_list.html", ctx)


# ── activities (timeline) ─────────────────────────────────────────────────────
@crm_read_required()
def activities_list(request):
    qs = selectors.list_activities(
        activity_type=request.GET.get("activity_type"),
        organization_id=request.GET.get("organization"),
    )
    paginator, page_obj = selectors.paginate(qs, request.GET.get("page"))
    ctx = _crm_context(
        request,
        active_key="crm_activity",
        crm_title="Activity Timeline",
        page_obj=page_obj,
        paginator=paginator,
        querystring=_querystring_without_page(request),
        activity_type_choices=CustomerActivity.ActivityType.choices,
        filters={"activity_type": request.GET.get("activity_type", "")},
    )
    return render(request, "platform_admin/crm/activities_list.html", ctx)
