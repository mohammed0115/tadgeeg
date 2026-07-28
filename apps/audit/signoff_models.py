"""Engagement review & sign-off (TADGEEG-G3 · ISA 220/230).

A generic, additive sign-off record that attaches a reviewer role to any
engagement artifact (working paper, procedure, risk, finding, readiness
workpaper, or the engagement itself). It closes the review-governance gap: an
engagement can now capture preparer → reviewer → partner sign-off, and the
service enforces the segregation rule that a preparer cannot review their own
work (ISA 220).

Deterministic; organization-scoped; never writes to ``apps.ledger``; advisory.
"""
from __future__ import annotations

import uuid

from django.core.exceptions import ValidationError
from django.db import models

from apps.audit.engagement_models import AuditEngagement
from apps.authentication.models import Organization, User


class EngagementSignoff(models.Model):
    """One sign-off on an engagement artifact by a role (append-only in spirit)."""

    class Role(models.TextChoices):
        PREPARER = "preparer", "Preparer"
        REVIEWER = "reviewer", "Reviewer"
        PARTNER  = "partner",  "Engagement partner"
        EQR      = "eqr",      "EQR partner"

    # Roles that must not be performed by whoever prepared the artifact.
    REVIEW_ROLES = frozenset({Role.REVIEWER, Role.PARTNER, Role.EQR})

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="engagement_signoffs")
    engagement = models.ForeignKey(
        AuditEngagement, on_delete=models.CASCADE, related_name="signoffs")

    # Generic reference to any artifact — kept decoupled so sign-off works across
    # working papers, procedures, risks, findings, reports, etc.
    artifact_type = models.CharField(max_length=40, db_index=True)
    artifact_id = models.CharField(max_length=64, db_index=True)

    role = models.CharField(max_length=12, choices=Role.choices)
    signed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="engagement_signoffs")
    note = models.TextField(blank=True)
    signed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "audit_engagement_signoffs"
        ordering = ("-signed_at",)
        indexes = [
            models.Index(fields=["engagement", "artifact_type", "artifact_id"]),
            models.Index(fields=["organization", "role"]),
        ]

    def __str__(self) -> str:
        return f"{self.role} sign-off on {self.artifact_type}:{self.artifact_id}"

    def clean(self):
        if self.engagement_id and self.organization_id:
            if self.engagement.organization_id != self.organization_id:
                raise ValidationError(
                    "organization must match engagement.organization.")
