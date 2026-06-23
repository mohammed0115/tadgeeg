"""General Ledger import **staging** models (TADGEEG-FIN-AUDIT-2A).

Client-uploaded general ledgers are *audit evidence*, not the platform's own
books. They land in dedicated staging tables linked to the canonical
``AuditEngagement`` (and optionally to a ``TrialBalanceImport``), and are
**never** written into ``apps.ledger`` (internal, hash-chained, period-locked
accounting truth). Mirrors the Trial Balance staging pattern from 1A/1B.

Scope: GL intake only. Bank reconciliation, VAT, materiality, sampling, SAD,
workpapers and report packs are out of scope (see the 2A doc).
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models

from apps.audit.engagement_models import AuditEngagement
from apps.audit.trial_balance_models import AccountMapping, TrialBalanceImport
from apps.authentication.models import Organization, User

_ZERO = Decimal("0")
_AMOUNT = dict(max_digits=20, decimal_places=4, default=_ZERO)


class GeneralLedgerImport(models.Model):
    """One uploaded general-ledger file for one engagement (a staging batch)."""

    class SourceFormat(models.TextChoices):
        CSV  = "csv",  "CSV"
        XLSX = "xlsx", "Excel (.xlsx)"
        XLS  = "xls",  "Excel (.xls)"

    class Status(models.TextChoices):
        UPLOADED          = "uploaded",          "Uploaded"
        VALIDATING        = "validating",        "Validating"
        VALIDATION_FAILED = "validation_failed", "Validation failed"
        VALIDATED         = "validated",         "Validated"
        IMPORTED          = "imported",          "Imported"
        ARCHIVED          = "archived",          "Archived"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    engagement = models.ForeignKey(
        AuditEngagement, on_delete=models.CASCADE,
        related_name="general_ledger_imports",
    )
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE,
        related_name="general_ledger_imports",
    )
    # Optional link to the TB import for the same engagement (alignment checks).
    related_trial_balance_import = models.ForeignKey(
        TrialBalanceImport, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="general_ledger_imports",
    )

    uploaded_file = models.FileField(
        upload_to="audit/general_ledger/%Y/%m/", null=True, blank=True,
    )
    file_sha256 = models.CharField(max_length=64, blank=True, db_index=True)
    original_filename = models.CharField(max_length=255, blank=True)
    source_format = models.CharField(max_length=8, choices=SourceFormat.choices)

    period_start = models.DateField(null=True, blank=True, db_index=True)
    period_end   = models.DateField(null=True, blank=True, db_index=True)
    fiscal_year  = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    currency     = models.CharField(max_length=8, blank=True)

    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.UPLOADED, db_index=True,
    )

    # ── Results / summary ───────────────────────────────────────────────
    row_count               = models.PositiveIntegerField(default=0)
    valid_row_count         = models.PositiveIntegerField(default=0)
    invalid_row_count       = models.PositiveIntegerField(default=0)
    journal_count           = models.PositiveIntegerField(default=0)
    balanced_journal_count  = models.PositiveIntegerField(default=0)
    unbalanced_journal_count = models.PositiveIntegerField(default=0)
    total_debit  = models.DecimalField(**_AMOUNT)
    total_credit = models.DecimalField(**_AMOUNT)
    difference   = models.DecimalField(**_AMOUNT)
    is_balanced  = models.BooleanField(default=False)

    column_mapping     = models.JSONField(default=dict, blank=True)
    validation_summary = models.JSONField(default=dict, blank=True)
    errors   = models.JSONField(default=list, blank=True)
    warnings = models.JSONField(default=list, blank=True)

    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="general_ledger_imports",
    )
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)
    validated_at = models.DateTimeField(null=True, blank=True)
    archived_at  = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "audit_general_ledger_imports"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["engagement", "-created_at"]),
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["fiscal_year"]),
            models.Index(fields=["period_start"]),
            models.Index(fields=["period_end"]),
        ]

    def __str__(self) -> str:
        return f"GL import {self.id} (eng={self.engagement_id}, {self.status})"

    def clean(self):
        if self.engagement_id and self.organization_id:
            if self.engagement.organization_id != self.organization_id:
                raise ValidationError(
                    "GeneralLedgerImport.organization must match "
                    "engagement.organization (cross-tenant import denied)."
                )
        # A linked TB import must belong to the same engagement + organization.
        if self.related_trial_balance_import_id:
            tb = self.related_trial_balance_import
            if (tb.engagement_id != self.engagement_id
                    or tb.organization_id != self.organization_id):
                raise ValidationError(
                    "related_trial_balance_import must belong to the same "
                    "engagement and organization."
                )


class GeneralLedgerRow(models.Model):
    """One staged GL line. Never posted to the ledger."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    import_batch = models.ForeignKey(
        GeneralLedgerImport, on_delete=models.CASCADE, related_name="rows",
    )
    engagement = models.ForeignKey(
        AuditEngagement, on_delete=models.CASCADE, related_name="general_ledger_rows",
    )
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="general_ledger_rows",
    )

    row_number      = models.PositiveIntegerField()
    journal_number  = models.CharField(max_length=64, blank=True, db_index=True)
    line_number     = models.CharField(max_length=32, blank=True)
    transaction_date = models.DateField(null=True, blank=True, db_index=True)
    posting_date     = models.DateField(null=True, blank=True, db_index=True)

    account_code = models.CharField(max_length=64, blank=True, db_index=True)
    account_name = models.CharField(max_length=255, blank=True)
    # Classification only — links to the engagement's AccountMapping if present.
    mapped_account = models.ForeignKey(
        AccountMapping, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="general_ledger_rows",
    )

    debit         = models.DecimalField(**_AMOUNT)
    credit        = models.DecimalField(**_AMOUNT)
    signed_amount = models.DecimalField(**_AMOUNT)
    currency      = models.CharField(max_length=8, blank=True)

    description     = models.TextField(blank=True)
    document_number = models.CharField(max_length=128, blank=True)
    reference       = models.CharField(max_length=128, blank=True)
    counterparty    = models.CharField(max_length=255, blank=True)
    cost_center     = models.CharField(max_length=64, blank=True)
    department      = models.CharField(max_length=64, blank=True)
    entered_by      = models.CharField(max_length=128, blank=True)
    source_system   = models.CharField(max_length=64, blank=True)

    is_valid = models.BooleanField(default=True, db_index=True)
    validation_errors = models.JSONField(default=list, blank=True)
    raw_data = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "audit_general_ledger_rows"
        ordering = ("import_batch", "row_number")
        constraints = [
            models.UniqueConstraint(
                fields=["import_batch", "row_number"],
                name="uniq_gl_row_per_import",
            ),
        ]
        indexes = [
            models.Index(fields=["import_batch", "row_number"]),
            models.Index(fields=["engagement", "account_code"]),
            models.Index(fields=["organization", "is_valid"]),
            models.Index(fields=["journal_number"]),
            models.Index(fields=["account_code"]),
            models.Index(fields=["transaction_date"]),
            models.Index(fields=["posting_date"]),
            models.Index(fields=["mapped_account"]),
        ]

    def __str__(self) -> str:
        return f"GL row {self.row_number}: {self.account_code} ({self.import_batch_id})"


class GeneralLedgerRiskFinding(models.Model):
    """A **candidate** risk finding produced by deterministic GL analysis.

    These are *not* audit conclusions: they are machine-suggested items for an
    auditor to review (accept / dismiss / request evidence / escalate). They are
    derived only from staged ``GeneralLedgerRow`` data, never posted to the
    ledger, and never use materiality or AI in this phase (raw amount thresholds
    only — temporary until materiality integration).
    """

    class Category(models.TextChoices):
        MANUAL_ENTRY             = "manual_entry",             "Manual entry"
        PERIOD_END               = "period_end",              "Period-end posting"
        UNUSUAL_TIMING           = "unusual_timing",          "Unusual timing (weekend)"
        ROUND_AMOUNT             = "round_amount",            "Round amount"
        THRESHOLD_AVOIDANCE      = "threshold_avoidance",     "Threshold avoidance"
        SENSITIVE_ACCOUNT        = "sensitive_account",       "Sensitive account"
        RARE_ACCOUNT_COMBINATION = "rare_account_combination","Rare account combination"
        MISSING_DESCRIPTION      = "missing_description",     "Missing description"
        UNBALANCED_JOURNAL       = "unbalanced_journal",      "Unbalanced journal"
        DUPLICATE_ENTRY          = "duplicate_entry",         "Duplicate entry"
        UNMAPPED_ACCOUNT         = "unmapped_account",        "Unmapped account"
        OTHER                    = "other",                   "Other"

    class Severity(models.TextChoices):
        LOW      = "low",      "Low"
        MEDIUM   = "medium",   "Medium"
        HIGH     = "high",     "High"
        CRITICAL = "critical", "Critical"

    class Status(models.TextChoices):
        CANDIDATE     = "candidate",     "Candidate"
        ACCEPTED      = "accepted",      "Accepted"
        DISMISSED     = "dismissed",     "Dismissed"
        NEEDS_EVIDENCE = "needs_evidence","Needs evidence"
        ESCALATED     = "escalated",     "Escalated"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    engagement = models.ForeignKey(
        AuditEngagement, on_delete=models.CASCADE, related_name="gl_risk_findings")
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="gl_risk_findings")
    general_ledger_import = models.ForeignKey(
        GeneralLedgerImport, on_delete=models.CASCADE, related_name="risk_findings")
    row = models.ForeignKey(
        GeneralLedgerRow, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="risk_findings")

    journal_number = models.CharField(max_length=64, blank=True, db_index=True)
    risk_code   = models.CharField(max_length=64, db_index=True)
    risk_title  = models.CharField(max_length=255)
    risk_description = models.TextField(blank=True)
    risk_category = models.CharField(max_length=32, choices=Category.choices, db_index=True)
    severity = models.CharField(max_length=12, choices=Severity.choices, db_index=True)
    score = models.PositiveSmallIntegerField(default=0)  # 0–100
    amount_impact = models.DecimalField(max_digits=20, decimal_places=4, default=Decimal("0"))

    account_code = models.CharField(max_length=64, blank=True, db_index=True)
    account_name = models.CharField(max_length=255, blank=True)
    mapped_category = models.CharField(max_length=32, blank=True)
    evidence_snapshot = models.JSONField(default=dict, blank=True)

    # Deterministic fingerprint — supports idempotent re-runs (not unique so one
    # row may raise several rules, but stable across re-analysis).
    fingerprint = models.CharField(max_length=64, blank=True, db_index=True)

    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.CANDIDATE, db_index=True)
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="reviewed_gl_risk_findings")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewer_note = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "audit_gl_risk_findings"
        ordering = ("-score", "-created_at")
        indexes = [
            models.Index(fields=["engagement", "status"]),
            models.Index(fields=["organization", "severity"]),
            models.Index(fields=["general_ledger_import", "risk_code"]),
            models.Index(fields=["account_code"]),
            models.Index(fields=["fingerprint"]),
        ]

    def __str__(self) -> str:
        return f"{self.risk_code} [{self.severity}] {self.account_code} ({self.general_ledger_import_id})"

    def clean(self):
        if self.engagement_id and self.organization_id:
            if self.engagement.organization_id != self.organization_id:
                raise ValidationError(
                    "GeneralLedgerRiskFinding.organization must match engagement.organization."
                )
        if self.general_ledger_import_id and self.engagement_id:
            if self.general_ledger_import.engagement_id != self.engagement_id:
                raise ValidationError(
                    "general_ledger_import must belong to the same engagement."
                )
