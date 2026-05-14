"""ERP integration persistence.

Four tables:

  • ERPConnection      — per-org binding to one external ERP. Credentials
                          are stored encrypted-at-rest.
  • SyncRun            — one ingestion or egress run. Status, counts,
                          watermark snapshot, error trace.
  • SyncRecord         — one (kind, external_id) seen in a run. Maps the
                          ERP row to its local Tadgeeg row + carries the
                          hash of the raw payload so reconciliation can
                          spot ERP-side mutations.
  • ReconciliationDiff — one mismatch between ERP and Tadgeeg.
"""
from __future__ import annotations

import uuid

from django.db import models

from apps.authentication.models import Organization
from core.utils.encrypted_json import EncryptedJSONField


# ─── ERPConnection ──────────────────────────────────────────────────────────
class ERPConnection(models.Model):
    """One org → one ERP instance binding."""

    class Provider(models.TextChoices):
        SAP        = "sap",        "SAP ECC / S/4HANA"
        ORACLE     = "oracle",     "Oracle Fusion Cloud"
        ODOO       = "odoo",       "Odoo"
        DYNAMICS   = "dynamics",   "Microsoft Dynamics 365 F&O"
        QUICKBOOKS = "quickbooks", "QuickBooks Online"
        NETSUITE   = "netsuite",   "Oracle NetSuite"

    class Environment(models.TextChoices):
        PRODUCTION = "production", "Production"
        SANDBOX    = "sandbox",    "Sandbox"
        MOCK       = "mock",       "Mock"

    class Status(models.TextChoices):
        ACTIVE     = "active",     "Active"
        PAUSED     = "paused",     "Paused"
        REVOKED    = "revoked",    "Revoked"
        ERROR      = "error",      "Error"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="erp_connections",
    )
    provider    = models.CharField(max_length=16, choices=Provider.choices)
    environment = models.CharField(max_length=12, choices=Environment.choices,
                                   default=Environment.SANDBOX)
    base_url    = models.URLField(blank=True)
    # Credentials are encrypted at rest. EncryptedJSONField wraps them in a
    # Fernet token; a DB read attack yields {"_enc": "gAAAAA..."}, not keys.
    credentials = EncryptedJSONField(default=dict, blank=True)
    extra       = models.JSONField(default=dict, blank=True)
    status      = models.CharField(max_length=10, choices=Status.choices,
                                   default=Status.ACTIVE)
    # Last successful ingestion watermark — used for CDC.
    last_synced_at = models.DateTimeField(null=True, blank=True, db_index=True)
    sync_paused_reason = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        "authentication.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="created_erp_connections",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "erp_connections"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "provider", "environment"],
                name="erp_one_connection_per_org_provider_env",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["provider"]),
        ]

    def __str__(self) -> str:
        return f"{self.provider}/{self.environment} [{self.organization_id}]"


# ─── SyncRun ────────────────────────────────────────────────────────────────
class SyncRun(models.Model):
    """One ingestion or egress run."""

    class Direction(models.TextChoices):
        INGEST = "ingest", "Ingest (ERP → Tadgeeg)"
        EGRESS = "egress", "Egress (Tadgeeg → ERP)"

    class Status(models.TextChoices):
        QUEUED    = "queued",    "Queued"
        RUNNING   = "running",   "Running"
        COMPLETED = "completed", "Completed"
        FAILED    = "failed",    "Failed"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    connection = models.ForeignKey(ERPConnection, on_delete=models.CASCADE,
                                   related_name="sync_runs")
    direction  = models.CharField(max_length=8, choices=Direction.choices)
    status     = models.CharField(max_length=10, choices=Status.choices,
                                  default=Status.QUEUED, db_index=True)
    # Watermark snapshot — what the run TRIED to pull. Stored even on
    # failure so the next run can resume.
    since      = models.DateTimeField(null=True, blank=True)
    until      = models.DateTimeField(null=True, blank=True)
    kinds      = models.JSONField(default=list, blank=True)

    started_at  = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    records_seen     = models.PositiveIntegerField(default=0)
    records_imported = models.PositiveIntegerField(default=0)
    records_failed   = models.PositiveIntegerField(default=0)
    error_message    = models.TextField(blank=True)

    triggered_by = models.ForeignKey(
        "authentication.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="triggered_erp_sync_runs",
    )

    class Meta:
        db_table = "erp_sync_runs"
        ordering = ("-started_at", "-id")
        indexes = [
            models.Index(fields=["connection", "status"]),
            models.Index(fields=["direction", "status"]),
        ]


# ─── SyncRecord ─────────────────────────────────────────────────────────────
class SyncRecord(models.Model):
    """One ERP row seen in a run + its mapping to the local Tadgeeg row."""

    class Action(models.TextChoices):
        CREATED  = "created",  "Created locally"
        UPDATED  = "updated",  "Updated locally"
        SKIPPED  = "skipped",  "Skipped (no change)"
        FAILED   = "failed",   "Mapping failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(SyncRun, on_delete=models.CASCADE,
                            related_name="records")
    kind         = models.CharField(max_length=20)         # "invoice", "vendor", ...
    external_id  = models.CharField(max_length=120, db_index=True)
    # SHA-256 of the canonical RemoteRecord.payload. Lets reconciliation
    # spot ERP-side mutations on rows already imported.
    payload_sha256 = models.CharField(max_length=64, db_index=True, blank=True)
    local_model    = models.CharField(max_length=64, blank=True)   # "invoices.Invoice"
    local_pk       = models.CharField(max_length=64, blank=True, db_index=True)
    action         = models.CharField(max_length=10, choices=Action.choices,
                                      default=Action.CREATED)
    error_message  = models.TextField(blank=True)
    processed_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "erp_sync_records"
        indexes = [
            models.Index(fields=("run", "kind")),
            models.Index(fields=("external_id", "kind")),
        ]


# ─── ReconciliationDiff ─────────────────────────────────────────────────────
class ReconciliationDiff(models.Model):
    """A mismatch between what the ERP reports and what Tadgeeg holds.

    Kinds of diff:
      • missing_in_tadgeeg   — ERP has it, Tadgeeg doesn't
      • missing_in_erp       — Tadgeeg has it, ERP doesn't
      • amount_mismatch      — both have it but totals differ
      • status_mismatch      — both have it but status disagrees
      • date_mismatch
      • vat_mismatch
    """

    class Severity(models.TextChoices):
        LOW       = "low",       "Low"
        MEDIUM    = "medium",    "Medium"
        HIGH      = "high",      "High"
        CRITICAL  = "critical",  "Critical"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    connection = models.ForeignKey(ERPConnection, on_delete=models.CASCADE,
                                   related_name="reconciliation_diffs")
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="reconciliation_diffs",
    )
    kind         = models.CharField(max_length=24)
    diff_type    = models.CharField(max_length=32, db_index=True)
    severity     = models.CharField(max_length=10, choices=Severity.choices,
                                    default=Severity.MEDIUM)
    external_id  = models.CharField(max_length=120, db_index=True)
    local_pk     = models.CharField(max_length=64, blank=True)
    summary      = models.CharField(max_length=255)
    detail       = models.JSONField(default=dict, blank=True)
    resolved     = models.BooleanField(default=False, db_index=True)
    resolved_at  = models.DateTimeField(null=True, blank=True)
    detected_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "erp_reconciliation_diffs"
        indexes = [
            models.Index(fields=("organization", "resolved", "severity")),
        ]
