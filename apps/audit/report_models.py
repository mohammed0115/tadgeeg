"""Engagement report (TADGEEG-G6).

A versioned engagement report assembled from the traceability spine (risks,
procedures, findings, issues) with a draft → in_review → final lifecycle. It is
explicitly **not an audit opinion** (ISA 700-safe): it never emits "In our
opinion" / "present fairly"; it carries a disclaimer and reports facts only.

Deterministic; organization-scoped; never writes to ``apps.ledger``.
"""
from __future__ import annotations

import uuid

from django.core.exceptions import ValidationError
from django.db import models

from apps.audit.engagement_models import AuditEngagement
from apps.authentication.models import Organization, User


class EngagementReport(models.Model):
    """One versioned engagement report snapshot."""

    class Status(models.TextChoices):
        DRAFT     = "draft",     "Draft"
        IN_REVIEW = "in_review", "In review"
        FINAL     = "final",     "Final"
        ARCHIVED  = "archived",  "Archived"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="engagement_reports")
    engagement = models.ForeignKey(
        AuditEngagement, on_delete=models.CASCADE, related_name="reports")

    reference = models.CharField(max_length=32, blank=True, db_index=True)  # REP-#####
    title = models.CharField(max_length=255, blank=True)
    version = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=12, choices=Status.choices,
                              default=Status.DRAFT, db_index=True)

    # Assembled snapshot (counts + findings + issues + disclaimer).
    content = models.JSONField(default=dict, blank=True)
    # ISA 700 guardrail — always a communication of facts, never an opinion.
    not_an_opinion = models.BooleanField(default=True)

    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="engagement_reports")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    finalized_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "audit_engagement_reports"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["engagement", "-version"]),
            models.Index(fields=["organization", "status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "reference"],
                condition=models.Q(reference__gt=""),
                name="uniq_engagement_report_reference_per_org"),
        ]

    def __str__(self) -> str:
        return f"EngagementReport {self.reference or self.id} v{self.version} ({self.status})"

    def clean(self):
        if self.engagement_id and self.organization_id:
            if self.engagement.organization_id != self.organization_id:
                raise ValidationError("organization must match engagement.organization.")
