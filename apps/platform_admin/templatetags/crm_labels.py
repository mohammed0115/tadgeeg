"""Translated, display-safe labels for CRM enum/literal values.

Some activity values (notably "ticket_assigned") are stored as literals that are
NOT members of CustomerActivity.ActivityType, so `get_activity_type_display`
returns the raw value (e.g. "ticket_assigned") — which then leaks into the
Arabic UI. Payment status labels live on PaymentStatus as plain (untranslated)
strings, so `get_status_display` shows English ("Initiated") under Arabic too.

These filters map the stored value → a gettext string WITHOUT touching the
stored data, the enums, or the payments app (so no migration is needed). Unknown
values fall back to the raw value rather than crashing.
"""
from django import template
from django.utils.translation import gettext_lazy as _

register = template.Library()

_ACTIVITY_LABELS = {
    "ticket_created": _("Ticket created"),
    "ticket_assigned": _("Ticket assigned"),
    "ticket_message_added": _("Ticket message added"),
    "ticket_status_changed": _("Ticket status changed"),
    "note_added": _("Note added"),
    "crm_role_checked": _("CRM role checked"),
    "crm_audit_logged": _("CRM audit logged"),
    "customer_viewed": _("Customer viewed"),
    "general": _("General activity"),
    "subscription_extended": _("Subscription extended"),
    "customer_suspended": _("Customer suspended"),
    "customer_reactivated": _("Customer reactivated"),
    "manual_payment_added": _("Manual payment added"),
    "manual_payment_confirmed": _("Manual payment confirmed"),
    "manual_payment_rejected": _("Manual payment rejected"),
}

_PAYMENT_STATUS_LABELS = {
    "pending": _("Pending"),
    "initiated": _("Initiated"),
    "redirect_required": _("Redirect required"),
    "paid": _("Paid"),
    "failed": _("Failed"),
    "canceled": _("Canceled"),
    "expired": _("Expired"),
    "refunded": _("Refunded"),
    "partially_refunded": _("Partially refunded"),
}


@register.filter
def activity_label(value):
    """Human, translated label for a CustomerActivity.activity_type value."""
    return _ACTIVITY_LABELS.get(value, value)


@register.filter
def payment_status_label(value):
    """Human, translated label for a PaymentStatus value."""
    return _PAYMENT_STATUS_LABELS.get(value, value)
