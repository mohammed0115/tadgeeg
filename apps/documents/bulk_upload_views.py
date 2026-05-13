"""
HTTP endpoints for BulkUploadJob — spec'd in
Docs/tadgeeg_enterprise_readiness_pack/API_AND_ERP_INTEGRATION_CONTRACTS.md §8.

  POST /api/v1/documents/bulk-upload-jobs/
        body: multipart `file` + optional `document_type` form field
        →  201 Created, JobSerializer(job).data
        Creates the job + persists the source file via existing storage
        layer, then enqueues processing. Returns immediately with job_id
        for polling. Idempotency-Key middleware (added in earlier commit)
        gives ERP clients safe retry semantics.

  GET  /api/v1/documents/bulk-upload-jobs/
        →  200 OK, paginated list of the org's recent jobs.

  GET  /api/v1/documents/bulk-upload-jobs/{id}/
        →  200 OK with summary + paginated items (≤ 200 per page).

  POST /api/v1/documents/bulk-upload-jobs/{id}/retry-failed/
        →  202 Accepted, returns task_id for the re-run.

The actual row-by-row processing reuses the existing
`apps/invoices/services/processor.py` pipeline (process_structured_upload
+ process_zip) — those already handle chunked Celery dispatch via
`process_structured_rows_chunk`. This wrapper just persists the tracker
rows so the client gets visibility.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from django.utils import timezone
from drf_spectacular.utils import extend_schema, OpenApiParameter
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import BulkUploadJob, BulkUploadItem

logger = logging.getLogger("finai")


# ── Serializers ───────────────────────────────────────────────────────────────

class BulkUploadItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = BulkUploadItem
        fields = [
            "id", "row_number", "source_path", "document_type", "status",
            "created_document_id", "audit_run_id", "error_code",
            "error_message", "attempt_count", "created_at", "updated_at",
        ]
        read_only_fields = fields


class BulkUploadJobSerializer(serializers.ModelSerializer):
    progress_pct = serializers.IntegerField(read_only=True)

    class Meta:
        model = BulkUploadJob
        fields = [
            "id", "document_type", "source_filename", "source_format",
            "source_file_size", "status", "total_items", "processed_items",
            "completed_items", "failed_items", "skipped_items",
            "progress_pct", "summary", "task_ids", "created_at",
            "updated_at", "started_at", "finished_at",
            # Stage 6 billing/quota fields
            "allowed_items", "blocked_items",
            "quota_required", "quota_available", "quota_status",
        ]
        read_only_fields = fields


# ── Helpers ───────────────────────────────────────────────────────────────────

_SOURCE_FORMAT_MAP = {
    ".zip":   BulkUploadJob.SourceFormat.ZIP,
    ".xlsx":  BulkUploadJob.SourceFormat.XLSX,
    ".xls":   BulkUploadJob.SourceFormat.XLS,
    ".csv":   BulkUploadJob.SourceFormat.CSV,
    ".jsonl": BulkUploadJob.SourceFormat.JSONL,
    ".json":  BulkUploadJob.SourceFormat.JSON,
}


def _detect_format(filename: str) -> str:
    ext = os.path.splitext(filename or "")[1].lower()
    return _SOURCE_FORMAT_MAP.get(ext, BulkUploadJob.SourceFormat.MIXED)


_TRUE_VALUES = frozenset({"1", "true", "yes", "on", "True"})


def _coerce_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip() in _TRUE_VALUES


def _enqueue_processing(job: BulkUploadJob, upload_file) -> Optional[str]:
    """Dispatch the actual chunked processing.

    Returns the Celery task_id, or None if Celery is unreachable (in which
    case the job stays in PENDING and an operator can re-trigger).
    """
    try:
        from apps.documents.tasks import process_bulk_upload_job
    except ImportError:
        logger.warning(
            "process_bulk_upload_job task not registered yet — job %s left PENDING",
            job.id,
        )
        return None
    try:
        # The task itself rehydrates the file from MEDIA_ROOT — we don't pass
        # the UploadedFile through Celery, just the persisted path. Saving
        # happens in the view BEFORE dispatch, so the worker can read it.
        result = process_bulk_upload_job.delay(job_id=str(job.id))
        return result.id
    except Exception as exc:
        logger.warning("Could not enqueue bulk upload job %s: %s", job.id, exc)
        return None


# ── Views ─────────────────────────────────────────────────────────────────────

class BulkUploadJobListCreateView(APIView):
    """POST: create a new bulk job. GET: list recent jobs for the org."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Bulk Upload"],
        summary="List bulk-upload jobs for the current organization",
        parameters=[OpenApiParameter("status", description="Filter by status")],
    )
    def get(self, request):
        qs = BulkUploadJob.objects.filter(organization=request.user.organization)
        if s := request.query_params.get("status"):
            qs = qs.filter(status=s)
        # Cap to most recent 100 to keep the response bounded.
        return Response(BulkUploadJobSerializer(qs[:100], many=True).data)

    @extend_schema(
        tags=["Bulk Upload"],
        summary="Submit a bulk upload (CSV / Excel / JSONL / ZIP)",
    )
    def post(self, request):
        up = request.FILES.get("file")
        if up is None:
            return Response({"error": "missing `file` field"}, status=400)
        # 50 MB ceiling — matches MAX_UPLOAD_SIZE_MB in settings_canonical.
        from django.conf import settings as dj_settings
        size_limit = int(getattr(dj_settings, "MAX_UPLOAD_SIZE_MB", 50)) * 1024 * 1024
        if up.size > size_limit:
            return Response({
                "error": "file_too_large",
                "message": f"Upload exceeds {size_limit} bytes.",
            }, status=413)

        doc_type = (request.data.get("document_type") or "").strip()
        accept_partial = _coerce_bool(request.data.get("accept_partial"))

        # Determine the format BEFORE saving — we need it to count items.
        safe_name_for_format = up.name or "bulk_upload.bin"
        source_format = _detect_format(safe_name_for_format)

        # Read bytes once, into memory. We've already capped file size
        # at MAX_UPLOAD_SIZE_MB (50 by default) so this is bounded.
        file_bytes = up.read()
        up.seek(0)  # rewind for the storage save below

        # ── Stage 6: pre-flight quota check ─────────────────────────────
        from apps.billing.bulk_quota import count_items, evaluate_bulk_quota
        total_items = count_items(file_bytes, source_format, safe_name_for_format)
        decision = evaluate_bulk_quota(
            organization=request.user.organization,
            total_items=total_items,
            accept_partial=accept_partial,
        )

        if not decision.accepted:
            return Response({
                "success":          False,
                "code":             decision.code,
                "message":          decision.message,
                "total_items":      decision.total_items,
                "quota_required":   decision.quota_required,
                "quota_available":  decision.quota_available,
                "quota_status":     decision.quota_status,
                "upgrade_required": True,
            }, status=status.HTTP_402_PAYMENT_REQUIRED)

        # ── Persist source bytes for the worker ────────────────────────
        from django.core.files.storage import default_storage
        from django.utils.text import get_valid_filename
        safe_name = get_valid_filename(up.name or "bulk_upload.bin")
        stored_path = default_storage.save(
            f"bulk_uploads/{request.user.organization_id}/{safe_name}", up,
        )

        job = BulkUploadJob.objects.create(
            organization=request.user.organization,
            created_by=request.user,
            document_type=doc_type,
            source_filename=safe_name,
            source_format=source_format,
            source_file_size=up.size,
            status=BulkUploadJob.Status.PENDING,
            summary={"stored_path": stored_path},
            # Quota snapshot from the pre-check
            total_items=decision.total_items,
            allowed_items=decision.allowed_items,
            blocked_items=decision.blocked_items,
            quota_required=decision.quota_required,
            quota_available=decision.quota_available,
            quota_status=decision.quota_status,
        )

        task_id = _enqueue_processing(job, up)
        if task_id:
            job.task_ids = [task_id]
            job.status = BulkUploadJob.Status.RUNNING
            job.started_at = timezone.now()
            job.save(update_fields=["task_ids", "status", "started_at"])

        return Response(
            BulkUploadJobSerializer(job).data,
            status=status.HTTP_201_CREATED,
        )


class BulkUploadJobDetailView(APIView):
    """GET: job summary + paginated items."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Bulk Upload"],
        summary="Get bulk-upload job detail",
        parameters=[
            OpenApiParameter("status", description="Filter items by status"),
            OpenApiParameter("page", description="1-based page", required=False),
            OpenApiParameter("page_size", description="Items per page (≤200)", required=False),
        ],
    )
    def get(self, request, pk):
        try:
            job = BulkUploadJob.objects.get(
                pk=pk, organization=request.user.organization,
            )
        except BulkUploadJob.DoesNotExist:
            return Response({"error": "not found"}, status=404)

        items_qs = job.items.all()
        if s := request.query_params.get("status"):
            items_qs = items_qs.filter(status=s)
        try:
            page = max(1, int(request.query_params.get("page", 1)))
            page_size = min(200, max(1, int(request.query_params.get("page_size", 50))))
        except ValueError:
            page, page_size = 1, 50
        start = (page - 1) * page_size
        items_page = list(items_qs[start:start + page_size])

        return Response({
            "job":         BulkUploadJobSerializer(job).data,
            "items": {
                "page":       page,
                "page_size":  page_size,
                "count":      items_qs.count(),
                "results":    BulkUploadItemSerializer(items_page, many=True).data,
            },
        })


class BulkUploadJobRetryFailedView(APIView):
    """POST: re-run only the FAILED items of a job."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Bulk Upload"],
        summary="Retry failed items of a bulk-upload job",
    )
    def post(self, request, pk):
        try:
            job = BulkUploadJob.objects.get(
                pk=pk, organization=request.user.organization,
            )
        except BulkUploadJob.DoesNotExist:
            return Response({"error": "not found"}, status=404)

        # Reset the failed items so the worker picks them up again.
        failed_qs = job.items.filter(status=BulkUploadItem.Status.FAILED)
        count = failed_qs.count()
        if not count:
            return Response({
                "status":  "noop",
                "message": "No failed items to retry.",
            }, status=200)

        failed_qs.update(
            status=BulkUploadItem.Status.PENDING,
            error_code="",
            error_message="",
        )

        # Reset job aggregate counters and re-dispatch.
        job.status = BulkUploadJob.Status.RUNNING
        job.failed_items = 0
        # processed_items is decremented by the number of failed items being
        # re-queued so progress_pct reflects the redo.
        job.processed_items = max(0, job.processed_items - count)
        job.finished_at = None
        job.save(update_fields=[
            "status", "failed_items", "processed_items", "finished_at",
        ])

        task_id = _enqueue_processing(job, None)
        if task_id:
            job.task_ids = list(job.task_ids or []) + [task_id]
            job.save(update_fields=["task_ids"])

        return Response({
            "status":   "queued",
            "retried":  count,
            "task_id":  task_id,
            "job":      BulkUploadJobSerializer(job).data,
        }, status=202)
