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
            logger.info(
                "[Task:process_document] DONE document=%s risk=%s time=%dms",
                document_id,
                result.get("risk_level", "?"),
                result.get("processing_time_ms", 0),
            )
        else:
            logger.warning(
                "[Task:process_document] FAILED document=%s error=%s",
                document_id,
                result.get("error", "unknown"),
            )

        return {
            "document_id": document_id,
            "success": result.get("success", False),
            "risk_level": result.get("risk_level"),
            "risk_score": result.get("risk_score"),
            "processing_time_ms": result.get("processing_time_ms"),
        }

    except Exception as exc:
        logger.error("[Task:process_document] Exception for %s: %s", document_id, exc)

        # Mark as failed immediately if it's a permanent error
        _safe_mark_failed(document_id, str(exc))

        # Retry for transient errors (OpenAI timeouts, network blips)
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

    yesterday = timezone.now().date() - datetime.timedelta(days=1)
    total_anomalies = 0

    for org in Organization.objects.filter(is_active=True):
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

def _safe_mark_failed(document_id: str, error: str):
    """Mark a document as FAILED without raising."""
    try:
        from apps.documents.models import Document
        Document.objects.filter(pk=document_id).update(
            processing_status=Document.ProcessingStatus.FAILED,
            processing_error=error[:2000],
        )
    except Exception as exc:
        logger.warning("[Task] Could not mark document %s as failed: %s", document_id, exc)
