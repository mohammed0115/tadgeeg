"""Summary of Audit Differences (SAD) backbone (TADGEEG-FIN-AUDIT-4A).

Aggregates **human-accepted** GL risk findings into an engagement-level working
layer and compares the accumulated impact against engagement materiality
(ISA 450). This is an auditor **working schedule**, not an audit opinion: it
records *accepted audit differences requiring auditor evaluation* — it never
states the financial statements are misstated, never posts adjustments, and
never writes to ``apps.ledger``.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models

from apps.audit.engagement_models import AuditEngagement
from apps.audit.general_ledger_models import GeneralLedgerRiskFinding
from apps.authentication.models import Organization, User

_AMOUNT = dict(max_digits=20, decimal_places=4, default=Decimal("0"))


class AuditDifferenceSummary(models.Model):
    """Engagement-level accumulation of accepted audit differences."""

    class SourceScope(models.TextChoices):
        GENERAL_LEDGER = "general_ledger", "General ledger"
        MIXED          = "mixed",          "Mixed"

    class Status(models.TextChoices):
        DRAFT        = "draft",        "Draft"
        RECALCULATED = "recalculated", "Recalculated"
        REVIEWED     = "reviewed",     "Reviewed"
        LOCKED       = "locked",       "Locked"

    class Conclusion(models.TextChoices):
        NO_ACCEPTED_DIFFERENCES   = "no_accepted_differences",       "No accepted differences"
        BELOW_TRIVIAL             = "below_trivial",                 "Below trivial threshold"
        BELOW_PERFORMANCE         = "below_performance_materiality", "Below performance materiality"
        ABOVE_PERFORMANCE         = "above_performance_materiality", "Above performance materiality"
        ABOVE_OVERALL             = "above_overall_materiality",     "Above overall materiality"
        NOT_ASSESSED              = "not_assessed",                  "Not assessed (no materiality)"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    engagement = models.ForeignKey(
        AuditEngagement, on_delete=models.CASCADE, related_name="difference_summaries")
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="difference_summaries")

    source_scope = models.CharField(
        max_length=20, choices=SourceScope.choices, default=SourceScope.GENERAL_LEDGER)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.DRAFT, db_index=True)

    total_accepted_findings = models.PositiveIntegerField(default=0)
    total_gross_misstatement = models.DecimalField(**_AMOUNT)
    total_debit_impact   = models.DecimalField(**_AMOUNT)
    total_credit_impact  = models.DecimalField(**_AMOUNT)
    total_absolute_impact = models.DecimalField(**_AMOUNT)

    overall_materiality     = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    performance_materiality = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    trivial_threshold       = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    materiality_basis = models.CharField(max_length=64, blank=True)

    exceeds_performance_materiality = models.BooleanField(default=False)
    exceeds_overall_materiality     = models.BooleanField(default=False)
    conclusion_status = models.CharField(
        max_length=32, choices=Conclusion.choices,
        default=Conclusion.NO_ACCEPTED_DIFFERENCES, db_index=True)

    summary_by_category  = models.JSONField(default=dict, blank=True)
    summary_by_account   = models.JSONField(default=dict, blank=True)
    calculation_snapshot = models.JSONField(default=dict, blank=True)

    calculated_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="calculated_difference_summaries")
    calculated_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="reviewed_difference_summaries")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewer_note = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "audit_difference_summaries"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["engagement", "-created_at"]),
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["conclusion_status"]),
            models.Index(fields=["calculated_at"]),
        ]

    def __str__(self) -> str:
        return f"SAD {self.id} (eng={self.engagement_id}, {self.conclusion_status})"

    def clean(self):
        if self.engagement_id and self.organization_id:
            if self.engagement.organization_id != self.organization_id:
                raise ValidationError(
                    "AuditDifferenceSummary.organization must match engagement.organization."
                )


class AuditDifferenceItem(models.Model):
    """One accepted audit difference line, linked to a GL risk finding."""

    class SourceType(models.TextChoices):
        GL_RISK_FINDING = "gl_risk_finding", "GL risk finding"

    class ManagementResponse(models.TextChoices):
        NOT_REQUESTED = "not_requested", "Not requested"
        PENDING       = "pending",       "Pending"
        AGREED        = "agreed",        "Agreed"
        DISAGREED     = "disagreed",     "Disagreed"
        ADJUSTED      = "adjusted",      "Adjusted"
        UNADJUSTED    = "unadjusted",    "Unadjusted"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    summary = models.ForeignKey(
        AuditDifferenceSummary, on_delete=models.CASCADE, related_name="items")
    engagement = models.ForeignKey(
        AuditEngagement, on_delete=models.CASCADE, related_name="difference_items")
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="difference_items")

    source_type = models.CharField(
        max_length=20, choices=SourceType.choices, default=SourceType.GL_RISK_FINDING)
    gl_finding = models.ForeignKey(
        GeneralLedgerRiskFinding, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="difference_items")

    account_code = models.CharField(max_length=64, blank=True, db_index=True)
    account_name = models.CharField(max_length=255, blank=True)
    mapped_category = models.CharField(max_length=32, blank=True, db_index=True)
    finding_risk_code = models.CharField(max_length=64, blank=True)
    finding_title = models.CharField(max_length=255, blank=True)

    amount_impact = models.DecimalField(**_AMOUNT)
    debit_impact  = models.DecimalField(**_AMOUNT)
    credit_impact = models.DecimalField(**_AMOUNT)

    materiality_status = models.CharField(max_length=32, blank=True, db_index=True)
    materiality_adjusted_severity = models.CharField(max_length=12, blank=True)
    is_above_trivial = models.BooleanField(default=False)
    is_above_performance_materiality = models.BooleanField(default=False)
    is_above_overall_materiality = models.BooleanField(default=False)

    management_response_status = models.CharField(
        max_length=16, choices=ManagementResponse.choices,
        default=ManagementResponse.NOT_REQUESTED)
    auditor_conclusion = models.TextField(blank=True)
    evidence_snapshot = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "audit_difference_items"
        ordering = ("summary", "-amount_impact")
        indexes = [
            models.Index(fields=["summary"]),
            models.Index(fields=["engagement", "account_code"]),
            models.Index(fields=["organization", "materiality_status"]),
            models.Index(fields=["gl_finding"]),
            models.Index(fields=["mapped_category"]),
        ]

    def __str__(self) -> str:
        return f"SAD item {self.account_code} {self.amount_impact} (summary={self.summary_id})"


class AuditDifferenceItemResponse(models.Model):
    """Append-only trail of management-response transitions on a SAD item.

    One row per status change (who/what/when/why). Never posts to the ledger.
    """

    class Reason(models.TextChoices):
        MANAGEMENT_AGREED                = "management_agreed",                "Management agreed"
        MANAGEMENT_DISAGREED             = "management_disagreed",             "Management disagreed"
        ADJUSTMENT_TO_BE_POSTED_BY_CLIENT = "adjustment_to_be_posted_by_client","Adjustment to be posted by client"
        CLIENT_REFUSED_ADJUSTMENT        = "client_refused_adjustment",        "Client refused adjustment"
        IMMATERIAL_UNADJUSTED            = "immaterial_unadjusted",            "Immaterial — left unadjusted"
        PENDING_MANAGEMENT_REPLY         = "pending_management_reply",         "Pending management reply"
        OTHER                            = "other",                           "Other"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    item = models.ForeignKey(
        AuditDifferenceItem, on_delete=models.CASCADE, related_name="responses")
    summary = models.ForeignKey(
        AuditDifferenceSummary, on_delete=models.CASCADE, related_name="item_responses")
    engagement = models.ForeignKey(
        AuditEngagement, on_delete=models.CASCADE, related_name="difference_item_responses")
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="difference_item_responses")

    from_status = models.CharField(max_length=16)
    to_status   = models.CharField(max_length=16)
    actor = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="difference_item_responses")
    response_note = models.TextField(blank=True)
    response_reason = models.CharField(
        max_length=40, choices=Reason.choices, default=Reason.OTHER)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "audit_difference_item_responses"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["item", "-created_at"]),
            models.Index(fields=["engagement", "to_status"]),
            models.Index(fields=["organization", "-created_at"]),
            models.Index(fields=["actor"]),
        ]

    def __str__(self) -> str:
        return f"{self.item_id}: {self.from_status} → {self.to_status}"

    def clean(self):
        if self.engagement_id and self.organization_id:
            if self.engagement.organization_id != self.organization_id:
                raise ValidationError(
                    "AuditDifferenceItemResponse.organization must match engagement.organization."
                )


class ProposedAuditAdjustment(models.Model):
    """A proposed audit adjustment for a SAD item — DOCUMENTATION ONLY.

    This never creates or modifies ``ledger.JournalEntry``; it records what the
    auditor proposes and how management/client responded. Posting (if any) is
    done by the client in their own system and only *referenced* here.
    """

    class Type(models.TextChoices):
        RECLASSIFICATION = "reclassification", "Reclassification"
        ACCRUAL          = "accrual",          "Accrual"
        CORRECTION       = "correction",       "Correction"
        REVERSAL         = "reversal",         "Reversal"
        DISCLOSURE_ONLY  = "disclosure_only",  "Disclosure only"
        OTHER            = "other",            "Other"

    class Status(models.TextChoices):
        DRAFT                 = "draft",                 "Draft"
        PROPOSED              = "proposed",              "Proposed"
        ACCEPTED_BY_MANAGEMENT = "accepted_by_management","Accepted by management"
        REJECTED_BY_MANAGEMENT = "rejected_by_management","Rejected by management"
        POSTED_BY_CLIENT      = "posted_by_client",      "Posted by client"
        NOT_POSTED            = "not_posted",            "Not posted"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    item = models.ForeignKey(
        AuditDifferenceItem, on_delete=models.CASCADE, related_name="proposed_adjustments")
    summary = models.ForeignKey(
        AuditDifferenceSummary, on_delete=models.CASCADE, related_name="proposed_adjustments")
    engagement = models.ForeignKey(
        AuditEngagement, on_delete=models.CASCADE, related_name="proposed_adjustments")
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="proposed_adjustments")

    adjustment_type = models.CharField(max_length=20, choices=Type.choices)
    description = models.TextField(blank=True)
    debit_account_code  = models.CharField(max_length=64, blank=True)
    debit_account_name  = models.CharField(max_length=255, blank=True)
    credit_account_code = models.CharField(max_length=64, blank=True)
    credit_account_name = models.CharField(max_length=255, blank=True)
    amount = models.DecimalField(**_AMOUNT)
    currency = models.CharField(max_length=8, blank=True)

    management_accepted = models.BooleanField(null=True, blank=True)
    client_posted_reference = models.CharField(max_length=128, blank=True)
    status = models.CharField(
        max_length=24, choices=Status.choices, default=Status.DRAFT, db_index=True)

    proposed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="proposed_audit_adjustments")
    proposed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "audit_proposed_adjustments"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["item", "-created_at"]),
            models.Index(fields=["engagement", "status"]),
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["summary"]),
        ]

    def __str__(self) -> str:
        return f"Proposed adj {self.amount} ({self.adjustment_type}) item={self.item_id}"

    def clean(self):
        if self.engagement_id and self.organization_id:
            if self.engagement.organization_id != self.organization_id:
                raise ValidationError(
                    "ProposedAuditAdjustment.organization must match engagement.organization."
                )
