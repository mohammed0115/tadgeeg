"""ISA 300 — Audit Engagement model.

Closes the BIG4 audit's finding "no engagement-level state machine".
One ``AuditEngagement`` row holds the lifecycle of a whole audit
(ACCEPTANCE → PLANNING → RISK_ASSESSMENT → FIELDWORK → REVIEW → EQR →
REPORTING → ARCHIVAL) and is the parent of AuditCase, AuditFinding,
WorkingPaper, and any AuditOpinion produced.

ISA cross-references:
  • ISA 210 §A21 — engagement acceptance
  • ISA 220 §17  — engagement quality review (EQR)
  • ISA 230 §A6  — retention period (≥ 5 years)
  • ISA 300 §7   — strategy + plan
  • ISA 315      — risk assessment procedures
  • ISA 330      — responses
  • ISA 700      — opinion
"""
from __future__ import annotations

import uuid

from django.db import models

from apps.authentication.models import Organization, User


class AuditEngagement(models.Model):
    """One end-to-end audit engagement. ISA 300 §7."""

    class Stage(models.TextChoices):
        ACCEPTANCE       = "acceptance",       "Acceptance"
        PLANNING         = "planning",         "Planning"
        RISK_ASSESSMENT  = "risk_assessment",  "Risk Assessment"
        FIELDWORK        = "fieldwork",        "Fieldwork"
        REVIEW           = "review",           "Review"
        EQR              = "eqr",              "Engagement Quality Review"
        REPORTING        = "reporting",        "Reporting"
        ARCHIVED         = "archived",         "Archived"
        WITHDRAWN        = "withdrawn",        "Withdrawn (post-acceptance)"

    class EngagementType(models.TextChoices):
        FINANCIAL_STATEMENT = "fs",      "Financial Statement Audit (ISA)"
        INTERNAL_AUDIT      = "ia",      "Internal Audit (IIA IPPF)"
        REVIEW              = "review",  "Review Engagement (ISRE 2400)"
        AGREED_PROCEDURES   = "aup",     "Agreed-upon Procedures (ISRS 4400)"
        COMPLIANCE          = "comp",    "Compliance / Regulatory"
        FRAUD_INVESTIGATION = "fraud",   "Forensic / Fraud Investigation"

    class OpinionType(models.TextChoices):
        UNMODIFIED  = "unmodified",  "Unmodified"
        QUALIFIED   = "qualified",   "Qualified"
        ADVERSE     = "adverse",     "Adverse"
        DISCLAIMER  = "disclaimer",  "Disclaimer of Opinion"

    # ── Identity ────────────────────────────────────────────────────────
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE,
        related_name="audit_engagements",
    )
    engagement_code = models.CharField(
        max_length=32, db_index=True,
        help_text="External reference, e.g. AUD-2026-001",
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    engagement_type = models.CharField(
        max_length=12, choices=EngagementType.choices,
        default=EngagementType.FINANCIAL_STATEMENT,
    )

    # ── Reporting period ────────────────────────────────────────────────
    period_start = models.DateField()
    period_end   = models.DateField()
    fieldwork_start = models.DateField(null=True, blank=True)
    fieldwork_end   = models.DateField(null=True, blank=True)
    expected_report_date = models.DateField(null=True, blank=True)
    archival_due_date    = models.DateField(
        null=True, blank=True,
        help_text="ISA 230 §A21 — 60 days after report sign-off.",
    )

    # ── Lifecycle ───────────────────────────────────────────────────────
    stage = models.CharField(
        max_length=20, choices=Stage.choices, default=Stage.ACCEPTANCE,
        db_index=True,
    )
    accepted_at  = models.DateTimeField(null=True, blank=True)
    locked_at    = models.DateTimeField(
        null=True, blank=True,
        help_text="Set when ARCHIVED. After this point the engagement is immutable.",
    )

    # ── Team ────────────────────────────────────────────────────────────
    engagement_partner = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="led_engagements",
    )
    engagement_manager = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="managed_engagements",
    )
    eqr_partner = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="eqr_engagements",
        help_text="ISA 220 / ISQM 1 — required for listed entity audits.",
    )

    # ── Planning artefacts (ISA 300) ────────────────────────────────────
    strategy        = models.JSONField(default=dict, blank=True)
    plan_procedures = models.JSONField(default=list, blank=True)
    materiality     = models.JSONField(default=dict, blank=True)
    risk_assessment = models.JSONField(default=dict, blank=True)

    # ── Reporting ──────────────────────────────────────────────────────
    opinion_type = models.CharField(
        max_length=12, choices=OpinionType.choices, blank=True, default="",
    )
    opinion_signed_at = models.DateTimeField(null=True, blank=True)
    opinion_signed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="signed_engagements",
    )
    kams_summary = models.JSONField(default=list, blank=True,
                                    help_text="ISA 701 Key Audit Matters.")

    # ── Audit trail ────────────────────────────────────────────────────
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="created_engagements",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "audit_engagements"
        ordering = ["-period_end", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "engagement_code"),
                name="audit_engagement_code_unique_per_org",
            ),
        ]
        indexes = [
            models.Index(fields=("organization", "stage")),
            models.Index(fields=("engagement_type",)),
            models.Index(fields=("period_end",)),
        ]

    def __str__(self) -> str:
        return f"{self.engagement_code} — {self.title}"
