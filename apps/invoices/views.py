"""
Invoice Auditing Views
Supports: single file, multiple files, ZIP archive upload.
Runs all 30 validation rules + AI analysis on each invoice.
"""

import io
import logging
import os
import time
import zipfile
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.core.files.base import ContentFile
from django.db.models import Avg, Count, Max, Min, Q, Sum
from django.shortcuts import render
from django.utils import timezone
from django.utils.dateparse import parse_date
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from apps.audit.services import AuditSessionService
from apps.audit.serializers import AuditFindingSerializer
from apps.authentication.permissions import IsSeniorAuditorOrAbove, IsOwnOrganization
from core.services.invoice_ai_service import analyze_invoice_risk, extract_invoice_with_ai
from core.services.invoice_validator import RULES, TOTAL_RULES, compute_file_hash
from core.services.invoice_validator import run_all_rules as core_run_all_rules
from core.services.normalization import NormalizationService
from core.services.ocr_service import pdf_to_images
from core.services.validation_pipeline import ValidationPipelineService
from core.utils.audit import log_action
from apps.authentication.models import AuditLog

from .models import (
    Invoice, InvoiceAuditEvent, InvoiceBatch, InvoiceValidationResult, VendorProfile
)
from .serializers import (
    InvoiceAuditEventSerializer,
    InvoiceBatchSerializer, InvoiceDetailSerializer,
    InvoiceListSerializer, InvoiceValidationResultSerializer,
    VendorProfileSerializer,
)

logger = logging.getLogger("finai")
normalizer = NormalizationService()


def run_all_rules(invoice, organization=None, file_hash: str = "") -> dict:
    """Backward-compatible validation entry point used by older callers and tests."""
    return core_run_all_rules(invoice, organization=organization, file_hash=file_hash)

ALLOWED_MIME = {"application/pdf", "image/jpeg", "image/png", "image/tiff",
                "application/zip", "application/x-zip-compressed",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "application/vnd.ms-excel", "application/json", "text/json",
                "text/csv", "text/plain", "text/tab-separated-values",
                "application/csv", "application/octet-stream"}
ALLOWED_EXT  = {".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".zip",
                ".xlsx", ".xls", ".json", ".csv", ".tsv"}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _get_client_ip(request):
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    return xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR", "")


def _save_audit_event(invoice, user, event_type, description="", before=None, after=None, request=None):
    InvoiceAuditEvent.objects.create(
        invoice=invoice,
        user=user,
        event_type=event_type,
        description=description,
        before_data=before or {},
        after_data=after or {},
        ip_address=_get_client_ip(request) if request else None,
    )


def _first_non_empty(*values):
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned:
                return cleaned
            continue
        return value
    return ""


def _to_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError, ArithmeticError):
        return default


def _risk_level_from_score(score):
    numeric_score = max(0.0, min(100.0, _to_float(score)))
    if numeric_score >= 70:
        return "high"
    if numeric_score >= 40:
        return "medium"
    return "low"


def _fallback_risk_score(validation_result):
    validation_score = max(0.0, min(100.0, _to_float(validation_result.get("validation_score"), 0.0)))
    failed_codes = set(validation_result.get("failed_rule_codes") or [])
    fallback_score = round(100.0 - validation_score, 2)

    if any(code.startswith("DUP-") for code in failed_codes):
        fallback_score = max(fallback_score, 78.0)
    elif any(code.startswith("ANO-") for code in failed_codes):
        fallback_score = max(fallback_score, 72.0)
    elif any(code.startswith("VAT-") for code in failed_codes):
        fallback_score = max(fallback_score, 58.0)

    return round(max(0.0, min(100.0, fallback_score)), 2)


def _merge_risk_assessment(invoice, validation_result, risk_result):
    risk_result = risk_result or {}
    fallback_score = _fallback_risk_score(validation_result)
    ai_score = max(0.0, min(100.0, _to_float(risk_result.get("overall_risk_score"), 0.0)))
    final_score = max(ai_score, fallback_score)
    final_level = _risk_level_from_score(final_score)

    invoice.risk_score = round(final_score, 2)
    invoice.risk_level = final_level
    invoice.ai_recommendations = risk_result.get("recommendations", [])
    if not invoice.ai_summary:
        invoice.ai_summary = str(risk_result.get("ai_summary", "") or "")

    invoice.is_duplicate = any(
        code in validation_result.get("failed_rule_codes", []) for code in ["DUP-001", "DUP-002", "DUP-003", "DUP-004"]
    )
    if invoice.status not in [Invoice.Status.APPROVED, Invoice.Status.REJECTED]:
        invoice.status = Invoice.Status.FLAGGED if invoice.risk_score >= 70 else Invoice.Status.VALIDATED

    return {
        "overall_risk_score": invoice.risk_score,
        "risk_level": invoice.risk_level,
        "recommendations": invoice.ai_recommendations,
        "ai_summary": invoice.ai_summary,
    }


REVIEW_FIELD_META = [
    ("vendor_name", "اسم المورد", "text"),
    ("vendor_vat_number", "الرقم الضريبي للمورد", "text"),
    ("invoice_number", "رقم الفاتورة", "text"),
    ("invoice_date", "تاريخ الفاتورة", "date"),
    ("due_date", "تاريخ الاستحقاق", "date"),
    ("subtotal", "المجموع الفرعي", "amount"),
    ("vat_amount", "ضريبة القيمة", "amount"),
    ("total_amount", "الإجمالي النهائي", "amount"),
    ("currency", "العملة", "text"),
    ("customer_name", "اسم العميل", "text"),
    ("customer_vat_number", "الرقم الضريبي للعميل", "text"),
    ("cost_center", "مركز التكلفة", "text"),
    ("account_code", "رمز الحساب", "text"),
    ("budget_code", "رمز الميزانية", "text"),
]


def _serialize_review_value(value):
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def _coerce_review_value(field_name: str, raw_value):
    if raw_value in (None, ""):
        return None

    if field_name in {"invoice_date", "due_date"}:
        if hasattr(raw_value, "isoformat"):
            return raw_value
        parsed = parse_date(str(raw_value).strip())
        if parsed:
            return parsed
        for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y"):
            try:
                return datetime.strptime(str(raw_value).strip(), fmt).date()
            except ValueError:
                continue
        raise ValueError(f"Invalid date for {field_name}.")

    if field_name in {"subtotal", "vat_amount", "total_amount"}:
        try:
            return Decimal(str(raw_value).replace(",", "").strip())
        except (InvalidOperation, ValueError, TypeError, AttributeError) as exc:
            raise ValueError(f"Invalid amount for {field_name}.") from exc

    value = str(raw_value).strip()
    return value or None


def _build_review_payload(invoice):
    extracted = dict(invoice.extracted_data or {})
    normalized = dict(extracted.get("normalized") or {})
    manual_review = dict(extracted.get("review") or {})
    manual_corrections = dict(manual_review.get("corrections") or {})
    ai_payload = {
        key: value
        for key, value in extracted.items()
        if key not in {"normalized", "review"} and not str(key).startswith("_")
    }

    field_rows = []
    for field_name, label, field_type in REVIEW_FIELD_META:
        field_rows.append(
            {
                "field": field_name,
                "label": label,
                "type": field_type,
                "current": _serialize_review_value(getattr(invoice, field_name, "")),
                "normalized": _serialize_review_value(normalized.get(field_name)),
                "ai": _serialize_review_value(ai_payload.get(field_name)),
                "manual": _serialize_review_value(manual_corrections.get(field_name)),
            }
        )

    review_events = invoice.audit_events.filter(
        event_type=InvoiceAuditEvent.EventType.EDITED,
        description__icontains="Manual review",
    ).order_by("-timestamp")

    return {
        "fields": field_rows,
        "raw_text": invoice.raw_text or "",
        "normalized": normalized,
        "ai_extracted": ai_payload,
        "manual_review": manual_review,
        "manual_corrections": manual_corrections,
        "last_review_event": InvoiceAuditEventSerializer(review_events.first()).data if review_events.exists() else None,
    }


def _run_invoice_revalidation(invoice, acting_user, request=None):
    file_hash = (invoice.extracted_data or {}).get("file_hash", "")
    validation_result = run_all_rules(
        invoice,
        organization=invoice.organization,
        file_hash=file_hash,
    )
    validation_result = ValidationPipelineService.persist_validation_result(
        invoice=invoice,
        validation_result=validation_result,
        created_by=acting_user,
    )
    risk_result = {}
    try:
        risk_result = analyze_invoice_risk(
            invoice.extracted_data or {},
            _get_vendor_history(invoice.organization, invoice.vendor_name),
        )
    except Exception as exc:
        logger.warning("AI risk re-analysis failed during manual review: %s", exc)

    _merge_risk_assessment(invoice, validation_result, risk_result)
    invoice.save(update_fields=["risk_score", "risk_level", "ai_recommendations", "ai_summary", "is_duplicate", "status", "updated_at"])
    _save_audit_event(
        invoice,
        acting_user,
        InvoiceAuditEvent.EventType.REPROCESSED,
        f"Re-validated after manual review: score={validation_result['validation_score']}%",
        request=request,
    )
    return validation_result


def _process_single_file(file_obj, filename: str, org, user, batch=None, request=None, audit_session=None) -> dict:
    """
    Full invoice processing pipeline:
      1. Upload File        — save raw file, create Invoice record
      2. Document Engine    — MIME detection, route to correct parser
      3. File Parser        — PDF/Image/Excel/JSON/CSV parser
      4. OCR/Text Extract   — Tesseract (+ OpenAI OCR upgrade if confidence < 60%)
      5. OpenAI Extraction  — ZATCA-specific invoice field extraction (GPT-4o)
      6. Financial AI       — classify → dup → fraud → compliance → risk
      7. Audit Engine       — run 6 audit rules, persist AuditCase
      8. Risk Engine        — merge scores from val + AI → final risk level
      9. Save to DB         — update Invoice, InvoiceValidationResult, VendorProfile

    Returns:
        dict with invoice_id, validation, risk, errors.
    """
    from core.services.document_engine import DocumentEngine
    from core.services.financial_ai_engine import FinancialAIEngine
    from apps.audit.audit_engine import run_audit

    start = time.time()
    ext = os.path.splitext(filename)[1].lower()
    file_data = file_obj.read()
    file_obj.seek(0)

    # ── Step 1: Upload File — save raw bytes, create initial Invoice record ───
    file_hash = compute_file_hash(io.BytesIO(file_data))
    if audit_session:
        AuditSessionService.advance_to_extracting(audit_session)
        if AuditSessionService.has_file_hash(audit_session, file_hash):
            raise ValueError("Duplicate file already processed in this audit session.")

    invoice = Invoice.objects.create(
        organization=org,
        uploaded_by=user,
        audit_session=audit_session,
        batch=batch,
        file=ContentFile(file_data, name=filename),
        original_filename=filename,
        file_size=len(file_data),
        mime_type=file_obj.content_type if hasattr(file_obj, "content_type") else "",
        extracted_data={"file_hash": file_hash},
    )
    _save_audit_event(invoice, user, InvoiceAuditEvent.EventType.UPLOADED,
                      f"Uploaded: {filename}", request=request)

    file_path = invoice.file.path

    # ── Steps 2 & 3: Document Engine → File Parser ───────────────────────────
    # MIME detection → routes to PDF / Image / Excel / JSON / CSV parser
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

    # ── Step 4: OCR / Text Extraction (handled inside the parser) ────────────
    # image_parser:  Tesseract → OpenAI OCR upgrade when confidence < 60%
    # pdf_parser:    PyMuPDF page render → Tesseract → OpenAI OCR upgrade
    # excel_parser:  pandas direct extraction (no OCR needed)
    # json_parser:   direct text extraction (no OCR needed)
    raw_text = ingestion.raw_text
    ocr_confidence = float(ingestion.metadata.get("ocr_confidence", 0.0))

    _save_audit_event(invoice, user, InvoiceAuditEvent.EventType.PROCESSED,
                      f"Parser: {ingestion.extraction_method} | OCR confidence: {ocr_confidence:.0f}%",
                      request=request)

    # ── Step 5: OpenAI Extraction — ZATCA-specific invoice field extraction ───
    # For vision: images use file_path directly; PDFs render first page
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
    except Exception as e:
        logger.warning(f"OpenAI extraction failed for {filename}: {e}")
        from core.services.invoice_ai_service import _fallback_extraction
        ai_data = _fallback_extraction(raw_text)

    normalized_ingestion = ingestion.normalized or {}
    normalization = normalizer.normalize(
        {
            **normalized_ingestion,
            **(ingestion.structured or {}),
            **(ai_data or {}),
            "raw_text": raw_text,
            "extraction_method": ingestion.extraction_method,
            "language": ai_data.get("language") or normalized_ingestion.get("language") or ingestion.metadata.get("language", "unknown"),
        },
        default_currency=getattr(org, "currency", "SAR") or "SAR",
    )
    normalized = normalization.normalized_data
    serialized_normalized = normalization.to_serializable_dict()

    # Populate Invoice fields (normalized canonical data takes priority)
    def _safe_decimal(val):
        try:
            return Decimal(str(val)) if val else Decimal("0")
        except Exception:
            return Decimal("0")

    def _safe_date(val):
        if not val:
            return None
        try:
            from datetime import datetime
            for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y",
                        "%Y/%m/%d", "%d %b %Y", "%d %B %Y"):
                try:
                    return datetime.strptime(str(val), fmt).date()
                except ValueError:
                    continue
        except Exception:
            pass
        return None

    invoice.invoice_number    = str(_first_non_empty(normalized.get("invoice_number"), ai_data.get("invoice_number"), filename) or "")
    invoice.invoice_date      = _safe_date(normalized.get("invoice_date") or ai_data.get("invoice_date"))
    invoice.due_date          = _safe_date(normalized.get("due_date") or ai_data.get("due_date"))
    invoice.vendor_name       = str(_first_non_empty(
        normalized.get("vendor_name"), ai_data.get("vendor_name"), ai_data.get("vendor_name_ar"),
        ai_data.get("supplier_name"), ai_data.get("merchant_name"),
    ) or "")
    invoice.vendor_name_ar    = str(_first_non_empty(ai_data.get("vendor_name_ar"), ai_data.get("vendor_name")) or "")
    invoice.vendor_vat_number = str(normalized.get("vendor_vat_number") or ai_data.get("vendor_vat_number", "") or "")
    invoice.vendor_cr_number  = str(ai_data.get("vendor_cr_number", "") or "")
    invoice.vendor_address    = str(ai_data.get("vendor_address", "") or "")
    invoice.vendor_phone      = str(ai_data.get("vendor_phone", "") or "")
    invoice.customer_name     = str(normalized.get("customer_name") or ai_data.get("customer_name", "") or "")
    invoice.customer_vat_number = str(normalized.get("customer_vat_number") or ai_data.get("customer_vat_number", "") or "")
    invoice.currency          = str(normalized.get("currency") or ai_data.get("currency", "SAR") or "SAR")
    invoice.subtotal          = _safe_decimal(normalized.get("subtotal"))
    invoice.vat_rate          = _safe_decimal(normalized.get("vat_rate", 15))
    invoice.vat_amount        = _safe_decimal(normalized.get("vat_amount"))
    invoice.discount          = _safe_decimal(normalized.get("discount"))
    invoice.total_amount      = _safe_decimal(normalized.get("total_amount"))
    invoice.line_items        = serialized_normalized.get("line_items") or ai_data.get("line_items", [])
    invoice.has_qr_code       = bool(normalized.get("has_qr_code", False))
    invoice.qr_code_valid     = bool(ai_data.get("qr_code_valid", False))
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
    invoice.status            = Invoice.Status.PROCESSING
    invoice.save()

    # ── Step 6: Financial AI Engine ──────────────────────────────────────────
    # classify → field extract → duplicate detection → fraud detection
    # → ZATCA compliance → Risk Engine (internal final step)
    ai_engine = FinancialAIEngine(organization_id=org.id, country_code="SA", use_ai=True)
    analysis = ai_engine.analyse(ingestion)

    # ── Step 7: Audit Engine — 6 structural audit rules + AuditCase persist ───
    try:
        run_audit(
            analysis.to_dict(),
            organization_id=org.id,
            invoice_id=invoice.id,
            persist=True,
        )
    except Exception as e:
        logger.warning(f"Audit engine failed for {filename}: {e}")

    # ── Also run 30 ZATCA validation rules against the Invoice model fields ───
    if audit_session:
        AuditSessionService.advance_to_validating(audit_session)
    val_result = ValidationPipelineService.validate_invoice(
        invoice=invoice,
        organization=org,
        file_hash=file_hash,
        created_by=user,
    )

    _save_audit_event(invoice, user, InvoiceAuditEvent.EventType.VALIDATED,
                      f"Validation: {val_result['validation_score']:.0f}% | Failed: {val_result['failed_rule_codes']}",
                      request=request)

    # ── Step 8: Risk Engine — merge validation + AI scores → final risk level ─
    # analyze_invoice_risk provides vendor-history-aware risk from invoice_ai_service
    # FinancialAIEngine already ran its own Risk Engine; we take the max score
    vendor_hist = _get_vendor_history(org, invoice.vendor_name)
    try:
        ai_risk = analyze_invoice_risk({k: v for k, v in invoice.extracted_data.items() if not k.startswith("_")}, vendor_hist)
    except Exception as e:
        logger.warning(f"AI risk analysis failed for {filename}: {e}")
        ai_risk = {}

    # Final score = max(Financial AI risk, invoice AI risk, fallback from val rules)
    ai_risk["overall_risk_score"] = max(
        _to_float(ai_risk.get("overall_risk_score"), 0.0),
        float(analysis.risk_score),
    )
    _merge_risk_assessment(invoice, val_result, ai_risk)

    # ── Step 9: Save to DB ────────────────────────────────────────────────────
    invoice.is_duplicate = invoice.is_duplicate or analysis.is_duplicate
    invoice.save()

    _update_vendor_profile(org, invoice)

    elapsed_ms = int((time.time() - start) * 1000)
    logger.info(
        "[Upload] %s | risk=%s | score=%.0f%% | dup=%s | fraud=%.2f | %dms",
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


def _get_vendor_history(org, vendor_name: str) -> dict:
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


def _update_vendor_profile(org, invoice: Invoice):
    """Update or create vendor profile after processing an invoice."""
    if not invoice.vendor_name:
        return
    try:
        stats = Invoice.objects.filter(
            organization=org, vendor_name=invoice.vendor_name
        ).aggregate(
            cnt=Count("id"),
            total=Sum("total_amount"),
            avg=Avg("total_amount"),
            max_a=Max("total_amount"),
            flagged=Count("id", filter=Q(risk_level__in=["high", "critical"])),
            dups=Count("id", filter=Q(is_duplicate=True)),
        )
        vp, _ = VendorProfile.objects.update_or_create(
            organization=org,
            vendor_name=invoice.vendor_name,
            defaults={
                "vendor_vat_number": invoice.vendor_vat_number or "",
                "invoice_count":    stats["cnt"] or 0,
                "total_amount":     stats["total"] or 0,
                "avg_invoice_amount": stats["avg"] or 0,
                "max_invoice_amount": stats["max_a"] or 0,
                "flagged_count":    stats["flagged"] or 0,
                "duplicate_count":  stats["dups"] or 0,
                "is_new":           (stats["cnt"] or 0) <= 1,
                "last_seen":        invoice.invoice_date or date.today(),
            }
        )
        if not vp.first_seen:
            vp.first_seen = invoice.invoice_date or date.today()
            vp.save(update_fields=["first_seen"])
    except Exception as e:
        logger.warning(f"Vendor profile update failed: {e}")


def _handle_processing_result(result: dict, filename: str, batch, results: list, errors: list, audit_session=None):
    if result.get("success"):
        results.append(result)
        batch.processed_files += 1
        return

    message = result.get("error") or "Processing failed"
    errors.append({"filename": filename, "error": message})
    batch.failed_files += 1
    if audit_session:
        AuditSessionService.record_failure(audit_session, message)


# ─── Views ────────────────────────────────────────────────────────────────────

class InvoiceUploadView(APIView):
    """
    Upload invoices for auditing.

    Supports:
    - Single file (PDF / JPG / PNG / TIFF)
    - Multiple files (multipart with multiple 'files' fields)
    - ZIP archive (contains multiple invoice files)
    """
    parser_classes = [MultiPartParser, FormParser]
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Invoices"],
        summary="Upload one or more invoices (PDF/image/ZIP) — runs all 30 audit rules",
        request={"type": "object", "properties": {
            "files": {"type": "array", "items": {"type": "string", "format": "binary"},
                      "description": "One or more invoice files (PDF, JPG, PNG, TIFF, or ZIP)"},
            "batch_name": {"type": "string"},
        }},
    )
    def post(self, request):
        org = request.user.organization
        if not org:
            return Response({"error": "User has no organization."}, status=400)

        uploaded_files = request.FILES.getlist("files")
        if not uploaded_files:
            # Try single file key
            single = request.FILES.get("file")
            if single:
                uploaded_files = [single]
            else:
                return Response({"error": "No files uploaded. Use 'files' or 'file' field."}, status=400)

        batch_name = request.data.get("batch_name", f"Batch {timezone.now().strftime('%Y-%m-%d %H:%M')}")

        # Create batch
        batch = InvoiceBatch.objects.create(
            organization=org,
            uploaded_by=request.user,
            batch_name=batch_name,
            total_files=len(uploaded_files),
        )
        audit_session = AuditSessionService.create_session(
            organization=org,
            created_by=request.user,
            name=batch_name,
            total_count=len(uploaded_files),
            context={"source": "invoice_upload"},
        )
        batch.audit_session = audit_session
        batch.save(update_fields=["audit_session"])

        results = []
        errors  = []

        for uploaded_file in uploaded_files:
            filename = uploaded_file.name
            ext = os.path.splitext(filename)[1].lower()

            if ext not in ALLOWED_EXT:
                errors.append({"filename": filename, "error": f"Unsupported file type: {ext}"})
                batch.failed_files += 1
                AuditSessionService.record_failure(audit_session, f"Unsupported file type: {ext}")
                continue

            # ── ZIP: extract and process each file inside ─────────────────────
            if ext == ".zip":
                zip_results, zip_errors = _process_zip(uploaded_file, org, request.user, batch, request, audit_session)
                results.extend(zip_results)
                errors.extend(zip_errors)
                batch.total_files += len(zip_results) + len(zip_errors) - 1
                AuditSessionService.sync_expected_total(audit_session, batch.total_files)
            # ── CSV/TSV: process each row as a separate invoice ───────────────
            elif ext in {".csv", ".tsv"}:
                csv_results, csv_errors = _process_csv_rows(uploaded_file, filename, org, request.user, batch, request, audit_session)
                if csv_results or csv_errors:
                    results.extend(csv_results)
                    errors.extend(csv_errors)
                    batch.total_files += len(csv_results) + len(csv_errors) - 1
                    AuditSessionService.sync_expected_total(audit_session, batch.total_files)
                else:
                    try:
                        r = _process_single_file(uploaded_file, filename, org, request.user, batch, request, audit_session)
                        _handle_processing_result(r, filename, batch, results, errors, audit_session)
                    except Exception as e:
                        logger.error(f"Failed processing {filename}: {e}")
                        errors.append({"filename": filename, "error": str(e)})
                        batch.failed_files += 1
                        AuditSessionService.record_failure(audit_session, str(e))
            # ── JSON array: process each dict as a separate invoice ────────────
            elif ext == ".json":
                json_results, json_errors = _process_json_list(uploaded_file, filename, org, request.user, batch, request, audit_session)
                if json_results or json_errors:
                    results.extend(json_results)
                    errors.extend(json_errors)
                    batch.total_files += len(json_results) + len(json_errors) - 1
                    AuditSessionService.sync_expected_total(audit_session, batch.total_files)
                else:
                    # Not a list — process as single file
                    try:
                        r = _process_single_file(uploaded_file, filename, org, request.user, batch, request, audit_session)
                        _handle_processing_result(r, filename, batch, results, errors, audit_session)
                    except Exception as e:
                        logger.error(f"Failed processing {filename}: {e}")
                        errors.append({"filename": filename, "error": str(e)})
                        batch.failed_files += 1
                        AuditSessionService.record_failure(audit_session, str(e))
            else:
                try:
                    r = _process_single_file(uploaded_file, filename, org, request.user, batch, request, audit_session)
                    _handle_processing_result(r, filename, batch, results, errors, audit_session)
                except Exception as e:
                    logger.error(f"Failed processing {filename}: {e}")
                    errors.append({"filename": filename, "error": str(e)})
                    batch.failed_files += 1
                    AuditSessionService.record_failure(audit_session, str(e))

        # Finalize batch
        batch.status = (
            InvoiceBatch.BatchStatus.COMPLETED  if not errors else
            InvoiceBatch.BatchStatus.PARTIAL    if results else
            InvoiceBatch.BatchStatus.FAILED
        )
        batch.completed_at = timezone.now()
        batch.processing_log = results + errors
        batch.save()
        AuditSessionService.sync_expected_total(audit_session, batch.total_files)
        AuditSessionService.finalize_if_ready(audit_session)

        log_action(request, AuditLog.Action.DOCUMENT_UPLOAD, "invoice_batch", str(batch.id),
                   {"files": len(results), "errors": len(errors)})

        return Response({
            "batch_id":      str(batch.id),
            "audit_session_id": str(audit_session.id),
            "batch_name":    batch_name,
            "total_files":   len(results) + len(errors),
            "processed":     len(results),
            "failed":        len(errors),
            "status":        batch.status,
            "results":       results,
            "errors":        errors,
        }, status=status.HTTP_201_CREATED)


def _process_zip(zip_file, org, user, batch, request, audit_session=None) -> tuple[list, list]:
    """Extract and process all invoice files inside a ZIP archive."""
    results, errors = [], []
    try:
        with zipfile.ZipFile(io.BytesIO(zip_file.read()), "r") as zf:
            for member in zf.infolist():
                if member.is_dir():
                    continue
                name = os.path.basename(member.filename)
                ext = os.path.splitext(name)[1].lower()
                if ext not in {".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".xlsx", ".xls", ".json"}:
                    continue
                try:
                    data = zf.read(member)
                    file_like = io.BytesIO(data)
                    file_like.name = name
                    file_like.content_type = _guess_mime(ext)
                    r = _process_single_file(file_like, name, org, user, batch, request, audit_session)
                    _handle_processing_result(r, name, batch, results, errors, audit_session)
                except Exception as e:
                    logger.error(f"ZIP member {name} failed: {e}")
                    errors.append({"filename": name, "error": str(e)})
                    batch.failed_files += 1
                    if audit_session:
                        AuditSessionService.record_failure(audit_session, str(e))
    except zipfile.BadZipFile:
        errors.append({"filename": zip_file.name, "error": "Invalid ZIP file"})
        if audit_session:
            AuditSessionService.record_failure(audit_session, "Invalid ZIP file")
    return results, errors


def _process_csv_rows(csv_file, filename: str, org, user, batch, request, audit_session=None) -> tuple[list, list]:
    """
    Parse a CSV/TSV file and process each row as a separate invoice.
    Returns (results, errors). Returns ([], []) if the file has ≤1 data row (caller handles as single).
    """
    results, errors = [], []
    try:
        import pandas as pd
        raw = csv_file.read()
        csv_file.seek(0)

        # Detect delimiter
        sample = raw[:4096].decode("utf-8", errors="replace")
        delimiter = max({",": sample.count(","), ";": sample.count(";"),
                         "\t": sample.count("\t"), "|": sample.count("|")},
                        key=lambda k: {",": sample.count(","), ";": sample.count(";"),
                                       "\t": sample.count("\t"), "|": sample.count("|")}[k])

        df = pd.read_csv(
            io.BytesIO(raw), sep=delimiter, dtype=str,
            keep_default_na=False, on_bad_lines="skip",
            encoding="utf-8-sig",
        )
        df = df.dropna(how="all")

        if len(df) <= 1:
            return [], []  # Single row — caller processes as one file

    except Exception as e:
        logger.warning(f"CSV pre-parse failed for {filename}: {e}")
        return [], []

    base_name = os.path.splitext(filename)[0]
    for idx, row in df.iterrows():
        row_dict = {k: v for k, v in row.items() if str(v).strip()}
        if not row_dict:
            continue
        row_name = f"{base_name}_row{idx + 1}.json"
        item_bytes = __import__("json").dumps(row_dict, ensure_ascii=False).encode("utf-8")
        file_like = io.BytesIO(item_bytes)
        file_like.name = row_name
        file_like.content_type = "application/json"
        try:
            r = _process_single_file(file_like, row_name, org, user, batch, request, audit_session)
            _handle_processing_result(r, row_name, batch, results, errors, audit_session)
        except Exception as e:
            logger.error(f"CSV row {row_name} failed: {e}")
            errors.append({"filename": row_name, "error": str(e)})
            batch.failed_files += 1
            if audit_session:
                AuditSessionService.record_failure(audit_session, str(e))

    return results, errors


def _process_json_list(json_file, filename: str, org, user, batch, request, audit_session=None) -> tuple[list, list]:
    """
    If a JSON file contains a list[dict], process each dict as a separate invoice.
    Returns (results, errors). Returns ([], []) if the JSON is NOT a list (caller handles it).
    """
    import json as _json
    results, errors = [], []
    try:
        raw = json_file.read()
        json_file.seek(0)
        data = _json.loads(raw.decode("utf-8", errors="replace").lstrip("\xef\xbb\xbf"))
    except Exception:
        return [], []

    if not isinstance(data, list):
        return [], []  # Not a list — caller will process as single file

    base_name = os.path.splitext(filename)[0]
    for idx, item in enumerate(data):
        if not isinstance(item, dict):
            continue
        item_name = f"{base_name}_item{idx + 1}.json"
        item_bytes = _json.dumps(item, ensure_ascii=False).encode("utf-8")
        file_like = io.BytesIO(item_bytes)
        file_like.name = item_name
        file_like.content_type = "application/json"
        try:
            r = _process_single_file(file_like, item_name, org, user, batch, request, audit_session)
            _handle_processing_result(r, item_name, batch, results, errors, audit_session)
        except Exception as e:
            logger.error(f"JSON item {item_name} failed: {e}")
            errors.append({"filename": item_name, "error": str(e)})
            batch.failed_files += 1
            if audit_session:
                AuditSessionService.record_failure(audit_session, str(e))

    return results, errors


def _guess_mime(ext: str) -> str:
    return {
        "pdf": "application/pdf", "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "png": "image/png", "tiff": "image/tiff", "tif": "image/tiff",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "xls": "application/vnd.ms-excel", "json": "application/json",
    }.get(ext.lstrip("."), "application/octet-stream")


class InvoiceListView(generics.ListAPIView):
    serializer_class = InvoiceListSerializer
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Invoices"],
        summary="List all invoices for the organization",
        parameters=[
            OpenApiParameter("status",       description="Filter by status"),
            OpenApiParameter("risk_level",   description="Filter by risk level"),
            OpenApiParameter("vendor_name",  description="Filter by vendor name"),
            OpenApiParameter("is_duplicate", type=bool),
            OpenApiParameter("date_from"),
            OpenApiParameter("date_to"),
            OpenApiParameter("min_amount",   type=float),
            OpenApiParameter("max_amount",   type=float),
            OpenApiParameter("search",       description="Search vendor/invoice number/notes"),
            OpenApiParameter("batch_id",     description="Filter by batch ID"),
        ],
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        qs = Invoice.objects.filter(organization=self.request.user.organization).select_related(
            "uploaded_by", "approved_by", "batch"
        )
        p = self.request.query_params
        if v := p.get("status"):        qs = qs.filter(status=v)
        if v := p.get("risk_level"):    qs = qs.filter(risk_level=v)
        if v := p.get("vendor_name"):   qs = qs.filter(vendor_name__icontains=v)
        if v := p.get("is_duplicate"):  qs = qs.filter(is_duplicate=v.lower() == "true")
        if v := p.get("date_from"):     qs = qs.filter(invoice_date__gte=v)
        if v := p.get("date_to"):       qs = qs.filter(invoice_date__lte=v)
        if v := p.get("min_amount"):    qs = qs.filter(total_amount__gte=v)
        if v := p.get("max_amount"):    qs = qs.filter(total_amount__lte=v)
        if v := p.get("batch_id") or p.get("batch"):
            qs = qs.filter(batch_id=v)
        if v := p.get("search"):
            qs = qs.filter(
                Q(vendor_name__icontains=v) | Q(invoice_number__icontains=v) |
                Q(notes__icontains=v) | Q(vendor_vat_number__icontains=v)
            )
        return qs.order_by("-created_at")


class InvoiceDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = InvoiceDetailSerializer
    permission_classes = [IsAuthenticated, IsOwnOrganization]
    authentication_classes = [JWTAuthentication, SessionAuthentication]

    @extend_schema(tags=["Invoices"], summary="Get full invoice details with validation results")
    def get(self, request, *args, **kwargs):
        invoice = self.get_object()
        if request.path.startswith("/invoices/") and "sessionid" in request.COOKIES:
            from apps.frontend.page_views import _build_invoice_display, _ctx

            audit_trail = invoice.audit_events.select_related("user").order_by("-timestamp")[:40]
            return render(
                request._request,
                "invoices/detail_premium.html",
                _ctx(
                    request._request,
                    "invoices",
                    invoice=invoice,
                    invoice_display=_build_invoice_display(invoice),
                    audit_trail=audit_trail,
                ),
            )

        data = InvoiceDetailSerializer(invoice).data
        try:
            data["validation"] = InvoiceValidationResultSerializer(invoice.validation).data
        except InvoiceValidationResult.DoesNotExist:
            data["validation"] = None
        data["findings"] = AuditFindingSerializer(
            invoice.audit_findings.order_by("-last_detected_at")[:20],
            many=True,
        ).data
        data["audit_trail"] = list(
            invoice.audit_events.order_by("-timestamp").values(
                "event_type", "description", "timestamp", "user__full_name", "ip_address"
            )[:20]
        )
        data["review"] = _build_review_payload(invoice)
        return Response(data)

    def perform_update(self, serializer):
        invoice = self.get_object()
        if invoice.status == Invoice.Status.APPROVED:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Cannot edit an approved invoice. (Rule CTL-004)")
        before = InvoiceDetailSerializer(invoice).data
        updated = serializer.save()
        _save_audit_event(updated, self.request.user, InvoiceAuditEvent.EventType.EDITED,
                          "Invoice fields updated", before=before,
                          after=InvoiceDetailSerializer(updated).data,
                          request=self.request)

    def get_queryset(self):
        return Invoice.objects.filter(organization=self.request.user.organization).select_related(
            "validation",
            "approved_by",
            "duplicate_of",
        )


class InvoiceApproveView(APIView):
    """Approve or reject an invoice (Rule CTL-005: must have approver)."""
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    @extend_schema(
        tags=["Invoices"],
        summary="Approve or reject an invoice",
        request={"type": "object", "properties": {
            "action": {"type": "string", "enum": ["approve", "reject"]},
            "reason": {"type": "string", "description": "Required for rejection"},
        }},
    )
    def post(self, request, pk):
        try:
            invoice = Invoice.objects.get(pk=pk, organization=request.user.organization)
        except Invoice.DoesNotExist:
            return Response({"error": "Invoice not found."}, status=404)

        action = request.data.get("action")
        if action not in ("approve", "reject"):
            return Response({"error": "action must be 'approve' or 'reject'"}, status=400)

        before = {"status": invoice.status}

        if action == "approve":
            invoice.status      = Invoice.Status.APPROVED
            invoice.approved_by = request.user
            invoice.approved_at = timezone.now()
            event_type          = InvoiceAuditEvent.EventType.APPROVED
            msg                 = f"Approved by {request.user.full_name}"
        else:
            reason = request.data.get("reason", "")
            if not reason:
                return Response({"error": "reason is required for rejection."}, status=400)
            invoice.status          = Invoice.Status.REJECTED
            invoice.rejected_reason = reason
            event_type              = InvoiceAuditEvent.EventType.REJECTED
            msg                     = f"Rejected: {reason}"

        invoice.save()
        _save_audit_event(invoice, request.user, event_type, msg,
                          before=before, after={"status": invoice.status}, request=request)

        return Response({"invoice_id": str(invoice.id), "status": invoice.status, "message": msg})


class InvoiceRevalidateView(APIView):
    """Re-run all 30 validation rules on an existing invoice."""
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Invoices"], summary="Re-run all 30 validation rules on an existing invoice")
    def post(self, request, pk):
        try:
            invoice = Invoice.objects.get(pk=pk, organization=request.user.organization)
        except Invoice.DoesNotExist:
            return Response({"error": "Invoice not found."}, status=404)
        val_result = _run_invoice_revalidation(invoice, request.user, request=request)
        return Response(val_result)


class InvoiceManualReviewView(APIView):
    """Persist reviewer corrections and optional revalidation for an invoice."""

    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]
    authentication_classes = [JWTAuthentication, SessionAuthentication]

    @extend_schema(
        tags=["Invoices"],
        summary="Save manual review corrections for an invoice",
        request={
            "type": "object",
            "properties": {
                "corrections": {"type": "object"},
                "note": {"type": "string"},
                "revalidate": {"type": "boolean"},
            },
        },
    )
    def post(self, request, pk):
        try:
            invoice = Invoice.objects.get(pk=pk, organization=request.user.organization)
        except Invoice.DoesNotExist:
            return Response({"error": "Invoice not found."}, status=404)

        corrections = request.data.get("corrections") or {}
        if not isinstance(corrections, dict):
            return Response({"error": "corrections must be an object."}, status=400)

        note = str(request.data.get("note", "") or "").strip()
        should_revalidate = bool(request.data.get("revalidate"))

        before = {field: _serialize_review_value(getattr(invoice, field, "")) for field, _, _ in REVIEW_FIELD_META}
        applied = {}
        validation_errors = {}

        for field_name, _, _ in REVIEW_FIELD_META:
            if field_name not in corrections:
                continue
            try:
                coerced_value = _coerce_review_value(field_name, corrections.get(field_name))
            except ValueError as exc:
                validation_errors[field_name] = str(exc)
                continue
            if coerced_value is None and field_name in {"invoice_date", "due_date"}:
                setattr(invoice, field_name, None)
            elif coerced_value is None and field_name in {"subtotal", "vat_amount", "total_amount"}:
                setattr(invoice, field_name, Decimal("0"))
            else:
                setattr(invoice, field_name, coerced_value if coerced_value is not None else "")
            applied[field_name] = _serialize_review_value(coerced_value)

        if validation_errors:
            return Response({"errors": validation_errors}, status=400)

        extracted_data = dict(invoice.extracted_data or {})
        extracted_data["review"] = {
            "corrections": {**(extracted_data.get("review", {}).get("corrections", {})), **applied},
            "note": note,
            "reviewed_by": str(request.user.id),
            "reviewed_by_name": request.user.full_name,
            "reviewed_at": timezone.now().isoformat(),
        }
        invoice.extracted_data = extracted_data
        update_fields = [field for field in applied] + ["extracted_data", "updated_at"]
        invoice.save(update_fields=list(dict.fromkeys(update_fields)))

        after = {field: _serialize_review_value(getattr(invoice, field, "")) for field, _, _ in REVIEW_FIELD_META}
        _save_audit_event(
            invoice,
            request.user,
            InvoiceAuditEvent.EventType.EDITED,
            "Manual review corrections applied",
            before=before,
            after={"fields": after, "note": note, "applied": applied},
            request=request,
        )

        validation_result = None
        if should_revalidate:
            validation_result = _run_invoice_revalidation(invoice, request.user, request=request)

        return Response(
            {
                "invoice_id": str(invoice.id),
                "status": invoice.status,
                "applied_fields": applied,
                "review": _build_review_payload(invoice),
                "validation": validation_result,
            }
        )


class InvoiceBatchListView(generics.ListAPIView):
    serializer_class = InvoiceBatchSerializer
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Invoices"], summary="List upload batches")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        return InvoiceBatch.objects.filter(organization=self.request.user.organization)


class InvoiceBatchDetailView(APIView):
    """Get batch details with all invoice summaries."""
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Invoices"], summary="Get batch details with invoice summaries")
    def get(self, request, pk):
        try:
            batch = InvoiceBatch.objects.get(pk=pk, organization=request.user.organization)
        except InvoiceBatch.DoesNotExist:
            return Response({"error": "Batch not found."}, status=404)

        invoices = Invoice.objects.filter(batch=batch).values(
            "id", "original_filename", "vendor_name", "total_amount", "currency",
            "invoice_date", "status", "risk_level", "is_duplicate", "ocr_confidence",
        )
        stats = Invoice.objects.filter(batch=batch).aggregate(
            total_amount=Sum("total_amount"),
            avg_score=Avg("ocr_confidence"),
            flagged=Count("id", filter=Q(status="flagged")),
            approved=Count("id", filter=Q(status="approved")),
            duplicates=Count("id", filter=Q(is_duplicate=True)),
            critical=Count("id", filter=Q(risk_level="critical")),
        )
        return Response({
            "batch": InvoiceBatchSerializer(batch).data,
            "audit_session_id": str(batch.audit_session_id) if batch.audit_session_id else None,
            "stats": stats,
            "invoices": list(invoices),
        })


# ─── Reports ─────────────────────────────────────────────────────────────────

class InvoiceRiskReportView(APIView):
    """Report: High-risk invoices."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Invoices"],
        summary="Risk report — flagged and high-risk invoices",
        parameters=[
            OpenApiParameter("date_from"), OpenApiParameter("date_to"),
            OpenApiParameter("risk_level", description="low|medium|high|critical"),
        ],
    )
    def get(self, request):
        org = request.user.organization
        qs = Invoice.objects.filter(organization=org)
        if v := request.query_params.get("date_from"):
            qs = qs.filter(invoice_date__gte=v)
        if v := request.query_params.get("date_to"):
            qs = qs.filter(invoice_date__lte=v)
        if v := request.query_params.get("risk_level"):
            qs = qs.filter(risk_level=v)
        else:
            qs = qs.filter(risk_level__in=["high", "critical"])

        invoices = qs.order_by("-risk_score").values(
            "id", "invoice_number", "vendor_name", "total_amount", "currency",
            "invoice_date", "risk_level", "risk_score", "ai_summary",
            "is_duplicate", "status", "ai_recommendations",
        )
        stats = qs.aggregate(
            count=Count("id"), total=Sum("total_amount"), avg_risk=Avg("risk_score")
        )
        return Response({
            "report_type": "risk_report",
            "generated_at": timezone.now().isoformat(),
            "stats": stats,
            "invoices": list(invoices),
        })


class DuplicateInvoiceReportView(APIView):
    """Report: Duplicate invoices."""
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Invoices"], summary="Duplicate invoices report")
    def get(self, request):
        org = request.user.organization
        qs = Invoice.objects.filter(organization=org, is_duplicate=True).order_by("-created_at")
        invoices = qs.values(
            "id", "invoice_number", "vendor_name", "total_amount", "currency",
            "invoice_date", "status", "duplicate_of_id", "created_at",
        )
        return Response({
            "report_type": "duplicate_report",
            "generated_at": timezone.now().isoformat(),
            "total_duplicates": qs.count(),
            "invoices": list(invoices),
        })


class VendorRiskReportView(APIView):
    """Report: Vendor risk analysis."""
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Invoices"], summary="Vendor risk analysis report")
    def get(self, request):
        org = request.user.organization
        vendors = VendorProfile.objects.filter(organization=org).order_by("-total_amount")
        return Response({
            "report_type": "vendor_risk_report",
            "generated_at": timezone.now().isoformat(),
            "vendors": VendorProfileSerializer(vendors, many=True).data,
        })


class VendorListView(APIView):
    """Compatibility vendor list endpoint for dashboard consumers."""

    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Invoices"], summary="List vendor profiles for the current organization")
    def get(self, request):
        org = request.user.organization
        if not org:
            return Response({"count": 0, "results": []})

        vendors = VendorProfile.objects.filter(organization=org).order_by("-total_amount", "vendor_name")
        if search := request.query_params.get("search"):
            vendors = vendors.filter(vendor_name__icontains=search)
        return Response({"count": vendors.count(), "results": VendorProfileSerializer(vendors[:100], many=True).data})


class SpendAnalysisReportView(APIView):
    """Report: Spend analysis by vendor and category."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Invoices"],
        summary="Spend analysis report",
        parameters=[
            OpenApiParameter("date_from"), OpenApiParameter("date_to"),
        ],
    )
    def get(self, request):
        org = request.user.organization
        qs = Invoice.objects.filter(organization=org)
        if v := request.query_params.get("date_from"):
            qs = qs.filter(invoice_date__gte=v)
        if v := request.query_params.get("date_to"):
            qs = qs.filter(invoice_date__lte=v)

        # By vendor
        by_vendor = qs.values("vendor_name").annotate(
            total=Sum("total_amount"), count=Count("id"),
            avg=Avg("total_amount"), flagged=Count("id", filter=Q(is_duplicate=True)),
        ).order_by("-total")[:20]

        # By currency
        by_currency = qs.values("currency").annotate(
            total=Sum("total_amount"), count=Count("id"),
        ).order_by("-total")

        # Monthly trend
        from django.db.models.functions import TruncMonth
        monthly = qs.annotate(month=TruncMonth("invoice_date")).values("month").annotate(
            total=Sum("total_amount"), count=Count("id"),
            flagged=Count("id", filter=Q(risk_level__in=["high", "critical"])),
        ).order_by("month")

        # Overall stats
        stats = qs.aggregate(
            grand_total=Sum("total_amount"),
            total_vat=Sum("vat_amount"),
            total_invoices=Count("id"),
            avg_invoice=Avg("total_amount"),
            flagged_total=Sum("total_amount", filter=Q(risk_level__in=["high","critical"])),
        )

        return Response({
            "report_type": "spend_analysis",
            "generated_at": timezone.now().isoformat(),
            "overall": stats,
            "by_vendor": list(by_vendor),
            "by_currency": list(by_currency),
            "monthly_trend": [
                {**m, "month": str(m["month"])[:7] if m["month"] else None}
                for m in monthly
            ],
        })


class ValidationRulesListView(APIView):
    """List all 30 validation rules with descriptions."""
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Invoices"], summary="List all 30 invoice audit rules")
    def get(self, request):
        groups = {
            "Group 1 — Invoice Validation": {k: v for k, v in RULES.items() if k.startswith("INV")},
            "Group 2 — Duplicate Detection": {k: v for k, v in RULES.items() if k.startswith("DUP")},
            "Group 3 — VAT Validation": {k: v for k, v in RULES.items() if k.startswith("VAT")},
            "Group 4 — Anomaly Detection": {k: v for k, v in RULES.items() if k.startswith("ANO")},
            "Group 5 — Financial Controls": {k: v for k, v in RULES.items() if k.startswith("CTL")},
            "Group 6 — Document Quality": {k: v for k, v in RULES.items() if k.startswith("DOC")},
        }
        return Response({"total_rules": TOTAL_RULES, "rule_groups": groups})
