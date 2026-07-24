"""Journal Analytics foundation (TADGEEG-FIN-AUDIT-7A).

An ADVISORY, journal-level analytics layer over the staged General Ledger
(``GeneralLedgerRow``). It is deliberately separate from the 2B candidate
findings pipeline:

  * 2B (``GeneralLedgerRiskFinding``) analyses **rows** and feeds the auditor
    review workflow (3B → 4A SAD → 5A readiness).
  * 7A analyses **journals** and produces advisory analytics only. It NEVER
    creates or modifies a ``GeneralLedgerRiskFinding``, never accepts a finding,
    never issues an opinion, and never writes to ``apps.ledger``.

Deterministic rules only — no AI, no machine learning, no sampling.
"""
from __future__ import annotations

import uuid

from django.core.exceptions import ValidationError
from django.db import models

from apps.audit.engagement_models import AuditEngagement
from apps.audit.general_ledger_models import GeneralLedgerImport
from apps.authentication.models import Organization, User


class JournalAnalyticsRule(models.Model):
    """Registry row for one deterministic analytics rule (enable/disable).

    The rule *logic* lives in ``services.journal_analytics``; this model only
    stores per-organization configuration so rules can be switched off without
    a code change.
    """

    class Category(models.TextChoices):
        TIMING      = "timing",      "Timing"
        AMOUNT      = "amount",      "Amount"
        DOCUMENTATION = "documentation", "Documentation"
        ACCOUNT     = "account",     "Account"
        SOURCE      = "source",      "Source"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="journal_analytics_rules")

    rule_code = models.CharField(max_length=48, db_index=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    recommendation = models.TextField(blank=True)
    category = models.CharField(
        max_length=16, choices=Category.choices, default=Category.AMOUNT)
    is_enabled = models.BooleanField(default=True, db_index=True)
    # Multiplies the rule's base score (deterministic weighting, not learning).
    weight = models.PositiveSmallIntegerField(default=100)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "audit_journal_analytics_rules"
        ordering = ("rule_code",)
        constraints = [
            models.UniqueConstraint(fields=["organization", "rule_code"],
                                    name="uniq_journal_analytics_rule_per_org"),
        ]
        indexes = [models.Index(fields=["organization", "is_enabled"])]

    def __str__(self) -> str:
        return f"{self.rule_code} ({'on' if self.is_enabled else 'off'})"


class JournalAnalyticsRun(models.Model):
    """One execution of the analytics engine over a GL import."""

    class Status(models.TextChoices):
        PENDING   = "pending",   "Pending"
        RUNNING   = "running",   "Running"
        COMPLETED = "completed", "Completed"
        FAILED    = "failed",    "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="journal_analytics_runs")
    engagement = models.ForeignKey(
        AuditEngagement, on_delete=models.CASCADE, related_name="journal_analytics_runs")
    general_ledger_import = models.ForeignKey(
        GeneralLedgerImport, on_delete=models.CASCADE,
        related_name="journal_analytics_runs")

    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    execution_ms = models.PositiveIntegerField(default=0)

    rules_executed = models.JSONField(default=list, blank=True)
    rows_analyzed = models.PositiveIntegerField(default=0)
    journals_analyzed = models.PositiveIntegerField(default=0)
    findings_count = models.PositiveIntegerField(default=0)

    warnings = models.JSONField(default=list, blank=True)
    errors = models.JSONField(default=list, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="journal_analytics_runs")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "audit_journal_analytics_runs"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["organization", "-created_at"]),
            models.Index(fields=["engagement", "-created_at"]),
            models.Index(fields=["general_ledger_import", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"AnalyticsRun {self.id} ({self.status})"

    def clean(self):
        if self.engagement_id and self.organization_id:
            if self.engagement.organization_id != self.organization_id:
                raise ValidationError(
                    "organization must match engagement.organization.")
        if self.general_ledger_import_id and self.engagement_id:
            imp = self.general_ledger_import
            if imp.engagement_id != self.engagement_id:
                raise ValidationError(
                    "general_ledger_import must belong to the same engagement.")


class JournalAnalyticsResult(models.Model):
    """One rule hit against one journal. Advisory only — never a finding."""

    class Severity(models.TextChoices):
        LOW      = "low",      "Low"
        MEDIUM   = "medium",   "Medium"
        HIGH     = "high",     "High"
        CRITICAL = "critical", "Critical"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(
        JournalAnalyticsRun, on_delete=models.CASCADE, related_name="results")
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="journal_analytics_results")

    rule_code = models.CharField(max_length=48, db_index=True)
    rule_name = models.CharField(max_length=255, blank=True)
    severity = models.CharField(
        max_length=10, choices=Severity.choices, default=Severity.LOW, db_index=True)
    score = models.PositiveSmallIntegerField(default=0)

    journal_number = models.CharField(max_length=64, blank=True, db_index=True)
    account_code = models.CharField(max_length=64, blank=True, db_index=True)
    account_name = models.CharField(max_length=255, blank=True)
    entered_by = models.CharField(max_length=128, blank=True, db_index=True)

    description = models.TextField(blank=True)
    recommendation = models.TextField(blank=True)
    amount = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    affected_rows = models.PositiveIntegerField(default=0)
    execution_ms = models.PositiveIntegerField(default=0)
    evidence = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "audit_journal_analytics_results"
        ordering = ("-score", "rule_code", "journal_number")
        indexes = [
            models.Index(fields=["run", "-score"]),
            models.Index(fields=["organization", "severity"]),
            models.Index(fields=["run", "rule_code"]),
        ]

    def __str__(self) -> str:
        return f"{self.rule_code} @ {self.journal_number} ({self.severity})"


class JournalAnalyticsSummary(models.Model):
    """Aggregated, denormalised summary for one run (powers the dashboard)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.OneToOneField(
        JournalAnalyticsRun, on_delete=models.CASCADE, related_name="summary")
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE,
        related_name="journal_analytics_summaries")

    total_journals = models.PositiveIntegerField(default=0)
    analyzed_journals = models.PositiveIntegerField(default=0)
    flagged_journals = models.PositiveIntegerField(default=0)
    high_risk_journals = models.PositiveIntegerField(default=0)
    medium_risk_journals = models.PositiveIntegerField(default=0)
    low_risk_journals = models.PositiveIntegerField(default=0)

    by_rule = models.JSONField(default=dict, blank=True)
    by_severity = models.JSONField(default=dict, blank=True)
    top_accounts = models.JSONField(default=list, blank=True)
    top_users = models.JSONField(default=list, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "audit_journal_analytics_summaries"
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"AnalyticsSummary for run {self.run_id}"
