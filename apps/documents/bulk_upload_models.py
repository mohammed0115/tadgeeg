"""
BulkUploadJob + BulkUploadItem — tracking models for async bulk file uploads.

The existing processor (`apps/invoices/services/processor.py`) already
handles chunked processing of CSV / Excel / JSONL via Celery
(`process_structured_rows_chunk`). What was missing was a persistent
tracker so a client can:

  • POST a bulk file and get a job_id immediately (no 30-minute wait).
  • Poll job status: pending / running / completed / failed / partial.
  • Inspect per-row outcomes via BulkUploadItem.
  • POST `/retry-failed/` to re-run only the failed rows.

The tracker is intentionally agnostic about the input format. Each
BulkUploadItem represents one logical row / file inside the upload
(ZIP member, CSV row, JSONL line, etc.) and carries enough metadata
to be re-tried independently.
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

from apps.authentication.models import Organization


class BulkUploadJob(models.Model):
    """Top-level tracker for one bulk upload submission."""

    class Status(models.TextChoices):
        PENDING   = "pending",   "Pending"
        RUNNING   = "running",   "Running"
        COMPLETED = "completed", "Completed"
        FAILED    = "failed",    "Failed"
        PARTIAL   = "partial",   "Partial — some rows failed"
        CANCELLED = "cancelled", "Cancelled"

    class SourceFormat(models.TextChoices):
        ZIP    = "zip",    "ZIP archive"
        XLSX   = "xlsx",   "Excel"
        XLS    = "xls",    "Legacy Excel"
        CSV    = "csv",    "CSV"
        JSONL  = "jsonl",  "JSON Lines"
        JSON   = "json",   "JSON array"
        MIXED  = "mixed",  "Multiple kinds inside a ZIP"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="bulk_upload_jobs",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="bulk_upload_jobs",
    )
    document_type = models.CharField(
        max_length=32, blank=True,
        help_text="Target doc type (e.g. 'invoice', 'purchase_order'). "
                  "Blank for ZIP uploads where each member has its own type.",
    )
    source_filename = models.CharField(max_length=255, blank=True)
    source_format = models.CharField(
        max_length=12, choices=SourceFormat.choices, default=SourceFormat.CSV,
    )
    source_file_size = models.PositiveBigIntegerField(default=0)

    status = models.CharField(max_length=12, choices=Status.choices,
                              default=Status.PENDING, db_index=True)
    total_items     = models.PositiveIntegerField(default=0)
    processed_items = models.PositiveIntegerField(default=0)
    completed_items = models.PositiveIntegerField(default=0)
    failed_items    = models.PositiveIntegerField(default=0)
    skipped_items   = models.PositiveIntegerField(default=0)

    # Aggregate task identifiers — typically Celery task_ids. Useful for
    # status polling and for revoke-in-flight on cancel.
    task_ids = models.JSONField(default=list, blank=True)

    # Free-form summary written when the job completes.
    summary = models.JSONField(default=dict, blank=True)

    created_at  = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at  = models.DateTimeField(auto_now=True)
    started_at  = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "bulk_upload_jobs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "-created_at"]),
            models.Index(fields=["organization", "status"]),
        ]

    def __str__(self) -> str:
        return f"BulkUploadJob<{self.id} {self.status} {self.processed_items}/{self.total_items}>"

    @property
    def progress_pct(self) -> int:
        if not self.total_items:
            return 0 if self.status in (self.Status.PENDING, self.Status.RUNNING) else 100
        return min(100, int((self.processed_items / self.total_items) * 100))


class BulkUploadItem(models.Model):
    """One logical row / file inside a bulk upload.

    The pair (job, row_number) uniquely identifies a position inside the
    source. `created_document_id` is populated when the row created a
    document so the API consumer can drill into it; `audit_run_id` lets
    the consumer trace which audit run was triggered.
    """

    class Status(models.TextChoices):
        PENDING   = "pending",   "Pending"
        RUNNING   = "running",   "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED    = "failed",    "Failed"
        SKIPPED   = "skipped",   "Skipped"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(
        BulkUploadJob, on_delete=models.CASCADE, related_name="items",
    )
    row_number = models.PositiveIntegerField(
        help_text="1-based row index inside the source file (CSV/XLSX/JSONL), "
                  "or the member index inside a ZIP.",
    )
    source_path = models.CharField(
        max_length=512, blank=True,
        help_text="Relative path inside the source (e.g. 'invoices/2026/inv1.pdf').",
    )
    document_type = models.CharField(max_length=32, blank=True)

    status = models.CharField(max_length=10, choices=Status.choices,
                              default=Status.PENDING, db_index=True)

    # Outcome pointers — set when the row creates a document / audit run.
    created_document_id = models.UUIDField(null=True, blank=True)
    audit_run_id        = models.UUIDField(null=True, blank=True)

    # Failure context — human-readable message + machine-readable code.
    error_code    = models.CharField(max_length=64, blank=True)
    error_message = models.TextField(blank=True)
    attempt_count = models.PositiveSmallIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "bulk_upload_items"
        ordering = ["job", "row_number"]
        indexes = [
            models.Index(fields=["job", "status"]),
            models.Index(fields=["job", "row_number"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["job", "row_number"], name="bulk_item_unique_row",
            ),
        ]

    def __str__(self) -> str:
        return f"BulkUploadItem<job={self.job_id} row={self.row_number} {self.status}>"
