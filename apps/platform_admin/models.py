"""
Platform CRM core models (CRM-1B).

These models add the *operations* layer for platform staff to manage customers.
The "customer" in CRM is the existing ``authentication.Organization`` — no new
Customer model is introduced. Every relationship points at Organization.

Scope note (CRM-1B): models + permissions + audit/timeline helpers only.
No dashboard, directory, templates, or payment/subscription actions live here.
"""

import uuid

from django.conf import settings
from django.db import models


class SupportTicket(models.Model):
    """A support request raised on behalf of / for a customer organization."""

    class Category(models.TextChoices):
        BILLING = "billing", "Billing"
        TECHNICAL = "technical", "Technical"
        UPLOAD_ISSUE = "upload_issue", "Upload Issue"
        AUDIT_REPORT = "audit_report", "Audit Report"
        SUBSCRIPTION = "subscription", "Subscription"
        ACCOUNT_ACCESS = "account_access", "Account Access"
        COMPLIANCE = "compliance", "Compliance"
        GENERAL = "general", "General"

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        URGENT = "urgent", "Urgent"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        PENDING_CUSTOMER = "pending_customer", "Pending Customer"
        PENDING_INTERNAL = "pending_internal", "Pending Internal"
        RESOLVED = "resolved", "Resolved"
        CLOSED = "closed", "Closed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "authentication.Organization",
        on_delete=models.CASCADE,
        related_name="support_tickets",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_support_tickets",
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_support_tickets",
    )
    title = models.CharField(max_length=255)
    category = models.CharField(
        max_length=20, choices=Category.choices, default=Category.GENERAL
    )
    priority = models.CharField(
        max_length=10, choices=Priority.choices, default=Priority.MEDIUM
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.OPEN
    )
    description = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Support Ticket"
        verbose_name_plural = "Support Tickets"
        indexes = [
            models.Index(fields=["organization", "-created_at"]),
            models.Index(fields=["status"]),
            models.Index(fields=["priority"]),
            models.Index(fields=["assigned_to"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"[{self.get_status_display()}] {self.title} — org={self.organization_id}"


class TicketMessage(models.Model):
    """A message in a support ticket thread. ``internal_only`` is staff-only."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket = models.ForeignKey(
        SupportTicket, on_delete=models.CASCADE, related_name="messages"
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="ticket_messages",
    )
    message = models.TextField()
    internal_only = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "Ticket Message"
        verbose_name_plural = "Ticket Messages"
        indexes = [
            models.Index(fields=["ticket", "created_at"]),
        ]

    def __str__(self):
        scope = "internal" if self.internal_only else "public"
        return f"Message ({scope}) on ticket {self.ticket_id}"


class CustomerNote(models.Model):
    """Internal note about a customer organization. Never shown to the customer."""

    class Category(models.TextChoices):
        SALES = "sales", "Sales"
        SUPPORT = "support", "Support"
        FINANCE = "finance", "Finance"
        RISK = "risk", "Risk"
        GENERAL = "general", "General"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "authentication.Organization",
        on_delete=models.CASCADE,
        related_name="crm_notes",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="authored_crm_notes",
    )
    category = models.CharField(
        max_length=20, choices=Category.choices, default=Category.GENERAL
    )
    note = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Customer Note"
        verbose_name_plural = "Customer Notes"
        indexes = [
            models.Index(fields=["organization", "-created_at"]),
            models.Index(fields=["category"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"{self.get_category_display()} note on org={self.organization_id}"


class CustomerActivity(models.Model):
    """
    Internal CRM timeline for a customer organization.

    This is a *display* timeline for the CRM. It does NOT replace the formal
    security record in ``authentication.AuditLog`` — it complements it.
    """

    class ActivityType(models.TextChoices):
        TICKET_CREATED = "ticket_created", "Ticket Created"
        TICKET_MESSAGE_ADDED = "ticket_message_added", "Ticket Message Added"
        TICKET_STATUS_CHANGED = "ticket_status_changed", "Ticket Status Changed"
        NOTE_ADDED = "note_added", "Note Added"
        CRM_ROLE_CHECKED = "crm_role_checked", "CRM Role Checked"
        CRM_AUDIT_LOGGED = "crm_audit_logged", "CRM Audit Logged"
        CUSTOMER_VIEWED = "customer_viewed", "Customer Viewed"
        GENERAL = "general", "General"
        # CRM-1F financial operations. Values are unchanged from the literals
        # previously recorded by crm_operations.py — this only makes them
        # canonical enum members (no stored-value or behavior change).
        SUBSCRIPTION_EXTENDED = "subscription_extended", "Subscription Extended"
        CUSTOMER_SUSPENDED = "customer_suspended", "Customer Suspended"
        CUSTOMER_REACTIVATED = "customer_reactivated", "Customer Reactivated"
        MANUAL_PAYMENT_ADDED = "manual_payment_added", "Manual Payment Added"
        MANUAL_PAYMENT_CONFIRMED = "manual_payment_confirmed", "Manual Payment Confirmed"
        MANUAL_PAYMENT_REJECTED = "manual_payment_rejected", "Manual Payment Rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "authentication.Organization",
        on_delete=models.CASCADE,
        related_name="crm_activities",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="crm_activities",
    )
    activity_type = models.CharField(
        max_length=32, choices=ActivityType.choices, default=ActivityType.GENERAL
    )
    description = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Customer Activity"
        verbose_name_plural = "Customer Activities"
        indexes = [
            models.Index(fields=["organization", "-created_at"]),
            models.Index(fields=["activity_type"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"{self.get_activity_type_display()} on org={self.organization_id}"
