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

from apps.authentication.models import Organization
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


# ── CRM-1F-1B — financial operation: extend subscription ──────────────────────
# Financial activity types are canonical ``CustomerActivity.ActivityType`` enum
# members (CRM-1F-TD-A); values are unchanged from the former literals.


def _require_financial_manager(actor):
    if not perms.can_manage_financial_crm_data(actor):
        raise PermissionDenied("Financial management permission is required.")


def crm_extend_subscription(
    *,
    actor,
    organization,
    subscription,
    days,
    reason,
    request=None,
):
    """
    CRM wrapper around the official ``billing.extend_subscription`` service.

    The wrapper owns: permission gate (``can_manage_financial_crm_data``),
    tenant-ownership check, reason requirement, and the AuditLog +
    CustomerActivity trail. The actual ``ends_at`` change is delegated to the
    billing service (atomic + row-locked) — this wrapper NEVER writes
    ``subscription.ends_at`` (or plan/status/quota/payment) directly, creates no
    PaymentTransaction, and emits no signals.

    Raises ``PermissionDenied`` (unauthorized) or ``ValidationError``
    (missing reason / bad days / cross-tenant). Returns the updated subscription.
    """
    from apps.billing.services.subscription_service import SubscriptionService

    _require_financial_manager(actor)

    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("A reason is required to extend a subscription.")
    if isinstance(days, bool) or not isinstance(days, int):
        raise ValidationError("days must be a positive integer.")
    if days <= 0:
        raise ValidationError("days must be a positive integer.")
    if subscription.organization_id != organization.id:
        raise ValidationError("Subscription does not belong to this organization.")

    old_ends_at = subscription.ends_at

    # Outer atomic so the billing extend + audit + activity commit together. The
    # billing service is itself atomic + select_for_update; nesting here keeps the
    # row lock held through the audit writes without breaking it.
    with transaction.atomic():
        updated = SubscriptionService().extend_subscription(
            subscription, days=days, reason=reason, actor=actor
        )
        new_ends_at = updated.ends_at
        old_iso = old_ends_at.isoformat() if old_ends_at else None
        new_iso = new_ends_at.isoformat() if new_ends_at else None

        record_customer_activity(
            organization=organization,
            actor=actor,
            activity_type=CustomerActivity.ActivityType.SUBSCRIPTION_EXTENDED,
            description=f"Subscription extended by {days} day(s)",
            metadata={
                "subscription_id": str(subscription.id),
                "days": days,
                "old_ends_at": old_iso,
                "new_ends_at": new_iso,
            },
        )
        log_crm_action(
            actor=actor,
            organization=organization,
            action_type="subscription_extended",
            resource_type="OrganizationSubscription",
            resource_id=subscription.id,
            reason=reason,
            old_value={"ends_at": old_iso},
            new_value={"ends_at": new_iso, "days": days},
            ip_address=_client_ip(request),
            record_activity=False,
        )
    return updated


# ── CRM-1F-2B — suspend / reactivate customer (Organization.is_active) ────────


def _set_customer_active(*, actor, organization, target_active, reason, request):
    """
    Flip Organization.is_active to ``target_active`` (the suspend/reactivate
    lever). Writes ONLY ``is_active`` — never subscription/quota/payment. Audited.
    """
    _require_financial_manager(actor)
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("A reason is required.")

    with transaction.atomic():
        org = Organization.objects.select_for_update().get(pk=organization.pk)
        if org.is_active == target_active:
            raise ValidationError(
                "Customer is already active." if target_active
                else "Customer is already suspended."
            )
        org.is_active = target_active
        org.save(update_fields=["is_active", "updated_at"])

        if target_active:
            action_type = "customer_reactivated"
            activity_type = CustomerActivity.ActivityType.CUSTOMER_REACTIVATED
            description = "Customer reactivated"
            old_value, new_value = {"is_active": False}, {"is_active": True}
        else:
            action_type = "customer_suspended"
            activity_type = CustomerActivity.ActivityType.CUSTOMER_SUSPENDED
            description = "Customer suspended"
            old_value, new_value = {"is_active": True}, {"is_active": False}

        record_customer_activity(
            organization=org,
            actor=actor,
            activity_type=activity_type,
            description=description,
            metadata={"reason": reason},
        )
        log_crm_action(
            actor=actor,
            organization=org,
            action_type=action_type,
            resource_type="Organization",
            resource_id=org.id,
            reason=reason,
            old_value=old_value,
            new_value=new_value,
            ip_address=_client_ip(request),
            record_activity=False,
        )
    return org


def suspend_customer(*, actor, organization, reason, request=None):
    """Suspend a customer: Organization.is_active → False. Rejects double-suspend."""
    return _set_customer_active(
        actor=actor, organization=organization, target_active=False,
        reason=reason, request=request,
    )


def reactivate_customer(*, actor, organization, reason, request=None):
    """Reactivate a customer: Organization.is_active → True. Rejects double-reactivate."""
    return _set_customer_active(
        actor=actor, organization=organization, target_active=True,
        reason=reason, request=request,
    )


# ── CRM-1F-3B-2A — manual payment wrappers ────────────────────────────────────


def _manual_payment_safe(payment, *, plan=None) -> dict:
    """Safe, JSON-serialisable snapshot for audit/activity. NEVER includes
    raw_request/raw_response/raw_webhook/provider_payment_id/checkout_url/
    idempotency_key or any secret."""
    return {
        "payment_id": str(payment.id),
        "provider": payment.provider,
        "status": payment.status,
        "amount": str(payment.amount),
        "currency": payment.currency,
        "reference": payment.provider_reference,
        "subscription_id": str(payment.reference_id) if payment.reference_id else None,
        "plan_id": str(plan.id) if plan is not None else None,
    }


def crm_add_manual_payment(
    *, actor, organization, plan, amount, currency, reference, reason, request=None,
):
    """
    Create a PENDING manual payment for a new pending subscription — via the
    official billing + payment services only (no direct PaymentTransaction or
    OrganizationSubscription writes). Does NOT activate / mark_paid.
    """
    _require_financial_manager(actor)
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("A reason is required.")
    reference = (reference or "").strip()
    if not reference:
        raise ValidationError("A payment reference is required.")

    from apps.billing.choices import USABLE_STATUSES
    from apps.billing.models import OrganizationSubscription
    from apps.billing.services.subscription_service import (
        SubscriptionError,
        SubscriptionService,
    )
    from apps.payments.choices import PaymentProvider, PaymentPurpose, PaymentStatus
    from apps.payments.models import PaymentTransaction
    from apps.payments.services.payment_service import (
        PaymentService,
        PaymentValidationError,
    )

    # Defense in depth (the payment service also guards): no usable subscription,
    # and no existing pending manual payment for this customer.
    if OrganizationSubscription.objects.filter(
        organization=organization, status__in=USABLE_STATUSES
    ).exists():
        raise ValidationError("Organization already has a usable subscription.")
    if PaymentTransaction.objects.filter(
        organization=organization,
        provider=PaymentProvider.MANUAL.value,
        status=PaymentStatus.PENDING,
        purpose=PaymentPurpose.SUBSCRIPTION.value,
    ).exists():
        raise ValidationError("A pending manual payment already exists for this customer.")

    try:
        with transaction.atomic():
            subscription = SubscriptionService().create_pending_paid_subscription(
                organization, plan
            )
            payment = PaymentService().create_manual_payment(
                organization=organization,
                user=actor,
                subscription=subscription,
                amount=amount,
                currency=currency,
                reference=reference,
                reason=reason,
                request=request,
            )
            safe = _manual_payment_safe(payment, plan=plan)
            record_customer_activity(
                organization=organization,
                actor=actor,
                activity_type=CustomerActivity.ActivityType.MANUAL_PAYMENT_ADDED,
                description=f"Manual payment added (reference={reference})",
                metadata=safe,
            )
            log_crm_action(
                actor=actor,
                organization=organization,
                action_type="manual_payment_added",
                resource_type="PaymentTransaction",
                resource_id=payment.id,
                reason=reason,
                new_value=safe,
                ip_address=_client_ip(request),
                record_activity=False,
            )
    except (SubscriptionError, PaymentValidationError) as exc:
        raise ValidationError(str(exc))
    return payment


def crm_confirm_manual_payment(
    *, actor, organization, payment, reason, request=None,
):
    """
    Confirm a pending manual payment via ``PaymentService.mark_paid`` — which
    runs the existing payment_paid → subscription-activation signal chain. Never
    writes payment.status directly, never calls a gateway/webhook.
    """
    _require_financial_manager(actor)
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("A reason is required.")

    from apps.billing.choices import USABLE_STATUSES, SubscriptionStatus
    from apps.billing.models import OrganizationSubscription
    from apps.payments.choices import PaymentProvider, PaymentPurpose, PaymentStatus
    from apps.payments.services.payment_service import PaymentService

    if payment.organization_id != organization.id:
        raise ValidationError("Payment does not belong to this organization.")
    if payment.provider != PaymentProvider.MANUAL.value:
        raise ValidationError("Only manual payments can be confirmed here.")
    if payment.status != PaymentStatus.PENDING:
        raise ValidationError("Only a pending manual payment can be confirmed.")
    if (
        payment.purpose != PaymentPurpose.SUBSCRIPTION.value
        or payment.reference_type != "organization_subscription"
    ):
        raise ValidationError("Payment is not linked to a subscription.")

    old = _manual_payment_safe(payment)
    with transaction.atomic():
        # Confirm-time double-active guard. Between add and confirm the org may
        # have gained a usable subscription (e.g. a hosted payment). Confirming
        # now would mark_paid → activate this pending subscription and hit the
        # one-usable-per-org constraint, leaving the payment PAID with no active
        # subscription. Re-check under a row lock BEFORE mark_paid.
        try:
            sub = (
                OrganizationSubscription.objects
                .select_for_update()
                .get(pk=payment.reference_id, organization_id=organization.id)
            )
        except (OrganizationSubscription.DoesNotExist, ValueError):
            raise ValidationError("Linked subscription not found for this organization.")
        if sub.status != SubscriptionStatus.PENDING_PAYMENT:
            raise ValidationError(
                "The linked subscription is no longer pending payment."
            )
        if (
            OrganizationSubscription.objects
            .filter(organization_id=organization.id, status__in=USABLE_STATUSES)
            .exclude(pk=sub.pk)
            .exists()
        ):
            raise ValidationError(
                "Organization now has a usable subscription; confirming would "
                "create a second active subscription."
            )

        ok = PaymentService().mark_paid(payment, payload={"source": "crm_manual_confirm"})
        if not ok:  # already paid (defensive — status check above usually catches it)
            raise ValidationError("Payment was already confirmed.")
        payment.refresh_from_db()
        new = _manual_payment_safe(payment)
        record_customer_activity(
            organization=organization,
            actor=actor,
            activity_type=CustomerActivity.ActivityType.MANUAL_PAYMENT_CONFIRMED,
            description="Manual payment confirmed",
            metadata=new,
        )
        log_crm_action(
            actor=actor,
            organization=organization,
            action_type="manual_payment_confirmed",
            resource_type="PaymentTransaction",
            resource_id=payment.id,
            reason=reason,
            old_value=old,
            new_value=new,
            ip_address=_client_ip(request),
            record_activity=False,
        )
    return payment


def crm_reject_manual_payment(
    *, actor, organization, payment, reason, request=None,
):
    """
    Reject a pending manual payment via ``PaymentService.mark_canceled``. Does
    NOT activate the subscription. Paid payments cannot be rejected.
    """
    _require_financial_manager(actor)
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("A reason is required.")

    from apps.payments.choices import PaymentProvider, PaymentStatus
    from apps.payments.services.payment_service import PaymentService

    if payment.organization_id != organization.id:
        raise ValidationError("Payment does not belong to this organization.")
    if payment.provider != PaymentProvider.MANUAL.value:
        raise ValidationError("Only manual payments can be rejected here.")
    if payment.status != PaymentStatus.PENDING:
        raise ValidationError("Only a pending manual payment can be rejected.")

    old = _manual_payment_safe(payment)
    with transaction.atomic():
        ok = PaymentService().mark_canceled(payment, payload={"source": "crm_manual_reject"})
        if not ok:
            raise ValidationError("Payment is no longer pending.")
        payment.refresh_from_db()
        new = _manual_payment_safe(payment)
        record_customer_activity(
            organization=organization,
            actor=actor,
            activity_type=CustomerActivity.ActivityType.MANUAL_PAYMENT_REJECTED,
            description="Manual payment rejected",
            metadata=new,
        )
        log_crm_action(
            actor=actor,
            organization=organization,
            action_type="manual_payment_rejected",
            resource_type="PaymentTransaction",
            resource_id=payment.id,
            reason=reason,
            old_value=old,
            new_value=new,
            ip_address=_client_ip(request),
            record_activity=False,
        )
    return payment
