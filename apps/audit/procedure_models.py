"""Audit procedures — the Risk → Procedure link of the traceability spine
(TADGEEG-G2.2 · ISA 330).

An ``AuditProcedure`` is a planned/performed audit procedure that responds to an
``AssessedRisk``. It is the second link of the chain:

    AssessedRisk → AuditProcedure → Evidence → Finding

Deterministic; organization-scoped; never writes to ``apps.ledger``; advisory.
"""
from __future__ import annotations

import uuid

from django.core.exceptions import ValidationError
from django.db import models

from apps.audit.assessed_risk_models import AssessedRisk
from apps.audit.engagement_models import AuditEngagement
from apps.authentication.models import Organization, User


class AuditProcedure(models.Model):
    """One audit procedure responsive to an assessed risk (ISA 330)."""

    class Nature(models.TextChoices):
        TEST_OF_CONTROLS       = "test_of_controls",       "Test of controls"
        SUBSTANTIVE_ANALYTICAL = "substantive_analytical", "Substantive analytical"
        TEST_OF_DETAILS        = "test_of_details",        "Test of details"

    class Timing(models.TextChoices):
        INTERIM       = "interim",       "Interim"
        YEAR_END      = "year_end",      "Year-end"
        SUBSEQUENT    = "subsequent",    "Subsequent events"
        UNPREDICTABLE = "unpredictable", "Unpredictable"

    class Extent(models.TextChoices):
        REDUCED   = "reduced",   "Reduced"
        STANDARD  = "standard",  "Standard"
        INCREASED = "increased", "Increased"
        ALL       = "all",       "All (100%)"

    class Status(models.TextChoices):
        PLANNED        = "planned",        "Planned"
        IN_PROGRESS    = "in_progress",    "In progress"
        COMPLETED      = "completed",      "Completed"
        NOT_APPLICABLE = "not_applicable", "Not applicable"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="audit_procedures")
    engagement = models.ForeignKey(
        AuditEngagement, on_delete=models.CASCADE, related_name="audit_procedures")
    # The risk this procedure responds to (spine link). Nullable so a procedure
    # can exist before being mapped, but the register is built around it.
    assessed_risk = models.ForeignKey(
        AssessedRisk, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="procedures")

    reference = models.CharField(max_length=32, blank=True, db_index=True)  # PROC-#####
    title = models.CharField(max_length=255)
    nature = models.CharField(max_length=24, choices=Nature.choices,
                              default=Nature.TEST_OF_DETAILS)
    timing = models.CharField(max_length=16, choices=Timing.choices,
                              default=Timing.YEAR_END)
    extent = models.CharField(max_length=12, choices=Extent.choices,
                              default=Extent.STANDARD)
    status = models.CharField(max_length=16, choices=Status.choices,
                              default=Status.PLANNED, db_index=True)

    description = models.TextField(blank=True)
    conclusion = models.TextField(blank=True)

    performed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="performed_procedures")
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="created_procedures")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "audit_procedures"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["engagement", "status"]),
            models.Index(fields=["assessed_risk"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "reference"],
                condition=models.Q(reference__gt=""),
                name="uniq_audit_procedure_reference_per_org"),
        ]

    def __str__(self) -> str:
        return f"AuditProcedure {self.reference or self.id} ({self.title})"

    def clean(self):
        if self.engagement_id and self.organization_id:
            if self.engagement.organization_id != self.organization_id:
                raise ValidationError(
                    "organization must match engagement.organization.")
        if self.assessed_risk_id:
            r = self.assessed_risk
            if r.engagement_id != self.engagement_id or r.organization_id != self.organization_id:
                raise ValidationError(
                    "assessed_risk must belong to the same engagement and organization.")
