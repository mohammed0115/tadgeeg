"""
apps/invoices/services/processor.py
=====================================
InvoiceProcessor — owns the full per-invoice processing pipeline.

Extracted from apps/invoices/views.py where it lived as the private
_process_single_file function, making it unreachable from Celery tasks
without importing the entire view module.

Public API
----------
InvoiceProcessor.process_file(file_obj, filename, org, user, batch, request, audit_session)
    Process a single uploaded file end-to-end.

process_structured_rows_chunk(rows, *, base_name, org, user, batch, ...)
    Process a chunk of structured (CSV/Excel/JSON) rows.  Called by the
    Celery task instead of the old circular views.py import.

process_structured_upload(uploaded_file, filename, org, user, batch, ...)
    Split a structured file into chunks and process/dispatch them.

process_zip(zip_file, org, user, batch, request, audit_session)
    Extract a ZIP archive and process each file inside.
"""
from __future__ import annotations

import io
import json
import logging
import os
import time
import zipfile
from decimal import Decimal

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils.translation import gettext as _

from core.services.invoice_ai_service import analyze_invoice_risk, extract_invoice_with_ai
from core.services.invoice_validator import compute_file_hash
from core.services.normalization import NormalizationService
from core.services.ocr_service import pdf_to_images
from core.services.parsers.structured import iter_structured_records
from core.services.qr_scanner import enrich_invoice_qr
from core.services.validation_pipeline import ValidationPipelineService
from core.services.zip_validator import validate_zip_bomb, ZipValidationError
from core.utils.audit import record_invoice_event
from core.utils.coerce import to_date, to_decimal

from apps.audit.services import AuditSessionService
from apps.invoices.models import Invoice, InvoiceAuditEvent, InvoiceBatch, VendorProfile
from apps.invoices.services.validation_service import InvoiceValidationService
from core.constants import AUTO_ASYNC_FILE_SIZE as _AUTO_ASYNC_FILE_SIZE

logger = logging.getLogger("finai")

# ── Constants ─────────────────────────────────────────────────────────────────
DEFAULT_BULK_CHUNK_SIZE = 250
MIN_BULK_CHUNK_SIZE = 25
MAX_BULK_CHUNK_SIZE = 1000
AUTO_ASYNC_FILE_SIZE = _AUTO_ASYNC_FILE_SIZE  # re-exported for callers that import from here
STRUCTURED_BULK_EXTENSIONS = {".csv", ".tsv", ".json", ".xlsx", ".xls"}
ALLOWED_ZIP_MEMBER_EXTENSIONS = {
    ".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".tif",
    ".xlsx", ".xls", ".json", ".csv", ".tsv",
}

_normalizer = NormalizationService()

# Loaded lazily to avoid circular imports at module load time.
_chunk_task = None


def _get_chunk_task():
    global _chunk_task
    if _chunk_task is None:
        from apps.invoices.tasks import process_invoice_rows_chunk_task
        _chunk_task = process_invoice_rows_chunk_task
    return _chunk_task


# ── File-type helper ──────────────────────────────────────────────────────────

def _guess_mime(ext: str) -> str:
    return {
        ".pdf": "application/pdf",
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".tiff": "image/tiff", ".tif": "image/tiff",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xls": "application/vnd.ms-excel",
        ".json": "application/json",
        ".csv": "text/csv",
        ".tsv": "text/tab-separated-values",
    }.get(ext, "application/octet-stream")


# ── Vendor-history helper ─────────────────────────────────────────────────────

def get_vendor_history(org, vendor_name: str) -> dict:
    """
    Return historical statistics for a vendor within the organisation.

    Queries the denormalised VendorProfile table (fast). Falls back to an
    empty dict when the vendor is not yet known.

    This is the single canonical implementation, replacing:
      - _get_vendor_history() in apps/invoices/views.py
      - InvoiceValidationService._get_vendor_history() in validation_service.py
    """
    if not vendor_name:
        return {"is_new": True, "invoice_count": 0}
    try:
        vp = VendorProfile.objects.get(organization=org, vendor_name=vendor_name)
        return {
            "invoice_count": vp.invoice_count,
            "avg_amount": float(vp.avg_invoice_amount),
            "max_amount": float(vp.max_invoice_amount),
            "flagged_count": vp.flagged_count,
            "is_new": vp.is_new,
        }
    except VendorProfile.DoesNotExist:
        return {"is_new": True, "invoice_count": 0}


# ── Canonical invoice persistence ─────────────────────────────────────────────

def _save_canonical_invoice(invoice: Invoice) -> None:
    """
    Persist a DocumentCanonicalData record after the invoice is saved.
    Never raises — failures are logged and silently swallowed.
    """
    try:
        from core.services.canonical_mapper import CanonicalMapper
        ed = invoice.extracted_data or {}
        raw_data = {
            "invoice_number":      invoice.invoice_number,
            "invoice_date":        str(invoice.invoice_date) if invoice.invoice_date else None,
            "due_date":            str(invoice.due_date) if invoice.due_date else None,
            "vendor_name":         invoice.vendor_name,
            "vendor_vat_number":   invoice.vendor_vat_number,
            "vendor_cr_number":    invoice.vendor_cr_number,
            "customer_name":       invoice.customer_name,
            "customer_vat_number": invoice.customer_vat_number,
            "currency":            invoice.currency,
            "subtotal":            float(invoice.subtotal or 0),
            "vat_rate":            float(invoice.vat_rate or 15),
            "vat_amount":          float(invoice.vat_amount or 0),
            "discount":            float(invoice.discount or 0),
            "total_amount":        float(invoice.total_amount or 0),
            "qr_code_valid":       invoice.qr_code_valid,
            "cost_center":         ed.get("cost_center", ""),
            "department":          ed.get("department", ""),
            "account_code":        ed.get("account_code", ""),
        }
        CanonicalMapper().save_canonical(
            raw_data=raw_data,
            document_type="invoice",
            typed_model_name="Invoice",
            typed_object_id=invoice.id,
        )
    except Exception as exc:
        logger.warning("[canonical] invoice save failed for %s: %s", invoice.id, exc)


def _update_vendor_profile(org, invoice: Invoice) -> None:
    """Update vendor intelligence after processing an invoice. Never raises."""
    if not invoice.vendor_name:
        return
    try:
        from apps.invoices.services.vendor_intelligence import VendorIntelligenceService
        VendorIntelligenceService().update_from_invoice(org, invoice)
    except Exception as exc:
        logger.warning("Vendor profile update failed: %s", exc)


# ── Core single-file processor ────────────────────────────────────────────────

def process_single_file(
    file_obj,
    filename: str,
    org,
    user,
    batch=None,
    request=None,
    audit_session=None,
) -> dict:
    """
    Full invoice processing pipeline — wrapped in a single atomic transaction.

    Steps
    -----
    1. Hash check + duplicate-session guard
    2. Create Invoice record + save file bytes
    3. Document engine (MIME detection → parser dispatch)
    4. OCR / text extraction (handled inside the parser)
    5. AI extraction (GPT-4o vision)
    6. Field normalisation
    7. Financial AI engine (classify → dup → fraud → compliance → risk)
    8. Audit rule evaluation (V2 pipeline dispatched async)
    9. 30-rule ZATCA validation
    10. Risk score merge
    11. Final DB save + canonical data + vendor profile

    Returns
    -------
    dict with keys: invoice_id, filename, success, validation_score,
                    rules_failed, risk_level, is_duplicate, fraud_score,
                    findings_summary, status, processing_ms.
    On failure returns: invoice_id (if created), filename, success=False, error.
    """
    from core.services.document_engine import DocumentEngine
    from core.services.financial_ai_engine import FinancialAIEngine
    from apps.audit.audit_engine import run_audit

    start = time.time()
    ext = os.path.splitext(filename)[1].lower()
    file_data = file_obj.read()
    file_obj.seek(0)

    # ── Step 1: Deduplication guard ───────────────────────────────────────────
    file_hash = compute_file_hash(io.BytesIO(file_data))
    if audit_session:
        AuditSessionService.advance_to_extracting(audit_session)
        if AuditSessionService.has_file_hash(audit_session, file_hash):
            raise ValueError(_("Duplicate file already processed in this audit session."))

    # ── Steps 2-11 wrapped in one atomic block ────────────────────────────────
    with transaction.atomic():
        # ── Step 2: Create Invoice record ────────────────────────────────────
        invoice = Invoice.objects.create(
            organization=org,
            uploaded_by=user,
            audit_session=audit_session,
            batch=batch,
            file=ContentFile(file_data, name=filename),
            original_filename=filename,
            file_size=len(file_data),
            mime_type=getattr(file_obj, "content_type", "") or "",
            extracted_data={"file_hash": file_hash},
        )
        record_invoice_event(
            invoice, user, InvoiceAuditEvent.EventType.UPLOADED,
            f"Uploaded: {filename}", request=request,
        )

        file_path = invoice.file.path

        # ── Step 3: Document engine ───────────────────────────────────────────
        doc_engine = DocumentEngine(use_ai=True)
        ingestion = doc_engine.ingest(file_path)
        if audit_session:
            AuditSessionService.advance_to_normalizing(audit_session)

        if ingestion.fatal_error:
            invoice.status = Invoice.Status.FLAGGED
            invoice.processing_error = ingestion.fatal_error
            invoice.extracted_data = {"file_hash": file_hash, "error": ingestion.fatal_error}
            invoice.save(update_fields=["status", "processing_error", "extracted_data", "updated_at"])
            return {
                "invoice_id": str(invoice.id), "filename": filename,
                "success": False, "error": ingestion.fatal_error, "risk_level": "high",
            }

        # ── Step 4: OCR confidence (extraction done inside parser) ────────────
        raw_text = ingestion.raw_text
        ocr_confidence = float(ingestion.metadata.get("ocr_confidence", 0.0))
        record_invoice_event(
            invoice, user, InvoiceAuditEvent.EventType.PROCESSED,
            f"Parser: {ingestion.extraction_method} | OCR confidence: {ocr_confidence:.0f}%",
            request=request,
        )

        # ── Step 5: AI extraction (GPT-4o) ────────────────────────────────────
        if ext == ".pdf":
            try:
                img_pages = pdf_to_images(file_path)
                img_for_ai = img_pages[0] if img_pages else file_path
            except Exception:
                img_for_ai = file_path
        else:
            img_for_ai = file_path

        try:
            ai_data = extract_invoice_with_ai(img_for_ai, raw_text)
        except Exception as exc:
            logger.warning("OpenAI extraction failed for %s: %s", filename, exc)
            from core.services.invoice_ai_service import _fallback_extraction
            ai_data = _fallback_extraction(raw_text)

        # ── Step 6: Normalisation ─────────────────────────────────────────────
        normalized_ingestion = ingestion.normalized or {}
        normalization = _normalizer.normalize(
            {
                **normalized_ingestion,
                **(ingestion.structured or {}),
                **(ai_data or {}),
                "raw_text": raw_text,
                "extraction_method": ingestion.extraction_method,
                "language": (
                    ai_data.get("language")
                    or normalized_ingestion.get("language")
                    or ingestion.metadata.get("language", "unknown")
                ),
            },
            default_currency=getattr(org, "currency", "SAR") or "SAR",
        )
        normalized = normalization.normalized_data
        serialized_normalized = normalization.to_serializable_dict()

        def _first_non_empty(*values):
            for v in values:
                if v is None:
                    continue
                if isinstance(v, str):
                    cleaned = v.strip()
                    if cleaned:
                        return cleaned
                    continue
                return v
            return ""

        invoice.invoice_number    = str(_first_non_empty(normalized.get("invoice_number"), ai_data.get("invoice_number"), filename) or "")
        invoice.invoice_date      = to_date(normalized.get("invoice_date") or ai_data.get("invoice_date"))
        invoice.due_date          = to_date(normalized.get("due_date") or ai_data.get("due_date"))
        invoice.vendor_name       = str(_first_non_empty(
            normalized.get("vendor_name"), ai_data.get("vendor_name"),
            ai_data.get("vendor_name_ar"), ai_data.get("supplier_name"), ai_data.get("merchant_name"),
        ) or "")
        invoice.vendor_name_ar    = str(_first_non_empty(ai_data.get("vendor_name_ar"), ai_data.get("vendor_name")) or "")
        invoice.vendor_vat_number = str(normalized.get("vendor_vat_number") or ai_data.get("vendor_vat_number", "") or "")
        invoice.vendor_cr_number  = str(ai_data.get("vendor_cr_number", "") or "")
        invoice.vendor_address    = str(ai_data.get("vendor_address", "") or "")
        invoice.vendor_phone      = str(ai_data.get("vendor_phone", "") or "")
        invoice.customer_name     = str(normalized.get("customer_name") or ai_data.get("customer_name", "") or "")
        invoice.customer_vat_number = str(normalized.get("customer_vat_number") or ai_data.get("customer_vat_number", "") or "")
        invoice.currency          = str(normalized.get("currency") or ai_data.get("currency", "SAR") or "SAR")
        invoice.subtotal          = to_decimal(normalized.get("subtotal"))
        invoice.vat_rate          = to_decimal(normalized.get("vat_rate", 15), Decimal("15"))
        invoice.vat_amount        = to_decimal(normalized.get("vat_amount"))
        invoice.discount          = to_decimal(normalized.get("discount"))
        invoice.total_amount      = to_decimal(normalized.get("total_amount"))
        invoice.line_items        = serialized_normalized.get("line_items") or ai_data.get("line_items", [])
        invoice.has_qr_code       = bool(normalized.get("has_qr_code", False))
        invoice.qr_code_valid     = bool(ai_data.get("qr_code_valid", False))

        try:
            qr_result = enrich_invoice_qr(file_path)
            if qr_result.get("found"):
                invoice.has_qr_code = True
                tlv = qr_result.get("tlv_data", {})
                qr_vat = str(tlv.get("vat_number", "") or "")

                # Use QR-extracted TRN only when OCR/AI extraction missed it.
                if not invoice.vendor_vat_number and qr_vat:
                    invoice.vendor_vat_number = qr_vat
                    logger.info("[QR] TRN enriched from QR code: %s", qr_vat)

                # Accept 10-digit simplified or 15-digit ZATCA TRN formats.
                invoice.qr_code_valid = bool(qr_vat and len(qr_vat) in (10, 15))
            else:
                logger.debug("[QR] No QR code found in %s: %s", filename, qr_result.get("error"))
        except Exception as exc:
            # Never let QR scan failures interrupt invoice processing.
            logger.warning("[QR] QR scan failed for %s: %s", filename, exc)

        invoice.is_handwritten    = bool(ai_data.get("is_handwritten") or ingestion.metadata.get("is_handwritten", False))
        invoice.is_clear          = bool(ai_data.get("is_clear", True))
        invoice.has_alterations   = bool(ai_data.get("has_alterations", False))
        invoice.language          = str(normalized.get("language") or ai_data.get("language", "unknown"))
        invoice.raw_text          = raw_text
        invoice.ocr_confidence    = ocr_confidence
        invoice.ai_summary        = str(ai_data.get("ai_summary", ""))
        invoice.extracted_data    = {
            **ai_data,
            "file_hash": file_hash,
            "_extraction_method": ingestion.extraction_method,
            "normalized": serialized_normalized,
        }
        invoice.status = Invoice.Status.PROCESSING
        invoice.save()

        # ── Step 7: Financial AI engine ───────────────────────────────────────
        country_code = getattr(org, "country", "SA") or "SA"
        ai_engine = FinancialAIEngine(organization_id=org.id, country_code=country_code, use_ai=True)
        analysis = ai_engine.analyse(ingestion)

        # ── Step 7a: Legacy audit engine (structural rules + AuditCase) ───────
        try:
            run_audit(
                analysis.to_dict(),
                organization_id=org.id,
                invoice_id=invoice.id,
                persist=True,
            )
        except Exception as exc:
            logger.warning("Audit engine failed for %s: %s", filename, exc)

    # ── Step 7b: V2 rule engine — dispatched async OUTSIDE the transaction ────
    # Running this inside the transaction would hold the DB connection open
    # for the entire Celery round-trip.
    try:
        from apps.rule_engine.tasks.audit_tasks import run_audit_task
        run_audit_task.delay(
            document_id=str(invoice.id),
            document_type="sales_invoice",
            organization_id=str(org.id),
            triggered_by="upload",
        )
    except Exception as exc:
        logger.warning("Rule engine pipeline trigger failed for %s: %s", filename, exc)

    # ── Steps 8-11: Validation, risk scoring, final DB save ───────────────────
    with transaction.atomic():
        if audit_session:
            AuditSessionService.advance_to_validating(audit_session)
        val_result = ValidationPipelineService.validate_invoice(
            invoice=invoice,
            organization=org,
            file_hash=file_hash,
            created_by=user,
        )

        record_invoice_event(
            invoice, user, InvoiceAuditEvent.EventType.VALIDATED,
            f"Validation: {val_result['validation_score']:.0f}% | Failed: {val_result['failed_rule_codes']}",
            request=request,
        )

        # ── Step 9: Risk score merge ──────────────────────────────────────────
        vendor_hist = get_vendor_history(org, invoice.vendor_name)
        try:
            ai_risk = analyze_invoice_risk(
                {k: v for k, v in invoice.extracted_data.items() if not k.startswith("_")},
                vendor_hist,
            )
        except Exception as exc:
            logger.warning("AI risk analysis failed for %s: %s", filename, exc)
            ai_risk = {}

        ai_risk["overall_risk_score"] = max(
            float(ai_risk.get("overall_risk_score") or 0.0),
            float(analysis.risk_score),
        )
        InvoiceValidationService.merge_risk_assessment(invoice, val_result, ai_risk)

        invoice.is_duplicate = invoice.is_duplicate or analysis.is_duplicate
        invoice.save()

    # ── Step 10-11: Canonical data + vendor profile (fire-and-forget) ─────────
    _save_canonical_invoice(invoice)
    _update_vendor_profile(org, invoice)

    elapsed_ms = int((time.time() - start) * 1000)
    logger.info(
        "[Processor] %s | risk=%s | score=%.0f%% | dup=%s | fraud=%.2f | %dms",
        filename, invoice.risk_level, val_result["validation_score"],
        invoice.is_duplicate, analysis.fraud_score, elapsed_ms,
    )

    if audit_session:
        AuditSessionService.record_success(
            audit_session,
            invoice,
            review_required=bool(
                getattr(analysis, "requires_review", False)
                or invoice.status == Invoice.Status.FLAGGED
                or bool(val_result.get("failed_rule_codes"))
            ),
        )

    return {
        "invoice_id":       str(invoice.id),
        "filename":         filename,
        "success":          True,
        "validation_score": val_result["validation_score"],
        "rules_failed":     val_result["failed_rule_codes"],
        "risk_level":       invoice.risk_level,
        "is_duplicate":     invoice.is_duplicate,
        "fraud_score":      round(analysis.fraud_score, 2),
        "findings_summary": val_result.get("findings_summary", {}),
        "status":           invoice.status,
        "processing_ms":    elapsed_ms,
    }


# ── Chunk processor (used by Celery tasks) ─────────────────────────────────────

def process_structured_rows_chunk(
    rows,
    *,
    base_name: str,
    org,
    user,
    batch,
    request=None,
    audit_session=None,
    persist_batch_progress: bool = True,
) -> dict:
    """
    Process a pre-built list of structured rows (from CSV/Excel/JSON).

    Each item in *rows* must be ``{"row_number": int, "payload": dict}``.

    This is the canonical implementation.  Previously lived in views.py and
    was imported by tasks.py, causing a circular dependency.  Celery tasks
    now import from here instead.
    """
    results, errors = [], []
    success_count = failure_count = duplicate_count = high_risk_count = review_required_count = 0
    last_error = ""

    for item in rows:
        row_number = item.get("row_number") or (success_count + failure_count + 1)
        payload = item.get("payload") or {}
        if not payload:
            continue

        row_name = f"{base_name}_row{row_number}.json"
        item_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        file_like = io.BytesIO(item_bytes)
        file_like.name = row_name
        file_like.size = len(item_bytes)
        file_like.content_type = "application/json"

        try:
            result = process_single_file(file_like, row_name, org, user, batch, request, audit_session)
        except Exception as exc:
            logger.error("Structured row %s failed: %s", row_name, exc)
            result = {"success": False, "error": str(exc)}

        if result.get("success"):
            results.append(result)
            success_count += 1
            if result.get("is_duplicate"):
                duplicate_count += 1
            if result.get("risk_level") in {"high", "critical"}:
                high_risk_count += 1
            if result.get("status") == Invoice.Status.FLAGGED or bool(result.get("rules_failed")):
                review_required_count += 1
        else:
            message = result.get("error") or "Processing failed"
            errors.append({"filename": row_name, "error": message})
            failure_count += 1
            last_error = message
            if audit_session:
                AuditSessionService.record_failure(audit_session, message)

    if persist_batch_progress and batch is not None and (success_count or failure_count):
        batch.processed_files += success_count
        batch.failed_files += failure_count

    return {
        "results": results,
        "errors": errors,
        "success_count": success_count,
        "failure_count": failure_count,
        "duplicate_count": duplicate_count,
        "high_risk_count": high_risk_count,
        "review_required_count": review_required_count,
        "last_error": last_error,
    }


# ── Structured-upload orchestrator ────────────────────────────────────────────

def _is_truthy(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _parse_chunk_size(raw_value) -> int:
    try:
        numeric = int(raw_value or DEFAULT_BULK_CHUNK_SIZE)
    except (TypeError, ValueError):
        numeric = DEFAULT_BULK_CHUNK_SIZE
    return max(MIN_BULK_CHUNK_SIZE, min(numeric, MAX_BULK_CHUNK_SIZE))


def _should_queue_async(request=None, uploaded_file=None) -> bool:
    if request is not None:
        data = getattr(request, "data", {}) or {}
        if _is_truthy(data.get("async")) or _is_truthy(data.get("use_async")):
            return True
        params = getattr(request, "query_params", {}) or {}
        if _is_truthy(params.get("async")) or _is_truthy(params.get("use_async")):
            return True
    return bool(uploaded_file and getattr(uploaded_file, "size", 0) >= AUTO_ASYNC_FILE_SIZE)


def process_structured_upload(
    uploaded_file,
    filename: str,
    org,
    user,
    batch,
    request=None,
    audit_session=None,
) -> dict | None:
    """
    Parse a structured file (CSV/Excel/JSON), split into chunks, and either
    process them inline (sync) or dispatch to Celery (async).

    Returns None if the file is not a supported structured type.
    """
    row_iter = iter_structured_records(uploaded_file, filename)
    if row_iter is None:
        return None

    base_name = os.path.splitext(filename)[0]
    chunk_size = _parse_chunk_size(
        (getattr(request, "data", {}) or {}).get("chunk_size") if request else None
    )
    prefer_async = _should_queue_async(request, uploaded_file)

    results, errors = [], []
    pending_chunks = []
    current_chunk = []
    total_rows = 0

    for row_number, payload in row_iter:
        total_rows += 1
        current_chunk.append({"row_number": row_number, "payload": payload})
        if len(current_chunk) >= chunk_size:
            if prefer_async:
                pending_chunks.append(current_chunk)
            else:
                outcome = process_structured_rows_chunk(
                    current_chunk, base_name=base_name, org=org, user=user,
                    batch=batch, request=request, audit_session=audit_session,
                )
                results.extend(outcome["results"])
                errors.extend(outcome["errors"])
            current_chunk = []

    if current_chunk:
        if prefer_async:
            pending_chunks.append(current_chunk)
        else:
            outcome = process_structured_rows_chunk(
                current_chunk, base_name=base_name, org=org, user=user,
                batch=batch, request=request, audit_session=audit_session,
            )
            results.extend(outcome["results"])
            errors.extend(outcome["errors"])

    if total_rows == 0:
        return None

    batch.total_files += max(total_rows - 1, 0)
    if audit_session:
        AuditSessionService.sync_expected_total(audit_session, batch.total_files)

    if prefer_async and pending_chunks:
        batch.status = InvoiceBatch.BatchStatus.PROCESSING
        if audit_session:
            AuditSessionService.advance_to_extracting(audit_session)

        queued_task_ids = []
        for chunk in pending_chunks:
            try:
                task = _get_chunk_task()
                async_result = task.delay(
                    rows=chunk,
                    base_name=base_name,
                    org_id=str(org.id),
                    user_id=str(user.id),
                    batch_id=str(batch.id),
                    audit_session_id=str(audit_session.id) if audit_session else None,
                )
                queued_task_ids.append(getattr(async_result, "id", ""))
            except Exception as exc:
                logger.warning(
                    "Async chunk dispatch failed for %s; falling back to inline: %s",
                    filename, exc,
                )
                inline = process_structured_rows_chunk(
                    chunk, base_name=base_name, org=org, user=user,
                    batch=batch, request=request, audit_session=audit_session,
                )
                results.extend(inline["results"])
                errors.extend(inline["errors"])

        if queued_task_ids:
            batch.processing_log = list(batch.processing_log or []) + [{
                "mode": "async_chunked",
                "source_file": filename,
                "queued_rows": total_rows,
                "queued_chunks": len(queued_task_ids),
                "chunk_size": chunk_size,
                "task_ids": queued_task_ids,
                "streaming": True,
            }]
            batch.save(update_fields=["status", "total_files", "processed_files", "failed_files", "processing_log"])
            return {
                "handled": True,
                "mode": "async_chunked",
                "results": results,
                "errors": errors,
                "queued_rows": total_rows,
                "queued_chunks": len(queued_task_ids),
                "task_ids": queued_task_ids,
                "chunk_size": chunk_size,
                "streaming": True,
            }

    return {
        "handled": True,
        "mode": "sync_chunked",
        "results": results,
        "errors": errors,
        "queued_rows": 0,
        "queued_chunks": 0,
        "task_ids": [],
        "chunk_size": chunk_size,
        "streaming": True,
        "processed_rows": total_rows,
    }


# ── ZIP processor ──────────────────────────────────────────────────────────────

def process_zip(zip_file, org, user, batch, request=None, audit_session=None):
    """Extract and process all invoice files inside a ZIP archive."""
    results, errors, async_jobs = [], [], []
    try:
        zip_file.seek(0)
        try:
            validate_zip_bomb(zip_file)
        except ZipValidationError as exc:
            errors.append({"filename": zip_file.name, "error": str(exc)})
            if audit_session:
                AuditSessionService.record_failure(audit_session, str(exc))
            return results, errors, async_jobs

        zip_file.seek(0)
        with zipfile.ZipFile(io.BytesIO(zip_file.read()), "r") as zf:
            for member in zf.infolist():
                if member.is_dir():
                    continue
                name = os.path.basename(member.filename)
                ext = os.path.splitext(name)[1].lower()
                if ext not in ALLOWED_ZIP_MEMBER_EXTENSIONS:
                    continue
                try:
                    data = zf.read(member)
                    file_like = io.BytesIO(data)
                    file_like.name = name
                    file_like.size = len(data)
                    file_like.content_type = _guess_mime(ext)

                    if ext in STRUCTURED_BULK_EXTENSIONS:
                        structured = process_structured_upload(
                            file_like, name, org, user, batch, request, audit_session
                        )
                        if structured and structured.get("handled"):
                            results.extend(structured.get("results", []))
                            errors.extend(structured.get("errors", []))
                            if structured.get("mode") == "async_chunked":
                                async_jobs.append({
                                    "filename": name,
                                    "queued_rows": structured.get("queued_rows", 0),
                                    "queued_chunks": structured.get("queued_chunks", 0),
                                    "task_ids": structured.get("task_ids", []),
                                    "chunk_size": structured.get("chunk_size"),
                                    "streaming": structured.get("streaming", True),
                                })
                        continue

                    result = process_single_file(file_like, name, org, user, batch, request, audit_session)
                    if result.get("success"):
                        results.append(result)
                        batch.processed_files += 1
                    else:
                        message = result.get("error") or "Processing failed"
                        errors.append({"filename": name, "error": message})
                        batch.failed_files += 1
                        if audit_session:
                            AuditSessionService.record_failure(audit_session, message)
                except Exception as exc:
                    logger.error("ZIP member %s failed: %s", name, exc)
                    errors.append({"filename": name, "error": str(exc)})
                    batch.failed_files += 1
                    if audit_session:
                        AuditSessionService.record_failure(audit_session, str(exc))
    except Exception as exc:
        logger.error("ZIP extraction failed for %s: %s", getattr(zip_file, "name", "?"), exc)
        errors.append({"filename": getattr(zip_file, "name", "archive.zip"), "error": str(exc)})

    return results, errors, async_jobs
