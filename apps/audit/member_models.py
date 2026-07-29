"""Engagement team members (TADGEEG-G3.3 · ISA 220).

Assigns users to an engagement with a role and (optionally) responsibilities and
a due date, so an engagement has an explicit team + accountability — the basis
for review routing and sign-off. Additive; organization-scoped; no ledger writes.
"""
from __future__ import annotations

import uuid

from django.core.exceptions import ValidationError
from django.db import models

from apps.audit.engagement_models import AuditEngagement
from apps.authentication.models import Organization, User


class EngagementMember(models.Model):
    """One user's assignment to an engagement, with a role."""

    class Role(models.TextChoices):
        PARTNER  = "partner",  "Engagement partner"
        MANAGER  = "manager",  "Manager"
        EQR      = "eqr",      "EQR partner"
        REVIEWER = "reviewer", "Reviewer"
        PREPARER = "preparer", "Preparer"
        MEMBER   = "member",   "Team member"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="engagement_members")
    engagement = models.ForeignKey(
        AuditEngagement, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="engagement_memberships")

    role = models.CharField(max_length=12, choices=Role.choices, default=Role.MEMBER)
    responsibilities = models.CharField(max_length=255, blank=True)
    due_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    assigned_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="engagement_assignments_made")
    assigned_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "audit_engagement_members"
        ordering = ("role", "assigned_at")
        indexes = [
            models.Index(fields=["engagement", "is_active"]),
            models.Index(fields=["user", "is_active"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["engagement", "user", "role"],
                name="uniq_engagement_member_role"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} as {self.role} on {self.engagement_id}"

    def clean(self):
        if self.engagement_id and self.organization_id:
            if self.engagement.organization_id != self.organization_id:
                raise ValidationError("organization must match engagement.organization.")
        if self.user_id and self.organization_id:
            if getattr(self.user, "organization_id", None) != self.organization_id:
                raise ValidationError("member must belong to the engagement's organization.")
