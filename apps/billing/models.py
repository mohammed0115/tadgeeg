"""Billing core models.

Design notes:
- ``Plan`` is the catalogue row — name/price/quota — managed by ops and
  seeded via ``manage.py seed_billing_plans``.
- ``OrganizationSubscription`` is a *snapshot* of the plan at purchase
  time. ``invoice_limit`` is duplicated onto the subscription so that
  raising the price or quota on the ``Plan`` row later does NOT silently
  upgrade or downgrade existing customers.
- ``UsageLedger`` is append-only — every reserve/consume/release writes
  a row so audit/finance can answer "where did the 100 invoices go?".

This module is intentionally standalone: no signals, no integration
with the audit pipeline yet. Stage 5 wires it in.
"""
from __future__ import annotations

import uuid

from django.db import models

from apps.authentication.models import Organization
from apps.billing.choices import (
    PlanCode,
    SubscriptionStatus,
    UsageAction,
)


class Plan(models.Model):
    id   = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    code = models.CharField(
        max_length=20, unique=True, choices=PlanCode.choices,
        help_text="Stable identifier used by code and APIs.",
    )

    name_ar = models.CharField(max_length=128)
    name_en = models.CharField(max_length=128)

    description_ar = models.TextField(blank=True, default="")
    description_en = models.TextField(blank=True, default="")

    invoice_limit  = models.PositiveIntegerField(help_text="Invoices auditable per billing period.")
    price          = models.DecimalField(max_digits=10, decimal_places=2)
    currency       = models.CharField(max_length=3, default="SAR")
    duration_days  = models.PositiveIntegerField(default=30)

    is_free  = models.BooleanField(default=False)
    is_trial = models.BooleanField(
        default=False,
        help_text="Trial plans can be activated only once per organisation.",
    )
    is_active = models.BooleanField(default=True)

    sort_order = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "price"]
        indexes  = [models.Index(fields=["is_active", "sort_order"])]

    def __str__(self):
        return f"{self.code} ({self.invoice_limit} inv / {self.price} {self.currency})"


class OrganizationSubscription(models.Model):
    """One row per (org, billing period). ``invoice_limit`` is frozen at
    activation — see module docstring for rationale."""
    id   = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="subscriptions",
    )
    plan = models.ForeignKey(
        Plan, on_delete=models.PROTECT, related_name="subscriptions",
    )

    status = models.CharField(
        max_length=20, choices=SubscriptionStatus.choices,
        default=SubscriptionStatus.PENDING_PAYMENT,
    )

    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at   = models.DateTimeField(null=True, blank=True)

    # Snapshot of the plan's quota at activation time — frozen.
    invoice_limit      = models.PositiveIntegerField(default=0)
    used_invoices      = models.PositiveIntegerField(default=0)
    reserved_invoices  = models.PositiveIntegerField(default=0)

    auto_renew = models.BooleanField(default=False)

    # FK to PaymentTransaction is kept opaque (UUID) so this app stays
    # importable even if apps/payments/ is uninstalled in a deployment.
    payment_transaction = models.UUIDField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["status", "ends_at"]),
        ]

    def __str__(self):
        return f"{self.organization_id} → {self.plan.code} ({self.status})"

    # ---- derived helpers ----
    @property
    def remaining_invoices(self) -> int:
        return max(0, self.invoice_limit - self.used_invoices - self.reserved_invoices)

    @property
    def is_usable(self) -> bool:
        from apps.billing.choices import USABLE_STATUSES
        return self.status in USABLE_STATUSES


class UsageLedger(models.Model):
    """Append-only record of every quota change. Drives forensic
    reconstruction of ``used_invoices`` / ``reserved_invoices`` if the
    counters ever drift from reality."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="usage_ledger_entries",
    )
    subscription = models.ForeignKey(
        OrganizationSubscription, on_delete=models.CASCADE, related_name="ledger_entries",
    )

    # String FKs so this app stays importable even when documents/audit
    # apps aren't in a deployment. Both nullable since reserve happens
    # before audit_run exists.
    document  = models.ForeignKey(
        "documents.Document",       on_delete=models.SET_NULL, null=True, blank=True,
        related_name="billing_ledger_entries",
    )
    audit_run = models.ForeignKey(
        "rule_engine.AuditRun",     on_delete=models.SET_NULL, null=True, blank=True,
        related_name="billing_ledger_entries",
    )

    action   = models.CharField(max_length=10, choices=UsageAction.choices)
    quantity = models.PositiveIntegerField(default=1)
    reason   = models.CharField(max_length=255, blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "action"]),
            models.Index(fields=["subscription", "action"]),
            models.Index(fields=["document", "action"]),
        ]

    def __str__(self):
        return f"{self.organization_id} {self.action} {self.quantity} ({self.created_at:%Y-%m-%d})"
