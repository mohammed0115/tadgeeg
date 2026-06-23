"""Trial Balance import **staging** models (TADGEEG-FIN-AUDIT-1A).

Client-uploaded trial balances are *audit evidence*, not the platform's own
books. They therefore land in dedicated staging tables linked to the canonical
``apps.audit.engagement_models.AuditEngagement`` — and are **never** written
into ``apps.ledger`` (which is internal, hash-chained, period-locked accounting
truth). Staging rows are import-versioned: corrections create a new import and
the old one is archived, mirroring how a real audit retains what the client
reported at each point in time.

Scope of this phase: Trial Balance only. General Ledger import, bank
reconciliation, materiality wiring, sampling, assertions, SAD, workpapers and
report packs are explicitly out of scope (see the 1A doc).
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models

from apps.audit.engagement_models import AuditEngagement
from apps.authentication.models import Organization, User

_ZERO = Decimal("0")
# Amounts mirror the ledger's high precision to avoid rounding artefacts while
# staging; these rows are never posted, so precision here is purely for fidelity.
_AMOUNT = dict(max_digits=20, decimal_places=4, default=_ZERO)


class TrialBalanceImport(models.Model):
    """One uploaded trial-balance file for one engagement (a staging batch)."""

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

    # ── Linkage (canonical engagement spine) ────────────────────────────
    engagement = models.ForeignKey(
        AuditEngagement, on_delete=models.CASCADE,
        related_name="trial_balance_imports",
    )
    # Denormalised for fast tenant scoping; MUST equal engagement.organization
    # (enforced in clean() and in the import service).
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE,
        related_name="trial_balance_imports",
    )

    # ── Source file ─────────────────────────────────────────────────────
    uploaded_file = models.FileField(
        upload_to="audit/trial_balance/%Y/%m/", null=True, blank=True,
    )
    file_sha256 = models.CharField(max_length=64, blank=True, db_index=True)
    original_filename = models.CharField(max_length=255, blank=True)
    source_format = models.CharField(max_length=8, choices=SourceFormat.choices)

    # ── Reporting period ────────────────────────────────────────────────
    period_start = models.DateField(null=True, blank=True)
    period_end   = models.DateField(null=True, blank=True)
    fiscal_year  = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    currency     = models.CharField(max_length=8, blank=True)

    # ── Lifecycle ───────────────────────────────────────────────────────
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.UPLOADED,
        db_index=True,
    )

    # ── Validation results / summary ────────────────────────────────────
    row_count         = models.PositiveIntegerField(default=0)
    valid_row_count   = models.PositiveIntegerField(default=0)
    invalid_row_count = models.PositiveIntegerField(default=0)
    total_debit  = models.DecimalField(**_AMOUNT)
    total_credit = models.DecimalField(**_AMOUNT)
    difference   = models.DecimalField(**_AMOUNT)
    is_balanced  = models.BooleanField(default=False)

    column_mapping     = models.JSONField(default=dict, blank=True)
    validation_summary = models.JSONField(default=dict, blank=True)
    errors   = models.JSONField(default=list, blank=True)
    warnings = models.JSONField(default=list, blank=True)

    # ── Audit trail ─────────────────────────────────────────────────────
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="trial_balance_imports",
    )
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)
    validated_at = models.DateTimeField(null=True, blank=True)
    archived_at  = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "audit_trial_balance_imports"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["engagement", "-created_at"]),
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["fiscal_year"]),
        ]

    def __str__(self) -> str:
        return f"TB import {self.id} (eng={self.engagement_id}, {self.status})"

    def clean(self):
        # An import must never cross tenants: its organization must match the
        # engagement's. This is the core safety invariant for this phase.
        if self.engagement_id and self.organization_id:
            if self.engagement.organization_id != self.organization_id:
                raise ValidationError(
                    "TrialBalanceImport.organization must match "
                    "engagement.organization (cross-tenant import denied)."
                )


class TrialBalanceRow(models.Model):
    """One staged trial-balance line. Never posted to the ledger."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    import_batch = models.ForeignKey(
        TrialBalanceImport, on_delete=models.CASCADE, related_name="rows",
    )
    # Denormalised for query/scoping convenience; set from the parent import.
    engagement = models.ForeignKey(
        AuditEngagement, on_delete=models.CASCADE,
        related_name="trial_balance_rows",
    )
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE,
        related_name="trial_balance_rows",
    )

    row_number   = models.PositiveIntegerField()
    account_code = models.CharField(max_length=64, blank=True, db_index=True)
    account_name = models.CharField(max_length=255, blank=True)
    # Free-text client classification; not validated against a chart here.
    account_type = models.CharField(max_length=64, blank=True, db_index=True)

    opening_debit  = models.DecimalField(**_AMOUNT)
    opening_credit = models.DecimalField(**_AMOUNT)
    period_debit   = models.DecimalField(**_AMOUNT)
    period_credit  = models.DecimalField(**_AMOUNT)
    closing_debit  = models.DecimalField(**_AMOUNT)
    closing_credit = models.DecimalField(**_AMOUNT)
    net_movement   = models.DecimalField(**_AMOUNT)
    closing_balance = models.DecimalField(**_AMOUNT)
    currency = models.CharField(max_length=8, blank=True)

    is_valid = models.BooleanField(default=True, db_index=True)
    validation_errors = models.JSONField(default=list, blank=True)
    raw_data = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "audit_trial_balance_rows"
        ordering = ("import_batch", "row_number")
        constraints = [
            models.UniqueConstraint(
                fields=["import_batch", "row_number"],
                name="uniq_tb_row_per_import",
            ),
        ]
        indexes = [
            models.Index(fields=["import_batch", "row_number"]),
            models.Index(fields=["engagement", "account_code"]),
            models.Index(fields=["organization", "is_valid"]),
            models.Index(fields=["account_type"]),
        ]

    def __str__(self) -> str:
        return f"TB row {self.row_number}: {self.account_code} ({self.import_batch_id})"


class AccountMapping(models.Model):
    """Maps a client trial-balance account code → a canonical audit category,
    and (optionally) to an existing ``ledger.Account`` for classification only.

    This is a **bridge / classification layer**. It NEVER posts to the ledger
    and NEVER mutates ledger accounts — ``mapped_ledger_account`` is a read-only
    reference used to align the client's chart with the platform's canonical
    chart for reporting. One mapping per (engagement, account_code).
    """

    class Category(models.TextChoices):
        CASH_AND_BANK        = "cash_and_bank",        "Cash & bank"
        ACCOUNTS_RECEIVABLE  = "accounts_receivable",  "Accounts receivable"
        INVENTORY            = "inventory",            "Inventory"
        FIXED_ASSETS         = "fixed_assets",         "Fixed assets"
        OTHER_ASSETS         = "other_assets",         "Other assets"
        ACCOUNTS_PAYABLE     = "accounts_payable",     "Accounts payable"
        VAT_TAX              = "vat_tax",              "VAT / tax"
        LOANS                = "loans",                "Loans"
        OTHER_LIABILITIES    = "other_liabilities",    "Other liabilities"
        EQUITY               = "equity",               "Equity"
        REVENUE              = "revenue",              "Revenue"
        COST_OF_SALES        = "cost_of_sales",        "Cost of sales"
        PAYROLL_EXPENSE      = "payroll_expense",      "Payroll expense"
        OPERATING_EXPENSE    = "operating_expense",    "Operating expense"
        FINANCE_COST         = "finance_cost",         "Finance cost"
        OTHER_INCOME_EXPENSE = "other_income_expense", "Other income / expense"
        UNKNOWN              = "unknown",              "Unknown"

    class Source(models.TextChoices):
        MANUAL     = "manual",     "Manual"
        RULE_BASED = "rule_based", "Rule-based"
        IMPORTED   = "imported",   "Imported"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    engagement = models.ForeignKey(
        AuditEngagement, on_delete=models.CASCADE,
        related_name="account_mappings",
    )
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE,
        related_name="account_mappings",
    )

    account_code = models.CharField(max_length=64, db_index=True)
    account_name = models.CharField(max_length=255, blank=True)
    mapped_category = models.CharField(
        max_length=32, choices=Category.choices, default=Category.UNKNOWN,
        db_index=True,
    )
    # Optional reference to the platform chart of accounts — classification
    # only. on_delete=SET_NULL so removing a ledger account never cascades into
    # audit evidence.
    mapped_ledger_account = models.ForeignKey(
        "ledger.Account", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="audit_account_mappings",
    )
    mapping_source = models.CharField(
        max_length=12, choices=Source.choices, default=Source.RULE_BASED,
    )
    confidence = models.DecimalField(
        max_digits=4, decimal_places=3, null=True, blank=True,
        help_text="0.000–1.000 for rule-based suggestions; null for manual.",
    )
    notes = models.TextField(blank=True)

    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="created_account_mappings",
    )
    updated_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="updated_account_mappings",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "audit_account_mappings"
        ordering = ("engagement", "account_code")
        constraints = [
            models.UniqueConstraint(
                fields=["engagement", "account_code"],
                name="uniq_account_mapping_per_engagement",
            ),
        ]
        indexes = [
            models.Index(fields=["engagement", "account_code"]),
            models.Index(fields=["organization", "mapped_category"]),
            models.Index(fields=["mapped_category"]),
        ]

    def __str__(self) -> str:
        return f"{self.account_code} → {self.mapped_category} (eng={self.engagement_id})"

    def clean(self):
        if self.engagement_id and self.organization_id:
            if self.engagement.organization_id != self.organization_id:
                raise ValidationError(
                    "AccountMapping.organization must match engagement.organization."
                )
