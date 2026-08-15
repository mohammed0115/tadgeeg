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

from apps.audit.reports import AuditReport

logger = logging.getLogger("finai")

# Pipeline version — bump when the scoring logic changes
PIPELINE_VERSION = "2.0"


# ── Public API ────────────────────────────────────────────────────────────────

def run_full_pipeline(document_id: str) -> dict:
    """
    Run the complete pipeline for an existing Document record.

    Loads the document from the database, processes it, and saves
    a DocumentAnalysisResult.  Updates Document.processing_status throughout.

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

    try:
        result = run_full_pipeline_for_file(
            file_path=doc.file.path,
            document_id=str(doc.id),
            organization_id=doc.organization_id,
            country_code=_get_org_country(doc.organization_id),
            use_ai=True,
        )
        _persist_result(doc, result)
        return result

    except Exception as exc:
        logger.exception("[Pipeline] Unhandled error for document %s: %s", document_id, exc)
        doc.processing_status = Document.ProcessingStatus.FAILED
        doc.processing_error = str(exc)
        doc.save(update_fields=["processing_status", "processing_error"])
        return {"success": False, "error": str(exc), "document_id": document_id}


def run_full_pipeline_for_file(
    file_path: str,
    document_id: Optional[str] = None,
    organization_id: Optional[int] = None,
    country_code: str = "SA",
    use_ai: bool = True,
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

    # ── Stage 3: Audit Rule Engine ────────────────────────────────────────────
    try:
        from apps.rule_engine.services.compatibility.legacy_audit_adapter import (
            LegacyAuditEngineAdapter,
        )

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

        if not document_id:
            # Stand-alone file processing has no persistent typed record, so no
            # V2 normalizer or quota identity exists.  Refuse the audit stage
            # explicitly rather than evaluating a dictionary with AuditEngine
            # and writing an incompatible legacy result.
            raise ValueError("Stage 3 requires a persisted Document id")

        audit_engine = LegacyAuditEngineAdapter(organization_id=organization_id)
        report = audit_engine.evaluate_document(document_id=document_id, context=context)

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
            # Detected, then discarded: the classifier distinguishes payroll and
            # Document.DocumentType has no choice for it, so the distinction is
            # lost here. Adding a choice needs a migration, which is outside
            # this shipment. Recorded in docs/EXECUTION_TRACKER.md as
            # deviation 74 rather than quietly accepted.
            "payroll":        "other",
            "vat_return":     "tax_document",
        }
        if ai_type not in type_map:
            # "unknown" arrives here whenever no parser determined a type — the
            # normal case, not an error — and so does any value a future
            # classifier starts returning. Both land on "other", which is
            # correct and lossless for the first and lossy for the second. Log
            # it so the second is visible: a widening classifier that nobody
            # noticed is how a document type goes unaudited.
            #
            # Logged, never raised. A new classifier value must not stop an
            # upload.
            logger.info(
                "[Pipeline] document_type %r is not in type_map — storing "
                "'other' for document %s", ai_type, doc.pk,
            )
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


def _serialise_audit_report(report: AuditReport) -> dict:
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
