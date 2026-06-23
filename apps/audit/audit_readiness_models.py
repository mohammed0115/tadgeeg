"""Audit Readiness / Opinion Preparation Workpaper (TADGEEG-FIN-AUDIT-5A).

A working aid that consolidates the SAD conclusion, management responses and
proposed adjustments to help a licensed auditor PREPARE an opinion. It is
explicitly **not** a formal audit opinion: it never asserts "in our opinion" or
"present fairly", never issues unqualified/qualified/adverse/disclaimer
opinions, never calls the ISA-700 opinion service to issue one, and never writes
to ``apps.ledger``. Any suggested direction is phrased as "subject to auditor
review". The final opinion belongs to the licensed auditor.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models

from apps.audit.audit_difference_models import AuditDifferenceSummary
from apps.audit.engagement_models import AuditEngagement
from apps.authentication.models import Organization, User

_AMOUNT = dict(max_digits=20, decimal_places=4, default=Decimal("0"))

LEGAL_DISCLAIMER = (
    "This workpaper is an AI-assisted audit readiness and opinion preparation "
    "aid. It does not constitute a formal audit opinion. The final audit "
    "opinion must be prepared and approved by a licensed auditor based on "
    "professional judgment and sufficient appropriate audit evidence."
)


class AuditReadinessWorkpaper(models.Model):
    """Engagement-level audit-readiness aid built from the current SAD."""

    class Status(models.TextChoices):
        DRAFT                   = "draft",                   "Draft"
        GENERATED               = "generated",               "Generated"
        AUDITOR_REVIEW_REQUIRED = "auditor_review_required", "Auditor review required"
        REVIEWED                = "reviewed",                "Reviewed"
        ARCHIVED                = "archived",                "Archived"

    class ReadinessConclusion(models.TextChoices):
        NO_ACCEPTED_DIFFERENCES        = "no_accepted_differences",        "No accepted differences"
        DIFFERENCES_BELOW_MATERIALITY  = "differences_below_materiality",  "Differences below materiality"
        UNADJUSTED_NEED_EVALUATION     = "unadjusted_differences_need_evaluation", "Unadjusted differences need evaluation"
        POSSIBLE_MATERIAL_IMPACT       = "possible_material_impact",       "Possible material impact"
        INSUFFICIENT_EVIDENCE          = "insufficient_evidence",          "Insufficient evidence"
        NOT_ASSESSED                   = "not_assessed",                   "Not assessed"

    class OpinionDirection(models.TextChoices):
        NO_DIRECTION = "no_direction", "No direction"
        LIKELY_UNMODIFIED = (
            "likely_unmodified_subject_to_auditor_review",
            "Likely unmodified — subject to auditor review")
        POSSIBLE_MODIFIED = (
            "possible_modified_opinion_subject_to_auditor_review",
            "Possible modified opinion — subject to auditor review")
        INSUFFICIENT_BASIS = (
            "insufficient_basis_subject_to_auditor_review",
            "Insufficient basis — subject to auditor review")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    engagement = models.ForeignKey(
        AuditEngagement, on_delete=models.CASCADE, related_name="readiness_workpapers")
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="readiness_workpapers")
    sad_summary = models.ForeignKey(
        AuditDifferenceSummary, on_delete=models.CASCADE,
        related_name="readiness_workpapers")

    status = models.CharField(
        max_length=24, choices=Status.choices, default=Status.DRAFT, db_index=True)
    readiness_conclusion = models.CharField(
        max_length=48, choices=ReadinessConclusion.choices,
        default=ReadinessConclusion.NOT_ASSESSED, db_index=True)
    suggested_opinion_direction = models.CharField(
        max_length=64, choices=OpinionDirection.choices,
        default=OpinionDirection.NO_DIRECTION)

    total_accepted_differences = models.PositiveIntegerField(default=0)
    total_unadjusted_differences = models.PositiveIntegerField(default=0)
    total_adjusted_differences = models.PositiveIntegerField(default=0)
    total_pending_management_response = models.PositiveIntegerField(default=0)
    total_needs_evidence = models.PositiveIntegerField(default=0)
    total_absolute_impact = models.DecimalField(**_AMOUNT)
    overall_materiality     = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    performance_materiality = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)

    conclusion_basis = models.JSONField(default=dict, blank=True)
    unadjusted_summary = models.JSONField(default=dict, blank=True)
    management_response_summary = models.JSONField(default=dict, blank=True)
    proposed_adjustment_summary = models.JSONField(default=dict, blank=True)
    legal_disclaimer = models.TextField(default=LEGAL_DISCLAIMER)

    generated_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="generated_readiness_workpapers")
    generated_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="reviewed_readiness_workpapers")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewer_note = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "audit_readiness_workpapers"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["engagement", "-created_at"]),
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["readiness_conclusion"]),
        ]

    def __str__(self) -> str:
        return f"Readiness {self.id} (eng={self.engagement_id}, {self.readiness_conclusion})"

    def clean(self):
        if self.engagement_id and self.organization_id:
            if self.engagement.organization_id != self.organization_id:
                raise ValidationError(
                    "AuditReadinessWorkpaper.organization must match engagement.organization."
                )
        if self.sad_summary_id and self.engagement_id:
            if self.sad_summary.engagement_id != self.engagement_id:
                raise ValidationError(
                    "sad_summary must belong to the same engagement."
                )
