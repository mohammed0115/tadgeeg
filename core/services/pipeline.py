"""
Unified Document Processing Pipeline — FinAI v2.0

One-call orchestrator that runs the complete document intelligence pipeline:

    Upload File
    → DocumentEngine.ingest()       — MIME detection, parsing, OCR, text extraction
    → FinancialAIEngine.analyse()   — classification, extraction, dup/fraud/compliance/risk
    → AuditEngine.evaluate()        — modular rule evaluation, issue persistence
    → Persist DocumentAnalysisResult

This module is the single entry point for all background document processing
and can also be called synchronously from views for small files.

Usage (from Celery task):
    from core.services.pipeline import run_full_pipeline
    result = run_full_pipeline(document_id=str(doc.id))

Usage (direct):
    from core.services.pipeline import run_full_pipeline_for_file
    result = run_full_pipeline_for_file(
        file_path="/media/documents/2024/03/invoice.pdf",
        document_id=uuid_str,
        organization_id=42,
        country_code="SA",
    )
"""

import logging
import time
from decimal import Decimal, InvalidOperation
from typing import Optional

logger = logging.getLogger("finai")

# Pipeline version — bump when the scoring logic changes
PIPELINE_VERSION = "2.0"


# ── Public API ────────────────────────────────────────────────────────────────

def run_full_pipeline(document_id: str, session_id: Optional[str] = None) -> dict:
    """
    Run the complete pipeline for an existing Document record.

    Loads the document from the database, processes it, and saves
    a DocumentAnalysisResult.  Updates Document.processing_status throughout.

    :param document_id: UUID string of the Document to process.
    :param session_id:  Optional UUID string of an AuditSession to link findings to.

    Returns a summary dict suitable for Celery task result storage.
    """
    from apps.documents.models import Document

    try:
        doc = Document.objects.get(pk=document_id)
    except Document.DoesNotExist:
        logger.error("[Pipeline] Document %s not found", document_id)
        return {"success": False, "error": "Document not found", "document_id": document_id}

    # Guard: don't reprocess a document already being handled
    if doc.processing_status == Document.ProcessingStatus.PROCESSING:
        logger.warning("[Pipeline] Document %s already processing — skipping", document_id)
        return {"success": False, "error": "Already processing", "document_id": document_id}

    doc.processing_status = Document.ProcessingStatus.PROCESSING
    doc.processing_error = ""
    doc.save(update_fields=["processing_status", "processing_error"])

    _t0 = time.monotonic()
    try:
        result = run_full_pipeline_for_file(
            file_path=doc.file.path,
            document_id=str(doc.id),
            organization_id=doc.organization_id,
            country_code=_get_org_country(doc.organization_id),
            use_ai=True,
            session_id=session_id,
            document_obj=doc,
        )
        _persist_result(doc, result)
        _record_pipeline_metric(doc.processing_status, time.monotonic() - _t0)
        return result

    except Exception as exc:
        logger.exception("[Pipeline] Unhandled error for document %s: %s", document_id, exc)
        doc.processing_status = Document.ProcessingStatus.FAILED
        doc.processing_error = str(exc)
        doc.save(update_fields=["processing_status", "processing_error"])
        _record_pipeline_metric("failed", time.monotonic() - _t0)
        return {"success": False, "error": str(exc), "document_id": document_id}


def _record_pipeline_metric(status: str, duration_s: float) -> None:
    """Record document processing metrics — fire-and-forget, never raises."""
    try:
        from core.utils.metrics import documents_processed_total, document_processing_seconds
        documents_processed_total.labels(status=status).inc()
        document_processing_seconds.observe(duration_s)
    except Exception:
        pass  # metrics are best-effort


def run_full_pipeline_for_file(
    file_path: str,
    document_id: Optional[str] = None,
    organization_id: Optional[int] = None,
    country_code: str = "SA",
    use_ai: bool = True,
    session_id: Optional[str] = None,
    document_obj=None,
) -> dict:
    """
    Run the full pipeline on an arbitrary file path.

    Does NOT touch the database — returns a plain dict.
    Suitable for unit testing and standalone use.

    Pipeline:
        DocumentEngine.ingest()
        → FinancialAIEngine.analyse()
        → AuditEngine.evaluate()

    Returns:
        {
            success, document_id, file_path,
            ingestion: {...},
            analysis: FinancialAnalysisResult.to_dict(),
            audit: serialised AuditReport,
            risk_level, risk_score, fraud_score, duplicate_score, compliance_score,
            processing_time_ms, errors
        }
    """
    t_start = time.monotonic()
    errors: list[str] = []

    summary = {
        "success": False,
        "document_id": document_id,
        "file_path": file_path,
        "pipeline_version": PIPELINE_VERSION,
        "ingestion": {},
        "analysis": {},
        "audit": {},
        "risk_level": "high",
        "risk_score": 60,
        "fraud_score": 0.0,
        "duplicate_score": 0.0,
        "compliance_score": 1.0,
        "is_duplicate": False,
        "requires_review": False,
        "escalate": False,
        "processing_time_ms": 0,
        "errors": errors,
    }

    # ── Stage 1: Document Ingestion ───────────────────────────────────────────
    try:
        from core.services.document_engine import DocumentEngine
        engine = DocumentEngine(use_ai=use_ai)
        ingestion = engine.ingest(file_path)
        summary["ingestion"] = ingestion.to_dict()

        if not ingestion.success:
            errors.append(f"Ingestion failed: {ingestion.fatal_error}")
            logger.error("[Pipeline] Ingestion failed for %s: %s", file_path, ingestion.fatal_error)
            _set_timing(summary, t_start)
            return summary

        logger.info(
            "[Pipeline] Stage 1 DONE — file=%s mime=%s method=%s",
            ingestion.file_name, ingestion.mime_type, ingestion.extraction_method,
        )
    except Exception as exc:
        errors.append(f"Stage 1 (Ingestion) exception: {exc}")
        logger.exception("[Pipeline] Stage 1 exception for %s", file_path)
        _set_timing(summary, t_start)
        return summary

    # ── Update Document status: PROCESSING (stage boundary) ──────────────
    _update_document_status(document_id, "processing", "stage_1_complete")

    # ── Stage 2: Financial AI Analysis ───────────────────────────────────────
    analysis = None
    try:
        from core.services.financial_ai_engine import FinancialAIEngine
        ai_engine = FinancialAIEngine(
            organization_id=organization_id,
            country_code=country_code,
            use_ai=use_ai,
        )
        analysis = ai_engine.analyse(ingestion)
        analysis_dict = analysis.to_dict()
        summary["analysis"] = analysis_dict

        # Propagate key signals
        summary["risk_level"]       = analysis.risk_level
        summary["risk_score"]       = analysis.risk_score
        summary["fraud_score"]      = analysis.fraud_score
        summary["duplicate_score"]  = analysis.duplicate_score
        summary["compliance_score"] = analysis.compliance_score
        summary["is_duplicate"]     = analysis.is_duplicate
        summary["requires_review"]  = analysis.requires_review
        summary["escalate"]         = analysis.escalate

        if analysis.processing_errors:
            errors.extend(analysis.processing_errors)

        logger.info(
            "[Pipeline] Stage 2 DONE — type=%s risk=%s(%d) dup=%.2f fraud=%.2f comp=%.2f",
            analysis.document_type,
            analysis.risk_level,
            analysis.risk_score,
            analysis.duplicate_score,
            analysis.fraud_score,
            analysis.compliance_score,
        )
    except Exception as exc:
        errors.append(f"Stage 2 (Financial AI) exception: {exc}")
        logger.exception("[Pipeline] Stage 2 exception for %s", file_path)
        # Continue to audit with whatever partial data we have

    # ── Update Document status: stage boundary ────────────────────────────
    _update_document_status(document_id, "processing", "stage_2_complete")

    # ── Stage 3.5: Normalization + Validation + Finding Persistence ──────────
    validation_summary: dict = {}
    try:
        from core.services.validation_service import ValidationService

        # Resolve AuditSession if a session_id was supplied
        audit_session = None
        if session_id:
            try:
                from apps.audit.models import AuditSession
                audit_session = AuditSession.objects.get(pk=session_id)
                # Advance session state: NORMALIZING
                if audit_session.can_transition_to(AuditSession.State.NORMALIZING):
                    audit_session.state = AuditSession.State.NORMALIZING
                    audit_session.save(update_fields=["state", "updated_at"])
            except Exception as exc:
                logger.warning("[Pipeline] Could not load AuditSession %s: %s", session_id, exc)

        val_svc = ValidationService(
            session=audit_session,
            document=document_obj,
            persist=audit_session is not None,
        )
        val_result = val_svc.run(analysis.to_dict() if analysis else {})
        validation_summary = val_result.summary
        summary["validation"] = validation_summary

        # Advance session state: VALIDATING
        if audit_session and audit_session.can_transition_to(AuditSession.State.VALIDATING):
            audit_session.state = AuditSession.State.VALIDATING
            audit_session.save(update_fields=["state", "updated_at"])

        # If critical findings → mark requires_review + escalate
        if val_result.has_critical:
            summary["requires_review"] = True
            summary["escalate"]        = True
            logger.warning(
                "[Pipeline] Stage 3.5 — %d critical validation finding(s) for %s",
                len(val_result.report.critical_failures), file_path,
            )

        logger.info(
            "[Pipeline] Stage 3.5 DONE — rules=%d failed=%d critical=%d findings_saved=%d",
            validation_summary.get("total_rules", 0),
            validation_summary.get("failed", 0),
            validation_summary.get("critical_failures", 0),
            validation_summary.get("findings_persisted", 0),
        )
    except Exception as exc:
        errors.append(f"Stage 3.5 (Validation) exception: {exc}")
        logger.exception("[Pipeline] Stage 3.5 exception for %s", file_path)

    # ── Stage 3: Audit Rule Engine ────────────────────────────────────────────
    try:
        from apps.audit.audit_engine import AuditEngine

        doc_dict = analysis.to_dict() if analysis else summary["ingestion"].get("normalized", {})

        # Enrich context with pre-computed scores so audit rules can use them
        context = {
            "duplicate_result": {
                "duplicate_score":    summary["duplicate_score"],
                "is_duplicate":       summary["is_duplicate"],
                "duplicate_reasons":  analysis.duplicate_reasons if analysis else [],
            },
            "compliance_result": {
                "compliance_score": summary["compliance_score"],
                "vat_valid":        analysis.vat_valid if analysis else True,
                "issues":           analysis.compliance_issues if analysis else [],
                "missing_fields":   analysis.missing_fields if analysis else [],
            },
        }

        audit_engine = AuditEngine(organization_id=organization_id)
        report = audit_engine.evaluate(
            document=doc_dict,
            context=context,
        )

        # Serialise AuditReport to JSON-safe dict
        audit_dict = _serialise_audit_report(report)
        summary["audit"] = audit_dict

        # Audit engine may escalate risk further
        if report.risk_score > summary["risk_score"]:
            summary["risk_score"] = report.risk_score
            summary["risk_level"] = report.risk_level
        if report.escalate:
            summary["escalate"] = True

        logger.info(
            "[Pipeline] Stage 3 DONE — rules=%d failed=%d risk_level=%s escalate=%s",
            report.total_rules,
            report.failed_count,
            report.risk_level,
            report.escalate,
        )
    except Exception as exc:
        errors.append(f"Stage 3 (Audit Engine) exception: {exc}")
        logger.exception("[Pipeline] Stage 3 exception for %s", file_path)

    summary["success"] = True
    _set_timing(summary, t_start)

    logger.info(
        "[Pipeline] COMPLETE — file=%s risk=%s(%d) time=%dms errors=%d",
        file_path,
        summary["risk_level"],
        summary["risk_score"],
        summary["processing_time_ms"],
        len(errors),
    )
    return summary


# ── Database persistence ──────────────────────────────────────────────────────

def _persist_result(doc, result: dict):
    """
    Save pipeline output to Document and DocumentAnalysisResult records.
    Also saves ExtractedData for backward compatibility with existing APIs.
    """
    from apps.documents.models import Document, ExtractedData, DocumentAnalysisResult

    analysis_data = result.get("analysis", {})
    audit_data    = result.get("audit", {})
    ingestion     = result.get("ingestion", {})

    # ── Update Document ───────────────────────────────────────────────────────
    new_status = Document.ProcessingStatus.NEEDS_REVIEW if (
        result["risk_level"] in ("high", "critical") or
        not result["success"]
    ) else Document.ProcessingStatus.COMPLETED

    doc.processing_status     = new_status if result["success"] else Document.ProcessingStatus.FAILED
    doc.processing_error      = "; ".join(result.get("errors", [])) if not result["success"] else ""
    doc.processing_duration_ms = result.get("processing_time_ms")
    doc.ocr_confidence        = ingestion.get("metadata", {}).get("ocr_confidence") or None
    doc.language              = analysis_data.get("language") or ingestion.get("metadata", {}).get("language") or "unknown"
    doc.is_handwritten        = bool(analysis_data.get("language") == "handwritten")
    doc.page_count            = ingestion.get("page_count", 1)

    # Update document_type from AI classification if available
    ai_type = analysis_data.get("document_type", "")
    if ai_type and ai_type != "other":
        # Map FinancialAIEngine types to Document.DocumentType choices
        type_map = {
            "invoice":        "invoice",
            "purchase_order": "purchase_order",
            "bank_statement": "bank_statement",
            "receipt":        "receipt",
            "expense_report": "expense_report",
            "payroll":        "other",
            "vat_return":     "tax_document",
        }
        doc.document_type = type_map.get(ai_type, "other")

    doc.save(update_fields=[
        "processing_status", "processing_error", "processing_duration_ms",
        "ocr_confidence", "language", "is_handwritten", "page_count", "document_type",
    ])

    # ── Save ExtractedData (backward compatibility) ───────────────────────────
    try:
        ExtractedData.objects.update_or_create(
            document=doc,
            defaults={
                "raw_text":         (ingestion.get("raw_text") or "")[:50000],
                "structured_data":  analysis_data,
                "extraction_method": analysis_data.get("extraction_tier", "pipeline"),
                "ai_model_used":    "gpt-4o",
            },
        )
    except Exception as exc:
        logger.warning("[Pipeline] ExtractedData save failed for %s: %s", doc.id, exc)

    # ── Save DocumentAnalysisResult ───────────────────────────────────────────
    try:
        _to_decimal = lambda v: _safe_decimal(v)

        DocumentAnalysisResult.objects.update_or_create(
            document=doc,
            defaults={
                "ai_document_type":           analysis_data.get("document_type", "other"),
                "classification_confidence":  float(analysis_data.get("classification_confidence", 0.0)),
                "classification_method":      analysis_data.get("classification_method", "unknown"),
                "vendor_name":                (analysis_data.get("vendor_name") or "")[:255],
                "document_number":            (analysis_data.get("document_number") or "")[:100],
                "doc_date":                   _parse_date(analysis_data.get("date")),
                "currency":                   (analysis_data.get("currency") or "SAR")[:10],
                "total_amount":               _to_decimal(analysis_data.get("total_amount")),
                "tax_amount":                 _to_decimal(analysis_data.get("tax_amount")),
                "risk_score":                 int(result.get("risk_score", 0)),
                "risk_level":                 result.get("risk_level", "low"),
                "fraud_score":                float(result.get("fraud_score", 0.0)),
                "duplicate_score":            float(result.get("duplicate_score", 0.0)),
                "compliance_score":           float(result.get("compliance_score", 1.0)),
                "is_duplicate":               bool(result.get("is_duplicate", False)),
                "requires_review":            bool(result.get("requires_review", False)),
                "escalate":                   bool(result.get("escalate", False)),
                "analysis_data":              analysis_data,
                "audit_report":               audit_data,
                "pipeline_version":           PIPELINE_VERSION,
                "processing_errors":          result.get("errors", []),
                "processing_time_ms":         result.get("processing_time_ms"),
            },
        )
    except Exception as exc:
        logger.exception("[Pipeline] DocumentAnalysisResult save failed for %s: %s", doc.id, exc)

    logger.info(
        "[Pipeline] Results persisted for document %s — status=%s risk=%s",
        doc.id, doc.processing_status, result.get("risk_level"),
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_org_country(organization_id) -> str:
    """Retrieve organisation country code; defaults to SA."""
    if not organization_id:
        return "SA"
    try:
        from apps.authentication.models import Organization
        org = Organization.objects.get(pk=organization_id)
        return getattr(org, "country_code", "SA") or "SA"
    except Exception:
        return "SA"


def _set_timing(summary: dict, t_start: float):
    summary["processing_time_ms"] = int((time.monotonic() - t_start) * 1000)


def _safe_decimal(value) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None


def _parse_date(value):
    """Parse a date string to a date object; returns None on failure."""
    if not value:
        return None
    from datetime import date
    if isinstance(value, date):
        return value
    import re
    s = str(value).strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        try:
            from datetime import datetime
            return datetime.strptime(s, "%Y-%m-%d").date()
        except ValueError:
            return None
    for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%d %b %Y", "%B %d, %Y"):
        try:
            from datetime import datetime
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _update_document_status(document_id: Optional[str], status: str, checkpoint: str = ""):
    """
    Lightweight stage-boundary status update.
    Uses the ProcessingStatus enum to avoid storing raw string values.
    Non-blocking — never raises.
    """
    if not document_id:
        return
    try:
        from apps.documents.models import Document
        # Map raw string → enum value so the DB receives the correct choice key.
        status_map = {
            "pending":      Document.ProcessingStatus.PENDING,
            "processing":   Document.ProcessingStatus.PROCESSING,
            "completed":    Document.ProcessingStatus.COMPLETED,
            "failed":       Document.ProcessingStatus.FAILED,
            "needs_review": Document.ProcessingStatus.NEEDS_REVIEW,
        }
        enum_status = status_map.get(status, Document.ProcessingStatus.PROCESSING)
        Document.objects.filter(pk=document_id).update(
            processing_status=enum_status,
        )
        logger.debug("[Pipeline] Document %s status=%s checkpoint=%s", document_id, enum_status, checkpoint)
    except Exception:
        pass  # Non-critical — never block the pipeline


def _serialise_audit_report(report) -> dict:
    """Convert AuditReport dataclass to a JSON-serialisable dict."""
    from apps.audit.rules.base_rule import RuleStatus

    rules = []
    for r in report.rule_results:
        rules.append({
            "rule_id":     r.rule_id,
            "rule_name":   r.rule_name,
            "severity":    r.severity.value if hasattr(r.severity, "value") else str(r.severity),
            "result":      r.result.value   if hasattr(r.result,   "value") else str(r.result),
            "explanation": r.explanation,
            "details":     r.details or {},
        })

    return {
        "risk_score":     report.risk_score,
        "risk_level":     report.risk_level,
        "total_rules":    report.total_rules,
        "passed_count":   report.passed_count,
        "failed_count":   report.failed_count,
        "skipped_count":  report.skipped_count,
        "error_count":    report.error_count,
        "escalate":       report.escalate,
        "processing_time_ms": report.processing_time_ms,
        "summary":        report.summary,
        "rule_results":   rules,
    }
