"""Celery async tasks for document processing and AI analysis"""

import logging
from celery import shared_task

logger = logging.getLogger("finai")


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def process_document_task(self, document_id: str):
    """Async: Process a document with OCR + AI."""
    try:
        from apps.documents.models import Document, ExtractedData, DocumentPageResult
        from core.services.ocr_service import process_document_hybrid
        import time

        doc = Document.objects.get(pk=document_id)
        doc.processing_status = Document.ProcessingStatus.PROCESSING
        doc.save(update_fields=["processing_status"])

        result = process_document_hybrid(doc.file.path, doc.document_type, use_openai=True)

        ExtractedData.objects.update_or_create(
            document=doc,
            defaults={
                "raw_text": result["raw_text"],
                "structured_data": result["structured_data"],
                "extraction_method": result["method"],
                "ai_model_used": result["structured_data"].get("_ai_model", ""),
            },
        )

        DocumentPageResult.objects.filter(document=doc).delete()
        for pr in result.get("page_results", []):
            DocumentPageResult.objects.create(
                document=doc,
                page_number=pr["page"],
                raw_text=pr["text"],
                confidence=pr["confidence"],
                image_path=pr.get("image_path", ""),
            )

        doc.processing_status = (
            Document.ProcessingStatus.NEEDS_REVIEW
            if result["confidence"] < 60
            else Document.ProcessingStatus.COMPLETED
        )
        doc.ocr_confidence = result["confidence"]
        doc.language = result.get("language", "unknown")
        doc.is_handwritten = result.get("is_handwritten", False)
        doc.processing_duration_ms = result.get("processing_ms", 0)
        doc.processing_error = ""
        doc.save()

        logger.info(f"Document {document_id} processed. Confidence: {result['confidence']:.1f}%")
        return {"success": True, "confidence": result["confidence"]}

    except Exception as exc:
        logger.error(f"Document {document_id} processing failed: {exc}")
        try:
            from apps.documents.models import Document
            Document.objects.filter(pk=document_id).update(
                processing_status=Document.ProcessingStatus.FAILED,
                processing_error=str(exc),
            )
        except Exception:
            pass
        raise self.retry(exc=exc)


@shared_task
def run_nightly_anomaly_scan():
    """Nightly scheduled: scan all organizations for anomalies."""
    from apps.authentication.models import Organization
    from apps.transactions.models import Transaction
    from core.services.ai_service import detect_anomalies_ai
    from django.utils import timezone
    import datetime

    yesterday = timezone.now().date() - datetime.timedelta(days=1)

    for org in Organization.objects.filter(is_active=True):
        try:
            txs = list(Transaction.objects.filter(
                organization=org, transaction_date=yesterday
            ).values(
                "id", "transaction_type", "amount", "currency",
                "vendor_name", "description", "transaction_date"
            )[:500])

            for t in txs:
                t["id"] = str(t["id"])
                t["amount"] = float(t["amount"])
                t["transaction_date"] = str(t["transaction_date"])

            if txs:
                result = detect_anomalies_ai(txs)
                for anomaly in result.get("anomalies", []):
                    if anomaly.get("severity") in ["high", "critical"]:
                        try:
                            tx = Transaction.objects.get(pk=anomaly["transaction_id"])
                            tx.is_flagged = True
                            tx.risk_score = anomaly.get("risk_score", 0)
                            tx.risk_level = anomaly.get("severity", "low")
                            tx.flag_reason = anomaly.get("description", "")
                            tx.save(update_fields=["is_flagged", "risk_score", "risk_level", "flag_reason"])
                        except Transaction.DoesNotExist:
                            pass

                logger.info(f"Nightly scan for {org.name}: {len(txs)} txs, {len(result.get('anomalies', []))} anomalies")

        except Exception as e:
            logger.error(f"Nightly scan failed for {org.name}: {e}")


@shared_task
def generate_weekly_kpi_report():
    """Generate weekly KPI reports for all organizations."""
    from apps.authentication.models import Organization, User
    from apps.reports.models import Report
    from core.services.ai_service import generate_audit_narrative
    import datetime

    for org in Organization.objects.filter(is_active=True):
        try:
            today = datetime.date.today()
            week_ago = today - datetime.timedelta(days=7)
            report = Report.objects.create(
                organization=org,
                report_type="weekly_kpi",
                language="en",
                period_from=str(week_ago),
                period_to=str(today),
                title=f"Weekly KPI Report - {today}",
                data={},
                narrative={},
            )
            logger.info(f"Weekly KPI report created for {org.name}: {report.id}")
        except Exception as e:
            logger.error(f"Weekly report failed for {org.name}: {e}")
