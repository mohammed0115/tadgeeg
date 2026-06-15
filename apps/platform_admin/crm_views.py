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

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, HttpResponseNotAllowed
from django.shortcuts import redirect, render

from apps.platform_admin import selectors
from apps.platform_admin.models import (
    CustomerActivity,
    CustomerNote,
    SupportTicket,
)
from apps.authentication.models import Organization
from apps.platform_admin import forms as crm_forms
from apps.platform_admin.permissions import (
    can_manage_financial_crm_data,
    can_manage_tickets,
    can_view_crm,
    can_view_financial_crm_data,
    is_readonly_crm_user,
)
from apps.platform_admin.services import crm_operations
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


def crm_manage_required(*, methods=("GET", "HEAD", "POST")):
    """
    Gate for ticket-write views: requires ``can_manage_tickets`` (Owner/Admin/
    Support). Finance/Readonly and non-CRM users get 403. POST-only handlers pass
    ``methods=("POST",)`` so GET (a potential mutation-via-GET) returns 405.
    """

    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def _wrapped(request, *args, **kwargs):
            if not can_manage_tickets(getattr(request, "user", None)):
                raise PermissionDenied("Ticket management permission is required.")
            if request.method not in methods:
                return HttpResponseNotAllowed(list(methods))
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator


def crm_financial_required(*, methods=("GET", "HEAD", "POST")):
    """
    Gate for financial-write views: requires ``can_manage_financial_crm_data``
    (Owner/Finance). Support/Readonly/Admin* and non-CRM users get 403.
    POST-only handlers pass ``methods=("POST",)`` so GET (mutation-via-GET) → 405.
    (*Admin: excluded by the current helper; not changed here.)
    """

    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def _wrapped(request, *args, **kwargs):
            if not can_manage_financial_crm_data(getattr(request, "user", None)):
                raise PermissionDenied("Financial management permission is required.")
            if request.method not in methods:
                return HttpResponseNotAllowed(list(methods))
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
    can_financial = can_view_financial_crm_data(request.user)
    qs = selectors.list_crm_customers(
        q=request.GET.get("q"),
        status=request.GET.get("status"),
        country=request.GET.get("country"),
        subscription=request.GET.get("subscription"),
    )
    paginator, page_obj = selectors.paginate(qs, request.GET.get("page"))
    # Enrich only the current page's rows (≤ page size) with batched queries.
    selectors.enrich_customer_rows(
        page_obj.object_list, include_financial=can_financial
    )
    ctx = _crm_context(
        request,
        active_key="crm_customers",
        crm_title="Customers",
        page_obj=page_obj,
        paginator=paginator,
        querystring=_querystring_without_page(request),
        country_choices=Organization.Country.choices,
        can_view_financial=can_financial,
        filters={
            "q": request.GET.get("q", ""),
            "status": request.GET.get("status", ""),
            "country": request.GET.get("country", ""),
            "subscription": request.GET.get("subscription", ""),
        },
    )
    return render(request, "platform_admin/crm/customers_list.html", ctx)


@crm_read_required()
def customer_detail(request, org_id):
    can_financial = can_view_financial_crm_data(request.user)
    profile = selectors.get_crm_customer_profile(
        org_id, include_financial=can_financial
    )
    if profile is None:
        raise Http404("Customer not found.")
    ctx = _crm_context(
        request,
        active_key="crm_customers",
        crm_title="Customer Detail",
        customer=profile["organization"],
        primary_contact=profile["primary_contact"],
        users=profile["users"],
        subscription=profile["subscription"],
        payments=profile["payments"],
        tickets=profile["tickets"],
        notes=profile["notes"],
        activities=profile["activities"],
        audits=profile["audits"],
        can_view_financial=can_financial,
        can_manage=can_manage_tickets(request.user),
        can_manage_financial=can_manage_financial_crm_data(request.user),
        manual_payment_plans=(
            selectors.get_purchasable_plans()
            if can_manage_financial_crm_data(request.user) else None
        ),
    )
    return render(request, "platform_admin/crm/customer_detail.html", ctx)


# ── subscription financial operations (CRM-1F-1B) ─────────────────────────────
@crm_financial_required(methods=("POST",))
def subscription_extend(request, org_id, subscription_id):
    """POST-only. Extend a customer's subscription via the CRM wrapper."""
    customer = selectors.get_customer(org_id)
    if customer is None:
        raise Http404("Customer not found.")
    subscription = selectors.get_subscription_for_customer(subscription_id, customer)
    if subscription is None:
        raise Http404("Subscription not found.")  # also covers cross-tenant ids

    form = crm_forms.ExtendSubscriptionForm(request.POST)
    if form.is_valid():
        try:
            crm_operations.crm_extend_subscription(
                actor=request.user,
                organization=customer,
                subscription=subscription,
                days=form.cleaned_data["days"],
                reason=form.cleaned_data["reason"],
                request=request,
            )
            messages.success(request, "Subscription extended.")
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
    else:
        messages.error(
            request,
            "Could not extend: a positive number of days and a reason are required.",
        )
    return redirect("platform_admin:crm:customer_detail", org_id=customer.id)


def _customer_active_op(request, org_id, *, op, success_msg):
    """Shared POST handler for suspend/reactivate (reason-only form)."""
    customer = selectors.get_customer(org_id)
    if customer is None:
        raise Http404("Customer not found.")
    form = crm_forms.FinancialReasonForm(request.POST)
    if form.is_valid():
        try:
            op(actor=request.user, organization=customer,
               reason=form.cleaned_data["reason"], request=request)
            messages.success(request, success_msg)
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
    else:
        messages.error(request, "A reason is required.")
    return redirect("platform_admin:crm:customer_detail", org_id=customer.id)


@crm_financial_required(methods=("POST",))
def customer_suspend(request, org_id):
    return _customer_active_op(
        request, org_id, op=crm_operations.suspend_customer,
        success_msg="Customer suspended.",
    )


@crm_financial_required(methods=("POST",))
def customer_reactivate(request, org_id):
    return _customer_active_op(
        request, org_id, op=crm_operations.reactivate_customer,
        success_msg="Customer reactivated.",
    )


# ── manual payment operations (CRM-1F-3B-2B) — POST-only, thin views ──────────
@crm_financial_required(methods=("POST",))
def manual_payment_add(request, org_id):
    customer = selectors.get_customer(org_id)
    if customer is None:
        raise Http404("Customer not found.")
    form = crm_forms.ManualPaymentAddForm(request.POST)
    if form.is_valid():
        cd = form.cleaned_data
        try:
            crm_operations.crm_add_manual_payment(
                actor=request.user, organization=customer, plan=cd["plan"],
                amount=cd["amount"], currency=cd["currency"],
                reference=cd["reference"], reason=cd["reason"], request=request,
            )
            messages.success(request, "Manual payment created (pending).")
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
    else:
        messages.error(request, "Could not add manual payment: check the form fields.")
    return redirect("platform_admin:crm:customer_detail", org_id=customer.id)


def _manual_payment_action(request, org_id, payment_id, *, op, success_msg):
    customer = selectors.get_customer(org_id)
    if customer is None:
        raise Http404("Customer not found.")
    payment = selectors.get_payment_for_customer(payment_id, customer)
    if payment is None:
        raise Http404("Payment not found.")  # also covers cross-tenant ids
    form = crm_forms.FinancialReasonForm(request.POST)
    if form.is_valid():
        try:
            op(actor=request.user, organization=customer, payment=payment,
               reason=form.cleaned_data["reason"], request=request)
            messages.success(request, success_msg)
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
    else:
        messages.error(request, "A reason is required.")
    return redirect("platform_admin:crm:customer_detail", org_id=customer.id)


@crm_financial_required(methods=("POST",))
def manual_payment_confirm(request, org_id, payment_id):
    return _manual_payment_action(
        request, org_id, payment_id, op=crm_operations.crm_confirm_manual_payment,
        success_msg="Manual payment confirmed.",
    )


@crm_financial_required(methods=("POST",))
def manual_payment_reject(request, org_id, payment_id):
    return _manual_payment_action(
        request, org_id, payment_id, op=crm_operations.crm_reject_manual_payment,
        success_msg="Manual payment rejected.",
    )


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
        can_manage=can_manage_tickets(request.user),
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
    can_manage = can_manage_tickets(request.user)
    ctx = _crm_context(
        request,
        active_key="crm_tickets",
        crm_title="Ticket Detail",
        ticket=ticket,
        ticket_messages=selectors.get_ticket_messages(ticket),
        audits=selectors.get_ticket_audits(ticket),
        can_manage=can_manage,
        # Choices for the manager-only forms (rendered as CSRF-protected POSTs to
        # the dedicated write routes). Only populated for managers.
        status_choices=SupportTicket.Status.choices if can_manage else None,
        assignable_staff=selectors.get_assignable_crm_staff() if can_manage else None,
    )
    return render(request, "platform_admin/crm/ticket_detail.html", ctx)


# ── ticket write operations (CRM-1E) ──────────────────────────────────────────
@crm_manage_required(methods=("GET", "HEAD", "POST"))
def create_ticket(request):
    if request.method == "POST":
        form = crm_forms.CreateSupportTicketForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            try:
                ticket = crm_operations.create_support_ticket(
                    actor=request.user,
                    organization=cd["organization"],
                    title=cd["title"],
                    description=cd["description"],
                    category=cd["category"],
                    priority=cd["priority"],
                    assigned_to=cd.get("assigned_to"),
                    request=request,
                )
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                messages.success(request, "Support ticket created.")
                return redirect("platform_admin:crm:ticket_detail", ticket_id=ticket.id)
    else:
        initial = {}
        org_id = request.GET.get("organization")
        customer = selectors.get_customer(org_id) if org_id else None
        if customer is not None:
            initial["organization"] = customer.id
        form = crm_forms.CreateSupportTicketForm(initial=initial)

    ctx = _crm_context(
        request,
        active_key="crm_tickets",
        crm_title="New Ticket",
        form=form,
    )
    return render(request, "platform_admin/crm/create_ticket.html", ctx)


def _get_ticket_or_404(ticket_id):
    ticket = selectors.get_ticket(ticket_id)
    if ticket is None:
        raise Http404("Ticket not found.")
    return ticket


@crm_manage_required(methods=("POST",))
def ticket_message(request, ticket_id):
    ticket = _get_ticket_or_404(ticket_id)
    form = crm_forms.TicketMessageForm(request.POST)
    if form.is_valid():
        crm_operations.add_ticket_message(
            actor=request.user,
            ticket=ticket,
            message=form.cleaned_data["message"],
            internal_only=form.cleaned_data["internal_only"],
            request=request,
        )
        messages.success(request, "Message added.")
    else:
        messages.error(request, "Could not add message: message text is required.")
    return redirect("platform_admin:crm:ticket_detail", ticket_id=ticket.id)


@crm_manage_required(methods=("POST",))
def ticket_status(request, ticket_id):
    ticket = _get_ticket_or_404(ticket_id)
    form = crm_forms.TicketStatusUpdateForm(request.POST)
    if form.is_valid():
        try:
            crm_operations.change_ticket_status(
                actor=request.user,
                ticket=ticket,
                new_status=form.cleaned_data["status"],
                reason=form.cleaned_data["reason"],
                request=request,
            )
            messages.success(request, "Ticket status updated.")
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
    else:
        messages.error(request, "Status change requires a valid status and a reason.")
    return redirect("platform_admin:crm:ticket_detail", ticket_id=ticket.id)


@crm_manage_required(methods=("POST",))
def ticket_assign(request, ticket_id):
    ticket = _get_ticket_or_404(ticket_id)
    form = crm_forms.TicketAssignForm(request.POST)
    if form.is_valid():
        try:
            crm_operations.assign_ticket(
                actor=request.user,
                ticket=ticket,
                assigned_to=form.cleaned_data.get("assigned_to"),
                reason=form.cleaned_data["reason"],
                request=request,
            )
            messages.success(request, "Ticket assignment updated.")
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
    else:
        messages.error(request, "Assignment requires a valid staff member and a reason.")
    return redirect("platform_admin:crm:ticket_detail", ticket_id=ticket.id)


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
