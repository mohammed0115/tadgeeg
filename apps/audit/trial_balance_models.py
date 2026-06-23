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
