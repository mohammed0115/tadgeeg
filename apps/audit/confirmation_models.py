"""External Confirmations (TADGEEG-FIN-AUDIT-9C · ISA 505).

An auditor requests an external party (customer, supplier, bank) to confirm a
recorded balance, tracks the reply, and reconciles the confirmed amount against
the books. A secure per-request token backs an optional public response page so
the external party can reply without an account.

Safety boundaries (same as the surrounding audit app): organization-scoped and
validated against its engagement; never writes to ``apps.ledger``; no AI; no
audit opinion — a discrepancy is flagged for the auditor, not auto-resolved.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models

from apps.audit.engagement_models import AuditEngagement
from apps.authentication.models import Organization, User

_AMOUNT = dict(max_digits=20, decimal_places=4)


class AuditConfirmationRequest(models.Model):
    """One ISA 505 external confirmation request + its reconciliation."""

    class ConfirmationType(models.TextChoices):
        RECEIVABLE = "receivable", "Customer balance (receivable)"
        PAYABLE    = "payable",    "Supplier balance (payable)"
        BANK       = "bank",       "Bank balance"
        OTHER      = "other",      "Other"

    class Status(models.TextChoices):
        DRAFT      = "draft",      "Draft"
        SENT       = "sent",       "Sent"
        RESPONDED  = "responded",  "Responded"
        MATCHED    = "matched",    "Matched"
        DISCREPANCY = "discrepancy", "Discrepancy"
        NO_REPLY   = "no_reply",   "No reply"
        CANCELLED  = "cancelled",  "Cancelled"

    FINAL_STATUSES = frozenset({Status.MATCHED, Status.DISCREPANCY,
                                Status.NO_REPLY, Status.CANCELLED})

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="confirmation_requests")
    engagement = models.ForeignKey(
        AuditEngagement, on_delete=models.CASCADE, related_name="confirmation_requests")

    request_number = models.CharField(max_length=32, blank=True, db_index=True)
    confirmation_type = models.CharField(
        max_length=12, choices=ConfirmationType.choices,
        default=ConfirmationType.RECEIVABLE)

    party_name = models.CharField(max_length=255)
    party_reference = models.CharField(max_length=128, blank=True)
    party_email = models.EmailField(blank=True)

    recorded_amount = models.DecimalField(**_AMOUNT)
    confirmed_amount = models.DecimalField(null=True, blank=True, **_AMOUNT)
    currency = models.CharField(max_length=8, blank=True, default="SAR")
    # Absolute tolerance under which recorded vs confirmed is treated as matched.
    tolerance = models.DecimalField(default=Decimal("0"), **_AMOUNT)

    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.DRAFT, db_index=True)
    # Unguessable token for the public response page (ISA 505 external reply).
    response_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    response_note = models.TextField(blank=True)

    requested_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="requested_confirmations")
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="reviewed_confirmations")
    sent_at = models.DateTimeField(null=True, blank=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "audit_confirmation_requests"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["engagement", "-created_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "request_number"],
                condition=models.Q(request_number__gt=""),
                name="uniq_confirmation_number_per_org"),
        ]

    def __str__(self) -> str:
        return f"Confirmation {self.request_number or self.id} ({self.status})"

    @property
    def is_final(self) -> bool:
        return self.status in self.FINAL_STATUSES

    @property
    def difference(self):
        """recorded − confirmed (None until a response is recorded)."""
        if self.confirmed_amount is None:
            return None
        return self.recorded_amount - self.confirmed_amount

    @property
    def is_within_tolerance(self):
        diff = self.difference
        if diff is None:
            return None
        return abs(diff) <= (self.tolerance or Decimal("0"))

    def clean(self):
        if self.engagement_id and self.organization_id:
            if self.engagement.organization_id != self.organization_id:
                raise ValidationError(
                    "organization must match engagement.organization.")
