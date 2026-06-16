"""
Document Processing Celery Tasks

All heavy document I/O (OCR, OpenAI calls, audit rule evaluation) runs here,
off the request thread.

Task hierarchy:
  process_document_task          — Full Financial AI + Audit pipeline (v2.0)
  reprocess_document_task        — Force-reprocess an existing document
  run_nightly_anomaly_scan       — Nightly scheduled scan for all orgs
  generate_weekly_kpi_report     — Weekly KPI reports
"""

import logging
from django.core.mail import send_mail
from django.conf import settings

from celery import shared_task

logger = logging.getLogger("finai")


# ── Document processing ───────────────────────────────────────────────────────

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    time_limit=300,        # 5-minute hard limit
    soft_time_limit=270,   # Soft limit: allow clean shutdown
    name="documents.process_document_task",
)
def process_document_task(self, document_id: str) -> dict:
    """
    Full pipeline for one document (v2.0):
      1. DocumentEngine.ingest()       — MIME detection, parsing, OCR
      2. FinancialAIEngine.analyse()   — classification, extraction, fraud/dup/risk
      3. AuditEngine.evaluate()        — modular rule evaluation
      4. Persist DocumentAnalysisResult

    Retries up to 3 times on transient failures (network, OpenAI timeouts).
    Permanent failures (file missing, unsupported type) are NOT retried.
    """
    logger.info("[Task:process_document] Starting pipeline for document %s", document_id)

    try:
        from core.services.pipeline import run_full_pipeline
        result = run_full_pipeline(document_id=document_id)

        if result.get("success"):
            # Success — mark document as COMPLETED
            _safe_mark_completed(document_id)
            logger.info(
                "[Task:process_document] COMPLETED document=%s risk=%s time=%dms",
                document_id,
                result.get("risk_level", "?"),
                result.get("processing_time_ms", 0),
            )
            return {
                "document_id": document_id,
                "success": True,
                "risk_level": result.get("risk_level"),
                "risk_score": result.get("risk_score"),
                "processing_time_ms": result.get("processing_time_ms"),
            }
        else:
            # Pipeline returned failure (not an exception, but processing failed)
            error_msg = result.get("error", "Unknown pipeline error")
            logger.warning(
                "[Task:process_document] Pipeline failed for document=%s error=%s",
                document_id,
                error_msg,
            )
            # Treat as transient and retry
            raise Exception(f"Pipeline error: {error_msg}")

    except Exception as exc:
        logger.error(
            "[Task:process_document] Exception for %s (retry %d/%d): %s",
            document_id,
            self.request.retries,
            self.max_retries,
            exc,
        )

        # Only mark as FAILED if this is the final attempt (no retries left)
        if self.request.retries >= self.max_retries:
            # FINAL FAILURE — mark document as failed and notify user
            _safe_mark_failed(document_id, str(exc))
            _send_processing_failed_email(document_id, str(exc))
            logger.error(
                "[Task:process_document] FINAL FAILURE for document %s after %d retries: %s",
                document_id,
                self.max_retries,
                exc,
            )
            # Return failure result instead of re-raising
            return {
                "document_id": document_id,
                "success": False,
                "error": str(exc)[:500],
                "retries_exhausted": True,
            }
        else:
            # Transient failure — retry without marking as failed yet
            logger.warning(
                "[Task:process_document] Retrying document %s (attempt %d/%d)",
                document_id,
                self.request.retries + 1,
                self.max_retries,
            )
            raise self.retry(exc=exc)


@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=10,
    time_limit=300,
    name="documents.reprocess_document_task",
)
def reprocess_document_task(self, document_id: str) -> dict:
    """
    Force-reprocess an already-processed document.
    Resets processing_status to PENDING before calling the pipeline.
    """
    from apps.documents.models import Document

    logger.info("[Task:reprocess_document] Reprocessing document %s", document_id)

    try:
        Document.objects.filter(pk=document_id).update(
            processing_status=Document.ProcessingStatus.PENDING,
            processing_error="",
        )
    except Exception:
        pass

    return process_document_task(document_id)


# ── Scheduled tasks ───────────────────────────────────────────────────────────

@shared_task(name="documents.run_nightly_anomaly_scan")
def run_nightly_anomaly_scan():
    """
    Nightly scheduled task: scan all active organisations for transaction anomalies.

    Runs at 2:00 AM Asia/Riyadh (configured in CELERY_BEAT_SCHEDULE).
    Flags high/critical transactions and updates their risk scores.
    """
    import datetime
    from django.utils import timezone
    from apps.authentication.models import Organization
    from apps.transactions.models import Transaction
    from core.services.ai_service import detect_anomalies_ai
    from apps.billing.ai_access import ai_access_allowed

    yesterday = timezone.now().date() - datetime.timedelta(days=1)
    total_anomalies = 0

    for org in Organization.objects.filter(is_active=True):
        # AI cost guard: this task bypasses HTTP middleware, so gate per-org
        # before any OpenAI spend (skip unsubscribed/expired/over-budget orgs).
        if not ai_access_allowed(org):
            logger.info("run_nightly_anomaly_scan: skipping org %s (AI access denied)", org.id)
            continue
        try:
            txs = list(
                Transaction.objects.filter(
                    organization=org,
                    transaction_date=yesterday,
                ).values(
                    "id", "transaction_type", "amount", "currency",
                    "vendor_name", "description", "transaction_date",
                )[:500]
            )

            if not txs:
                continue

            # Serialise for AI service
            for t in txs:
                t["id"]               = str(t["id"])
                t["amount"]           = float(t["amount"])
                t["transaction_date"] = str(t["transaction_date"])

            result = detect_anomalies_ai(txs)
            anomalies = result.get("anomalies", [])

            for anomaly in anomalies:
                if anomaly.get("severity") not in ("high", "critical"):
                    continue
                try:
                    tx = Transaction.objects.get(pk=anomaly["transaction_id"])
                    tx.is_flagged  = True
                    tx.risk_score  = anomaly.get("risk_score", 0)
                    tx.risk_level  = anomaly.get("severity", "low")
                    tx.flag_reason = anomaly.get("description", "")
                    tx.save(update_fields=["is_flagged", "risk_score", "risk_level", "flag_reason"])
                    total_anomalies += 1
                except Transaction.DoesNotExist:
                    pass

            logger.info(
                "[Task:nightly_scan] org=%s txs=%d anomalies=%d",
                org.name, len(txs), len(anomalies),
            )

        except Exception as exc:
            logger.error("[Task:nightly_scan] Failed for org %s: %s", org.name, exc)

    logger.info("[Task:nightly_scan] Complete. Total flagged: %d", total_anomalies)
    return {"total_anomalies_flagged": total_anomalies}


@shared_task(name="documents.generate_weekly_kpi_report")
def generate_weekly_kpi_report():
    """
    Weekly scheduled task: generate KPI reports for all active organisations.
    Runs Monday 6:00 AM Asia/Riyadh.
    """
    import datetime
    from apps.authentication.models import Organization
    from apps.reports.models import Report

    today    = datetime.date.today()
    week_ago = today - datetime.timedelta(days=7)
    created  = 0

    for org in Organization.objects.filter(is_active=True):
        try:
            Report.objects.create(
                organization=org,
                report_type="weekly_kpi",
                language="en",
                period_from=str(week_ago),
                period_to=str(today),
                title=f"Weekly KPI Report — {today}",
                data={},
                narrative={},
            )
            created += 1
            logger.info("[Task:weekly_kpi] Report created for %s", org.name)
        except Exception as exc:
            logger.error("[Task:weekly_kpi] Failed for %s: %s", org.name, exc)

    return {"reports_created": created}


# ── Internal helpers ──────────────────────────────────────────────────────────

def _safe_mark_completed(document_id: str):
    """Mark a document as COMPLETED after successful processing."""
    try:
        from apps.documents.models import Document
        Document.objects.filter(pk=document_id).update(
            processing_status=Document.ProcessingStatus.COMPLETED,
            processing_error="",  # Clear any previous errors
        )
        logger.info("[Task] Marked document %s as COMPLETED", document_id)
    except Exception as exc:
        logger.warning("[Task] Could not mark document %s as completed: %s", document_id, exc)


def _safe_mark_failed(document_id: str, error: str):
    """Mark a document as FAILED without raising."""
    try:
        from apps.documents.models import Document
        Document.objects.filter(pk=document_id).update(
            processing_status=Document.ProcessingStatus.FAILED,
            processing_error=error[:2000],
        )
        logger.info("[Task] Marked document %s as FAILED with error: %s", document_id, error[:100])
    except Exception as exc:
        logger.warning("[Task] Could not mark document %s as failed: %s", document_id, exc)


def _send_processing_failed_email(document_id: str, error: str):
    """
    Send email notification to document uploader when processing fails finally.
    Only called on final failure (retries exhausted).
    Failures in email sending do NOT impact document processing state.
    """
    try:
        from apps.documents.models import Document
        
        # Fetch document and uploader
        doc = Document.objects.select_related('uploaded_by').get(pk=document_id)
        user_email = doc.uploaded_by.email if doc.uploaded_by else None
        
        if not user_email:
            logger.info("[Task] Document %s has no uploader email, skipping notification", document_id)
            return
        
        # Build error message (truncate for readability)
        error_display = error[:300] if error else "Unknown error occurred"
        
        subject = f"Document Processing Failed: {doc.original_filename}"
        message = f"""Hello,

Your document "{doc.original_filename}" could not be processed after multiple attempts.

Error details: {error_display}

Please try uploading the document again. If the problem persists, please contact support.

---
Tadgeeg Financial Auditing System
"""
        
        # Send email without crashing if it fails
        try:
            send_mail(
                subject=subject,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user_email],
                fail_silently=False,  # Do raise to catch, but we catch below
            )
            logger.info("[Task] Sent failure email to %s for document %s", user_email, document_id)
        except Exception as email_exc:
            logger.warning("[Task] Email delivery failed for document %s: %s (not critical)", document_id, email_exc)
        
    except Document.DoesNotExist:
        logger.warning("[Task] Document %s not found, skipping email notification", document_id)
    except Exception as exc:
        logger.error("[Task] Unexpected error sending email for document %s: %s", document_id, exc)



# ─── Bulk upload processing ────────────────────────────────────────────────────
# Drives a BulkUploadJob through completion. Reuses the existing
# process_zip / process_structured_upload pipeline from apps/invoices/services.
# Persists per-row outcomes as BulkUploadItem so the API consumer can poll
# progress and retry only the failed rows.

@shared_task(
    bind=True,
    name="documents.process_bulk_upload_job",
    max_retries=1,
    default_retry_delay=60,
    time_limit=3600,           # 1 h hard
    soft_time_limit=3540,      # 59 min soft
)
def process_bulk_upload_job(self, job_id: str) -> dict:
    """Process a queued BulkUploadJob end-to-end.

    The job's source file lives at ``summary['stored_path']`` (set by the
    view when it persisted the upload). We open it, route it through the
    appropriate parser, and persist one BulkUploadItem per row / member.
    """
    from django.core.files.storage import default_storage
    from django.utils import timezone as _tz
    from apps.documents.models import BulkUploadJob, BulkUploadItem

    try:
        job = BulkUploadJob.objects.select_related("organization", "created_by").get(pk=job_id)
    except BulkUploadJob.DoesNotExist:
        logger.warning("[Bulk] Job %s missing on dispatch", job_id)
        return {"job_id": job_id, "status": "missing"}

    stored_path = (job.summary or {}).get("stored_path", "")
    if not stored_path or not default_storage.exists(stored_path):
        job.status = BulkUploadJob.Status.FAILED
        job.summary = {**(job.summary or {}), "error": "source file not found"}
        job.finished_at = _tz.now()
        job.save(update_fields=["status", "summary", "finished_at"])
        return {"job_id": job_id, "status": "failed", "error": "source missing"}

    job.status = BulkUploadJob.Status.RUNNING
    if not job.started_at:
        job.started_at = _tz.now()
    job.save(update_fields=["status", "started_at"])

    org = job.organization
    user = job.created_by
    completed = failed = 0

    try:
        with default_storage.open(stored_path, "rb") as fh:
            data = fh.read()
        from io import BytesIO
        file_like = BytesIO(data)
        file_like.name = job.source_filename or "bulk.bin"

        if job.source_format == BulkUploadJob.SourceFormat.ZIP:
            from apps.invoices.services.processor import process_zip
            results, errors, _async = process_zip(
                file_like, org, user, batch=None, request=None, audit_session=None,
            )
            for idx, r in enumerate(results, start=1):
                BulkUploadItem.objects.create(
                    job=job, row_number=idx,
                    source_path=r.get("filename") or "",
                    document_type=job.document_type or "",
                    status=BulkUploadItem.Status.SUCCEEDED,
                    created_document_id=r.get("document_id") or r.get("id"),
                    attempt_count=1,
                )
                completed += 1
            for idx, e in enumerate(errors, start=len(results) + 1):
                BulkUploadItem.objects.create(
                    job=job, row_number=idx,
                    source_path=e.get("filename") or "",
                    document_type=job.document_type or "",
                    status=BulkUploadItem.Status.FAILED,
                    error_message=str(e.get("error") or "unknown"),
                    attempt_count=1,
                )
                failed += 1
        else:
            # Structured (CSV/XLSX/JSONL) — drive through process_structured_upload.
            from apps.invoices.services.processor import process_structured_upload
            structured = process_structured_upload(
                file_like, file_like.name, org, user,
                batch=None, request=None, audit_session=None,
            ) or {}
            for idx, r in enumerate(structured.get("results", []) or [], start=1):
                BulkUploadItem.objects.create(
                    job=job, row_number=idx,
                    source_path="",
                    document_type=job.document_type or "",
                    status=BulkUploadItem.Status.SUCCEEDED,
                    created_document_id=r.get("document_id") or r.get("id"),
                    attempt_count=1,
                )
                completed += 1
            for idx, e in enumerate(structured.get("errors", []) or [], start=completed + 1):
                BulkUploadItem.objects.create(
                    job=job, row_number=idx,
                    source_path="",
                    document_type=job.document_type or "",
                    status=BulkUploadItem.Status.FAILED,
                    error_message=str(e.get("error") or "unknown"),
                    attempt_count=1,
                )
                failed += 1

        job.completed_items = completed
        job.failed_items = failed
        job.processed_items = completed + failed
        job.total_items = job.processed_items
        if failed == 0 and completed > 0:
            job.status = BulkUploadJob.Status.COMPLETED
        elif failed > 0 and completed > 0:
            job.status = BulkUploadJob.Status.PARTIAL
        elif failed > 0 and completed == 0:
            job.status = BulkUploadJob.Status.FAILED
        else:
            job.status = BulkUploadJob.Status.COMPLETED
        job.finished_at = _tz.now()
        job.save(update_fields=[
            "completed_items", "failed_items", "processed_items",
            "total_items", "status", "finished_at",
        ])
        return {
            "job_id":    str(job.id),
            "status":    job.status,
            "completed": completed,
            "failed":    failed,
        }

    except Exception as exc:
        logger.exception("[Bulk] Job %s failed: %s", job_id, exc)
        job.status = BulkUploadJob.Status.FAILED
        job.summary = {**(job.summary or {}), "error": str(exc)[:500]}
        job.finished_at = _tz.now()
        job.save(update_fields=["status", "summary", "finished_at"])
        return {"job_id": str(job.id), "status": "failed", "error": str(exc)[:200]}
