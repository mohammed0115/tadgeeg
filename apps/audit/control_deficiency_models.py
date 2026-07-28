"""Control Deficiencies & Management Letter (TADGEEG-FIN-AUDIT-9B · ISA 265).

Records deficiencies in internal control identified during the audit, classifies
them (material weakness / significant deficiency / other), captures management's
response, and drives a generated Management Letter grouped by significance.

Safety boundaries: organization-scoped and validated against its engagement;
never writes to ``apps.ledger``; no AI; no audit opinion — the letter
communicates deficiencies to those charged with governance (ISA 265), it does
not modify the opinion.
"""
from __future__ import annotations

import uuid

from django.core.exceptions import ValidationError
from django.db import models

from apps.audit.engagement_models import AuditEngagement
from apps.audit.general_ledger_models import GeneralLedgerRiskFinding
from apps.authentication.models import Organization, User


class AuditControlDeficiency(models.Model):
    """One internal-control deficiency (ISA 265 §6)."""

    class Classification(models.TextChoices):
        MATERIAL_WEAKNESS      = "material_weakness",      "Material weakness"
        SIGNIFICANT_DEFICIENCY = "significant_deficiency", "Significant deficiency"
        OTHER_DEFICIENCY       = "other_deficiency",       "Other deficiency"

    class Area(models.TextChoices):
        FINANCIAL_REPORTING = "financial_reporting", "Financial reporting"
        REVENUE             = "revenue",             "Revenue"
        PROCUREMENT_PAYABLES = "procurement_payables", "Procurement & payables"
        PAYROLL             = "payroll",             "Payroll"
        CASH_TREASURY       = "cash_treasury",       "Cash & treasury"
        INVENTORY           = "inventory",           "Inventory"
        FIXED_ASSETS        = "fixed_assets",        "Fixed assets"
        IT_GENERAL_CONTROLS = "it_general_controls", "IT general controls"
        OTHER               = "other",               "Other"

    class Status(models.TextChoices):
        OPEN                 = "open",                 "Open"
        MANAGEMENT_RESPONDED = "management_responded", "Management responded"
        REMEDIATED           = "remediated",           "Remediated"
        ACCEPTED_RISK        = "accepted_risk",        "Risk accepted"

    # Ranking for sorting the letter (most severe first).
    _SEVERITY_RANK = {
        Classification.MATERIAL_WEAKNESS: 0,
        Classification.SIGNIFICANT_DEFICIENCY: 1,
        Classification.OTHER_DEFICIENCY: 2,
    }

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="control_deficiencies")
    engagement = models.ForeignKey(
        AuditEngagement, on_delete=models.CASCADE, related_name="control_deficiencies")

    reference = models.CharField(max_length=32, blank=True, db_index=True)
    title = models.CharField(max_length=255)
    area = models.CharField(max_length=24, choices=Area.choices, default=Area.OTHER)
    classification = models.CharField(
        max_length=24, choices=Classification.choices,
        default=Classification.OTHER_DEFICIENCY, db_index=True)

    description = models.TextField(blank=True)
    potential_effect = models.TextField(blank=True)
    recommendation = models.TextField(blank=True)

    management_response = models.TextField(blank=True)
    management_action_owner = models.CharField(max_length=255, blank=True)
    target_date = models.DateField(null=True, blank=True)

    status = models.CharField(
        max_length=24, choices=Status.choices, default=Status.OPEN, db_index=True)

    # Optional link to the 2B GL finding that surfaced the deficiency (reuse).
    gl_finding = models.ForeignKey(
        GeneralLedgerRiskFinding, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="control_deficiencies")
    # TADGEEG-G2.3 — link the deficiency to the assessed risk it relates to.
    assessed_risk = models.ForeignKey(
        "audit.AssessedRisk", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="control_deficiencies")

    identified_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="identified_deficiencies")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "audit_control_deficiencies"
        ordering = ("classification", "-created_at")
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["engagement", "classification"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "reference"],
                condition=models.Q(reference__gt=""),
                name="uniq_deficiency_reference_per_org"),
        ]

    def __str__(self) -> str:
        return f"Deficiency {self.reference or self.id} ({self.classification})"

    @property
    def severity_rank(self) -> int:
        return self._SEVERITY_RANK.get(self.classification, 9)

    def clean(self):
        if self.engagement_id and self.organization_id:
            if self.engagement.organization_id != self.organization_id:
                raise ValidationError(
                    "organization must match engagement.organization.")
        if self.gl_finding_id and self.engagement_id:
            if self.gl_finding.engagement_id != self.engagement_id:
                raise ValidationError(
                    "gl_finding must belong to the same engagement.")
