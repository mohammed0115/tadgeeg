"""Engagement planning records (TADGEEG-FIN-AUDIT-9H).

ISA 300 §12 requires the auditor to **document** the overall audit strategy and
the audit plan; ISA 330 and ISA 240 responses are documented likewise. The ISA
assessment pages (8H) compute these deterministically but were stateless. This
model lets the auditor **save** a computed artifact onto an engagement so it
becomes part of the audit file — a dated, attributable record.

One uniform model serves all three artifact kinds via a ``kind`` discriminator;
``payload`` holds the engine output and ``inputs`` the parameters used, so the
record is self-describing and reproducible. Deterministic; organization-scoped;
never writes to ``apps.ledger``; not an audit opinion.
"""
from __future__ import annotations

import uuid

from django.core.exceptions import ValidationError
from django.db import models

from apps.audit.engagement_models import AuditEngagement
from apps.authentication.models import Organization, User


class EngagementPlanningRecord(models.Model):
    """One saved planning/response artifact attached to an engagement."""

    class Kind(models.TextChoices):
        AUDIT_PLAN     = "audit_plan",     "Audit strategy & plan (ISA 300)"
        RISK_RESPONSES = "risk_responses", "Risk responses (ISA 330)"
        FRAUD_PLAN     = "fraud_plan",     "Fraud response plan (ISA 240)"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="planning_records")
    engagement = models.ForeignKey(
        AuditEngagement, on_delete=models.CASCADE, related_name="planning_records")

    kind = models.CharField(max_length=20, choices=Kind.choices, db_index=True)
    title = models.CharField(max_length=255, blank=True)
    # Engine output (strategy+plan / response mappings / fraud plan).
    payload = models.JSONField(default=dict, blank=True)
    # The parameters used to produce it (for reproducibility / audit trail).
    inputs = models.JSONField(default=dict, blank=True)

    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="planning_records")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "audit_engagement_planning_records"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["engagement", "kind", "-created_at"]),
            models.Index(fields=["organization", "kind"]),
        ]

    def __str__(self) -> str:
        return f"PlanningRecord {self.kind} ({self.engagement_id})"

    def clean(self):
        if self.engagement_id and self.organization_id:
            if self.engagement.organization_id != self.organization_id:
                raise ValidationError(
                    "organization must match engagement.organization.")
