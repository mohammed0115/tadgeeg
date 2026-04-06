"""Celery tasks for scalable invoice bulk uploads."""

from __future__ import annotations

import logging

from celery import shared_task
from django.db.models import F
from django.utils import timezone

logger = logging.getLogger("finai")


def _finalize_batch_if_ready(batch_id: str, audit_session_id: str | None = None) -> None:
    from apps.audit.models import AuditSession
    from apps.audit.services import AuditSessionService
    from apps.invoices.models import InvoiceBatch

    batch = InvoiceBatch.objects.get(pk=batch_id)
    if batch.processed_files + batch.failed_files < batch.total_files:
        return

    if batch.failed_files and batch.processed_files:
        final_status = InvoiceBatch.BatchStatus.PARTIAL
    elif batch.failed_files:
        final_status = InvoiceBatch.BatchStatus.FAILED
    else:
        final_status = InvoiceBatch.BatchStatus.COMPLETED

    batch.status = final_status
    batch.completed_at = timezone.now()
    batch.save(update_fields=["status", "completed_at"])

    if audit_session_id:
        session = AuditSession.objects.filter(pk=audit_session_id).first()
        if session:
            AuditSessionService.sync_expected_total(session, batch.total_files)
            AuditSessionService.finalize_if_ready(session)


@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=15,
    time_limit=1200,
    soft_time_limit=1100,
    name="invoices.process_invoice_rows_chunk",
)
def process_invoice_rows_chunk_task(
    self,
    *,
    rows,
    base_name: str,
    org_id: str,
    user_id: str,
    batch_id: str,
    audit_session_id: str | None = None,
) -> dict:
    """Process one chunk of structured invoice rows outside the request thread."""
    from apps.audit.models import AuditSession
    from apps.authentication.models import Organization, User
    from apps.invoices.models import InvoiceBatch
    from apps.invoices.views import _process_structured_rows_chunk

    logger.info(
        "[Task:invoice_chunk] Processing batch=%s rows=%s base=%s",
        batch_id,
        len(rows or []),
        base_name,
    )

    org = Organization.objects.get(pk=org_id)
    user = User.objects.get(pk=user_id)
    batch = InvoiceBatch.objects.get(pk=batch_id)
    session = AuditSession.objects.filter(pk=audit_session_id).first() if audit_session_id else None

    outcome = _process_structured_rows_chunk(
        rows,
        base_name=base_name,
        org=org,
        user=user,
        batch=batch,
        request=None,
        audit_session=None,
        persist_batch_progress=False,
    )

    success_count = int(outcome.get("success_count") or 0)
    failure_count = int(outcome.get("failure_count") or 0)
    duplicate_count = int(outcome.get("duplicate_count") or 0)
    high_risk_count = int(outcome.get("high_risk_count") or 0)
    review_required_count = int(outcome.get("review_required_count") or 0)
    last_error = outcome.get("last_error") or ""

    InvoiceBatch.objects.filter(pk=batch_id).update(
        processed_files=F("processed_files") + success_count,
        failed_files=F("failed_files") + failure_count,
        status=InvoiceBatch.BatchStatus.PROCESSING,
    )

    if session:
        update_kwargs = {
            "processed_count": F("processed_count") + success_count + failure_count,
            "success_count": F("success_count") + success_count,
            "failed_count": F("failed_count") + failure_count,
            "duplicate_count": F("duplicate_count") + duplicate_count,
            "high_risk_count": F("high_risk_count") + high_risk_count,
            "review_required_count": F("review_required_count") + review_required_count,
        }
        if last_error:
            update_kwargs["last_error"] = last_error
        AuditSession.objects.filter(pk=audit_session_id).update(**update_kwargs)

    _finalize_batch_if_ready(batch_id, audit_session_id)

    logger.info(
        "[Task:invoice_chunk] Finished batch=%s success=%s failed=%s",
        batch_id,
        success_count,
        failure_count,
    )
    return {
        "batch_id": batch_id,
        "success": True,
        "processed": success_count,
        "failed": failure_count,
        "duplicate_count": duplicate_count,
        "high_risk_count": high_risk_count,
    }
