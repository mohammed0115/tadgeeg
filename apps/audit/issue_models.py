"""Audit issues — the issue → remediation → closure loop (TADGEEG-G3.2).

An ``AuditIssue`` is an observation/exception raised during the engagement with a
full lifecycle: owner, due date, remediation plan, management response, and
closure. It can hang off the traceability spine (``assessed_risk``) and/or a
source ``gl_finding``. Complements 9B control deficiencies (which carry their own
loop) with a general engagement issue register.

Deterministic; organization-scoped; never writes to ``apps.ledger``; advisory.
"""
from __future__ import annotations

import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.audit.engagement_models import AuditEngagement
from apps.audit.general_ledger_models import GeneralLedgerRiskFinding
from apps.authentication.models import Organization, User


class AuditIssue(models.Model):
    """One engagement issue with a remediation/closure lifecycle."""

    class Severity(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        CRITICAL = "critical", "Critical"

    class Status(models.TextChoices):
        OPEN           = "open",            "Open"
        IN_REMEDIATION = "in_remediation",  "In remediation"
        REMEDIATED     = "remediated",      "Remediated"
        ACCEPTED_RISK  = "accepted_risk",   "Accepted risk"
        CLOSED         = "closed",          "Closed"

    CLOSED_STATUSES = frozenset({Status.REMEDIATED, Status.ACCEPTED_RISK, Status.CLOSED})

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="audit_issues")
    engagement = models.ForeignKey(
        AuditEngagement, on_delete=models.CASCADE, related_name="audit_issues")

    reference = models.CharField(max_length=32, blank=True, db_index=True)  # ISSUE-#####
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    severity = models.CharField(max_length=10, choices=Severity.choices,
                                default=Severity.MEDIUM, db_index=True)

    # Spine + source links (nullable, additive).
    assessed_risk = models.ForeignKey(
        "audit.AssessedRisk", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="issues")
    gl_finding = models.ForeignKey(
        GeneralLedgerRiskFinding, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="issues")

    # Remediation loop.
    owner = models.CharField(max_length=160, blank=True)  # management owner (name/role)
    owner_user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="owned_issues")  # may be a client (auditee) user
    due_date = models.DateField(null=True, blank=True)
    remediation_plan = models.TextField(blank=True)
    management_response = models.TextField(blank=True)

    status = models.CharField(max_length=16, choices=Status.choices,
                              default=Status.OPEN, db_index=True)
    raised_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="raised_issues")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "audit_issues"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["engagement", "status"]),
            models.Index(fields=["organization", "severity"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "reference"],
                condition=models.Q(reference__gt=""),
                name="uniq_audit_issue_reference_per_org"),
        ]

    def __str__(self) -> str:
        return f"AuditIssue {self.reference or self.id} ({self.title})"

    @property
    def is_open(self) -> bool:
        return self.status not in self.CLOSED_STATUSES

    @property
    def is_overdue(self) -> bool:
        return bool(self.due_date and self.is_open
                    and self.due_date < timezone.now().date())

    def clean(self):
        if self.engagement_id and self.organization_id:
            if self.engagement.organization_id != self.organization_id:
                raise ValidationError("organization must match engagement.organization.")
        for fk_name in ("assessed_risk", "gl_finding"):
            obj = getattr(self, fk_name, None)
            if obj is not None:
                if obj.engagement_id != self.engagement_id or obj.organization_id != self.organization_id:
                    raise ValidationError(
                        f"{fk_name} must belong to the same engagement and organization.")
