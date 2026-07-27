"""Substantive Testing — Inventory / Fixed Assets / Payroll
(TADGEEG-FIN-AUDIT-9D · ISA 501 + substantive procedures).

A uniform substantive-test register: for each item the auditor compares the
recorded (book) value against an independently derived (tested) value and the
system flags a variance outside tolerance. It covers three areas:

  * Inventory (ISA 501)  — counted quantity × unit cost vs book value,
  * Fixed assets         — recomputed net book value (straight-line) vs book,
  * Payroll              — recomputed net pay (gross − deductions) vs recorded.

Deterministic (no AI); organization-scoped; never writes to ``apps.ledger``; a
variance is flagged for the auditor, never auto-corrected.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models

from apps.audit.engagement_models import AuditEngagement
from apps.authentication.models import Organization, User

_AMOUNT = dict(max_digits=20, decimal_places=4)


class SubstantiveTestItem(models.Model):
    """One substantive-test line (book vs independently-tested value)."""

    class Area(models.TextChoices):
        INVENTORY    = "inventory",    "Inventory (ISA 501)"
        FIXED_ASSETS = "fixed_assets", "Fixed assets"
        PAYROLL      = "payroll",      "Payroll"
        OTHER        = "other",        "Other"

    class Status(models.TextChoices):
        OPEN      = "open",      "Open"
        MATCHED   = "matched",   "Matched"
        VARIANCE  = "variance",  "Variance"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="substantive_test_items")
    engagement = models.ForeignKey(
        AuditEngagement, on_delete=models.CASCADE, related_name="substantive_test_items")

    reference = models.CharField(max_length=32, blank=True, db_index=True)
    area = models.CharField(max_length=16, choices=Area.choices, default=Area.INVENTORY,
                            db_index=True)
    item_reference = models.CharField(max_length=128, blank=True)  # SKU / asset tag / emp id
    description = models.CharField(max_length=255, blank=True)

    book_value = models.DecimalField(**_AMOUNT)
    tested_value = models.DecimalField(null=True, blank=True, **_AMOUNT)
    tolerance = models.DecimalField(default=Decimal("0"), **_AMOUNT)

    # Inventory quantities (optional, for display / count sheets).
    quantity_book = models.DecimalField(null=True, blank=True, **_AMOUNT)
    quantity_counted = models.DecimalField(null=True, blank=True, **_AMOUNT)

    # Area-specific recompute inputs (e.g. asset cost/life, payroll gross/ded).
    inputs = models.JSONField(default=dict, blank=True)
    notes = models.TextField(blank=True)

    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.OPEN, db_index=True)

    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="substantive_test_items")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "audit_substantive_test_items"
        ordering = ("area", "-created_at")
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["engagement", "area"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "reference"],
                condition=models.Q(reference__gt=""),
                name="uniq_substantive_reference_per_org"),
        ]

    def __str__(self) -> str:
        return f"Substantive {self.reference or self.id} ({self.area})"

    @property
    def variance(self):
        """book − tested (None until a tested value is recorded)."""
        if self.tested_value is None:
            return None
        return self.book_value - self.tested_value

    @property
    def is_within_tolerance(self):
        v = self.variance
        if v is None:
            return None
        return abs(v) <= (self.tolerance or Decimal("0"))

    def clean(self):
        if self.engagement_id and self.organization_id:
            if self.engagement.organization_id != self.organization_id:
                raise ValidationError(
                    "organization must match engagement.organization.")
