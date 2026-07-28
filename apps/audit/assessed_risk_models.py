"""Assessed Risks of Material Misstatement — the traceability spine anchor
(TADGEEG-G2 · ISA 315).

An ``AssessedRisk`` is a first-class, persisted risk of material misstatement
(ROMM) at the assertion level. It is the anchor of the audit chain:

    AssessedRisk → (Control) → Procedure → Evidence → Finding → Report

Before G2, ISA 315/330 lived only as stateless calculators and opaque JSON
snapshots (``EngagementPlanningRecord``); this makes the risk a linkable entity
so responses, procedures, evidence and findings can reference it and an auditor
can walk the chain end-to-end.

Deterministic; organization-scoped; never writes to ``apps.ledger``; advisory.
"""
from __future__ import annotations

import uuid

from django.core.exceptions import ValidationError
from django.db import models

from apps.audit.engagement_models import AuditEngagement
from apps.authentication.models import Organization, User

# Combined-risk ranking (mirrors isa330_risk_responses so the two agree).
_RANK = {"low": 1, "medium": 2, "high": 3, "significant": 4}


class AssessedRisk(models.Model):
    """One assessed risk of material misstatement (ISA 315), assertion-level."""

    class Assertion(models.TextChoices):
        EXISTENCE          = "existence",          "Existence / Occurrence"
        COMPLETENESS       = "completeness",       "Completeness"
        ACCURACY           = "accuracy",           "Accuracy"
        CUTOFF             = "cutoff",             "Cut-off"
        CLASSIFICATION     = "classification",     "Classification"
        VALUATION          = "valuation",          "Valuation / Allocation"
        RIGHTS_OBLIGATIONS = "rights_obligations", "Rights & obligations"
        PRESENTATION       = "presentation",       "Presentation & disclosure"

    class InherentRisk(models.TextChoices):
        LOW         = "low",         "Low"
        MEDIUM      = "medium",      "Medium"
        HIGH        = "high",        "High"
        SIGNIFICANT = "significant", "Significant"

    class ControlRisk(models.TextChoices):
        LOW    = "low",    "Low"
        MEDIUM = "medium", "Medium"
        HIGH   = "high",   "High"

    class Status(models.TextChoices):
        IDENTIFIED = "identified", "Identified"     # assessed, no response yet
        RESPONDED  = "responded",  "Responded"      # procedures designed (ISA 330)
        TESTED     = "tested",     "Tested"         # procedures performed
        CONCLUDED  = "concluded",  "Concluded"      # conclusion reached
        CLOSED     = "closed",     "Closed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="assessed_risks")
    engagement = models.ForeignKey(
        AuditEngagement, on_delete=models.CASCADE, related_name="assessed_risks")

    reference = models.CharField(max_length=32, blank=True, db_index=True)  # RISK-#####
    title = models.CharField(max_length=255)
    # Financial-statement area (e.g. revenue, receivables, inventory). Free text
    # so it can hold the account grouping the engagement actually uses.
    fs_area = models.CharField(max_length=120, blank=True, db_index=True)
    assertion = models.CharField(max_length=20, choices=Assertion.choices,
                                 default=Assertion.EXISTENCE, db_index=True)

    inherent_risk = models.CharField(max_length=12, choices=InherentRisk.choices,
                                     default=InherentRisk.MEDIUM)
    control_risk = models.CharField(max_length=12, choices=ControlRisk.choices,
                                    default=ControlRisk.MEDIUM)
    is_significant = models.BooleanField(default=False)
    is_fraud_risk = models.BooleanField(default=False)

    description = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    status = models.CharField(max_length=12, choices=Status.choices,
                              default=Status.IDENTIFIED, db_index=True)

    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="assessed_risks")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "audit_assessed_risks"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["engagement", "status"]),
            models.Index(fields=["organization", "assertion"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "reference"],
                condition=models.Q(reference__gt=""),
                name="uniq_assessed_risk_reference_per_org"),
        ]

    def __str__(self) -> str:
        return f"AssessedRisk {self.reference or self.id} ({self.title})"

    @property
    def combined_risk(self) -> str:
        """Combined risk = max(inherent, control); significant/fraud force
        'significant'. Drives the ISA 330 response strength."""
        if self.is_significant or self.is_fraud_risk:
            return "significant"
        rank = max(_RANK.get(self.inherent_risk, 0), _RANK.get(self.control_risk, 0))
        for name, value in _RANK.items():
            if value == rank:
                return name
        return "low"

    def clean(self):
        if self.engagement_id and self.organization_id:
            if self.engagement.organization_id != self.organization_id:
                raise ValidationError(
                    "organization must match engagement.organization.")
