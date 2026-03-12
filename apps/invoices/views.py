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
from datetime import date
from decimal import Decimal

from django.core.files.base import ContentFile
from django.db.models import Avg, Count, Max, Min, Q, Sum
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authentication.permissions import IsSeniorAuditorOrAbove, IsOwnOrganization
from core.services.invoice_ai_service import analyze_invoice_risk, extract_invoice_with_ai
from core.services.invoice_validator import RULES, TOTAL_RULES, compute_file_hash, run_all_rules
from core.services.ocr_service import extract_text_tesseract, pdf_to_images
from core.utils.audit import log_action
from apps.authentication.models import AuditLog

from .models import (
    Invoice, InvoiceAuditEvent, InvoiceBatch, InvoiceValidationResult, VendorProfile
)
from .serializers import (
    InvoiceBatchSerializer, InvoiceDetailSerializer,
    InvoiceListSerializer, InvoiceValidationResultSerializer,
    VendorProfileSerializer,
)

logger = logging.getLogger("finai")

ALLOWED_MIME = {"application/pdf", "image/jpeg", "image/png", "image/tiff",
                "application/zip", "application/x-zip-compressed"}
ALLOWED_EXT  = {".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".zip"}


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


def _process_single_file(file_obj, filename: str, org, user, batch=None, request=None) -> dict:
    """
    Full pipeline for one file:
      1. OCR with Tesseract
      2. AI extraction with OpenAI
      3. Save Invoice record
      4. Run 30 validation rules
      5. AI risk analysis
      6. Update vendor profile

    Returns:
        dict with invoice_id, validation, risk, errors.
    """
    start = time.time()
    ext = os.path.splitext(filename)[1].lower()
    file_data = file_obj.read()
    file_obj.seek(0)

    # Compute hash for duplicate detection
    file_hash = compute_file_hash(io.BytesIO(file_data))

    # Create invoice record (initial)
    invoice = Invoice.objects.create(
        organization=org,
        uploaded_by=user,
        batch=batch,
        file=ContentFile(file_data, name=filename),
        original_filename=filename,
        file_size=len(file_data),
        mime_type=file_obj.content_type if hasattr(file_obj, "content_type") else "",
        extracted_data={"file_hash": file_hash},
    )

    _save_audit_event(invoice, user, InvoiceAuditEvent.EventType.UPLOADED,
                      f"Uploaded file: {filename}", request=request)

    # ── Step 1: OCR ──────────────────────────────────────────────────────────
    raw_text = ""
    ocr_confidence = 0.0
    image_paths = []

    try:
        tmp_path = invoice.file.path

        if ext == ".pdf":
            image_paths = pdf_to_images(tmp_path)
            img_for_ai = image_paths[0] if image_paths else tmp_path
        else:
            img_for_ai = tmp_path
            image_paths = [tmp_path]

        tess_result = extract_text_tesseract(image_paths[0])
        raw_text = tess_result.get("text", "")
        ocr_confidence = tess_result.get("confidence", 0.0)

    except Exception as e:
        logger.warning(f"Tesseract OCR failed for {filename}: {e}")
        img_for_ai = invoice.file.path
        raw_text = ""

    # ── Step 2: AI Extraction (OpenAI) ───────────────────────────────────────
    try:
        ai_data = extract_invoice_with_ai(img_for_ai, raw_text)
    except Exception as e:
        logger.warning(f"AI extraction failed for {filename}: {e}")
        from core.services.invoice_ai_service import _fallback_extraction
        ai_data = _fallback_extraction(raw_text)

    # ── Step 3: Populate Invoice from extracted data ──────────────────────────
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
            for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y"):
                try:
                    return datetime.strptime(str(val), fmt).date()
                except ValueError:
                    continue
        except Exception:
            return None

    invoice.invoice_number    = str(_first_non_empty(ai_data.get("invoice_number"), filename) or "")
    invoice.invoice_date      = _safe_date(ai_data.get("invoice_date"))
    invoice.due_date          = _safe_date(ai_data.get("due_date"))
    invoice.vendor_name       = str(_first_non_empty(
        ai_data.get("vendor_name"),
        ai_data.get("vendor_name_ar"),
        ai_data.get("supplier_name"),
        ai_data.get("merchant_name"),
    ) or "")
    invoice.vendor_name_ar    = str(_first_non_empty(ai_data.get("vendor_name_ar"), ai_data.get("vendor_name")) or "")
    invoice.vendor_vat_number = str(ai_data.get("vendor_vat_number", "") or "")
    invoice.vendor_cr_number  = str(ai_data.get("vendor_cr_number", "") or "")
    invoice.vendor_address    = str(ai_data.get("vendor_address", "") or "")
    invoice.vendor_phone      = str(ai_data.get("vendor_phone", "") or "")
    invoice.customer_name     = str(ai_data.get("customer_name", "") or "")
    invoice.customer_vat_number = str(ai_data.get("customer_vat_number", "") or "")
    invoice.currency          = str(ai_data.get("currency", "SAR") or "SAR")
    invoice.subtotal          = _safe_decimal(ai_data.get("subtotal", 0))
    invoice.vat_rate          = _safe_decimal(ai_data.get("vat_rate", 15))
    invoice.vat_amount        = _safe_decimal(ai_data.get("vat_amount", 0))
    invoice.discount          = _safe_decimal(ai_data.get("discount", 0))
    invoice.total_amount      = _safe_decimal(ai_data.get("total_amount", 0))
    invoice.line_items        = ai_data.get("line_items", [])
    invoice.has_qr_code       = bool(ai_data.get("has_qr_code", False))
    invoice.qr_code_valid     = bool(ai_data.get("qr_code_valid", False))
    invoice.is_handwritten    = bool(ai_data.get("is_handwritten", False))
    invoice.is_clear          = bool(ai_data.get("is_clear", True))
    invoice.has_alterations   = bool(ai_data.get("has_alterations", False))
    invoice.language          = str(ai_data.get("language", "unknown"))
    invoice.raw_text          = raw_text
    invoice.ocr_confidence    = ocr_confidence
    invoice.ai_summary        = str(ai_data.get("ai_summary", ""))
    invoice.extracted_data    = {**ai_data, "file_hash": file_hash}
    invoice.status            = Invoice.Status.PROCESSING
    invoice.save()

    _save_audit_event(invoice, user, InvoiceAuditEvent.EventType.PROCESSED,
                      f"OCR confidence: {ocr_confidence:.0f}% | AI extraction: {ai_data.get('_extraction_method','unknown')}",
                      request=request)

    # ── Step 4: Run all 30 validation rules ───────────────────────────────────
    val_result = run_all_rules(invoice, organization=org, file_hash=file_hash)

    # Save validation result
    vr, _ = InvoiceValidationResult.objects.update_or_create(
        invoice=invoice,
        defaults={
            "has_invoice_number":       "INV-001" in val_result["passed_rule_codes"],
            "has_invoice_date":         "INV-002" in val_result["passed_rule_codes"],
            "has_vendor_name":          "INV-003" in val_result["passed_rule_codes"],
            "has_vendor_vat":           "INV-004" in val_result["passed_rule_codes"],
            "has_total_amount":         "INV-005" in val_result["passed_rule_codes"],
            "has_currency":             "INV-006" in val_result["passed_rule_codes"],
            "total_greater_zero":       "INV-007" in val_result["passed_rule_codes"],
            "no_vat_without_base":      "INV-008" in val_result["passed_rule_codes"],
            "duplicate_invoice_number": "DUP-001" in val_result["failed_rule_codes"],
            "duplicate_vendor_and_number": "DUP-002" in val_result["failed_rule_codes"],
            "duplicate_vendor_amount_date": "DUP-003" in val_result["failed_rule_codes"],
            "duplicate_file_hash":      "DUP-004" in val_result["failed_rule_codes"],
            "duplicate_across_months":  "DUP-005" in val_result["failed_rule_codes"],
            "vat_rate_correct":         "VAT-001" in val_result["passed_rule_codes"],
            "vat_calculation_correct":  "VAT-002" in val_result["passed_rule_codes"],
            "vat_subtotal_correct":     "VAT-003" in val_result["passed_rule_codes"],
            "vat_number_present":       "VAT-004" in val_result["passed_rule_codes"],
            "qr_code_valid":            "VAT-005" in val_result["passed_rule_codes"],
            "amount_unusually_high":    "ANO-001" in val_result["failed_rule_codes"],
            "new_unknown_vendor":       "ANO-002" in val_result["failed_rule_codes"],
            "many_invoices_same_day":   "ANO-003" in val_result["failed_rule_codes"],
            "sudden_price_change":      "ANO-004" in val_result["failed_rule_codes"],
            "many_invoices_year_end":   "ANO-005" in val_result["failed_rule_codes"],
            "vendor_dominates_invoices":"ANO-006" in val_result["failed_rule_codes"],
            "has_cost_center":          "CTL-001" in val_result["passed_rule_codes"],
            "has_account_code":         "CTL-002" in val_result["passed_rule_codes"],
            "has_approver":             "CTL-005" in val_result["passed_rule_codes"],
            "document_is_clear":        "DOC-001" in val_result["passed_rule_codes"],
            "appears_genuine":          "DOC-002" in val_result["passed_rule_codes"],
            "no_alterations":           "DOC-003" in val_result["passed_rule_codes"],
            "has_qr_code":              "DOC-004" in val_result["passed_rule_codes"],
            "rules_passed":             val_result["rules_passed"],
            "rules_failed":             val_result["rules_failed"],
            "validation_score":         val_result["validation_score"],
            "failed_rule_codes":        val_result["failed_rule_codes"],
            "validation_details":       val_result["rule_details"],
        }
    )

    _save_audit_event(invoice, user, InvoiceAuditEvent.EventType.VALIDATED,
                      f"Validation score: {val_result['validation_score']}% | Failed: {val_result['failed_rule_codes']}",
                      request=request)

    # ── Step 5: AI Risk Analysis ──────────────────────────────────────────────
    vendor_hist = _get_vendor_history(org, invoice.vendor_name)
    try:
        risk_result = analyze_invoice_risk(
            {k: v for k, v in ai_data.items() if not k.startswith("_")},
            vendor_hist,
        )
    except Exception as e:
        logger.warning(f"AI risk analysis failed: {e}")
        risk_result = {}

    # Merge risk into invoice
    risk_result = _merge_risk_assessment(invoice, val_result, risk_result)
    invoice.save()

    # ── Step 6: Update vendor profile ────────────────────────────────────────
    _update_vendor_profile(org, invoice)

    elapsed_ms = int((time.time() - start) * 1000)
    logger.info(f"Invoice {invoice.id} processed in {elapsed_ms}ms | Score: {val_result['validation_score']}%")

    return {
        "invoice_id": str(invoice.id),
        "filename": filename,
        "success": True,
        "validation_score": val_result["validation_score"],
        "rules_failed": val_result["failed_rule_codes"],
        "risk_level": invoice.risk_level,
        "status": invoice.status,
        "processing_ms": elapsed_ms,
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

        results = []
        errors  = []

        for uploaded_file in uploaded_files:
            filename = uploaded_file.name
            ext = os.path.splitext(filename)[1].lower()

            if ext not in ALLOWED_EXT:
                errors.append({"filename": filename, "error": f"Unsupported file type: {ext}"})
                batch.failed_files += 1
                continue

            # ── ZIP: extract and process each file inside ─────────────────────
            if ext == ".zip":
                zip_results, zip_errors = _process_zip(uploaded_file, org, request.user, batch, request)
                results.extend(zip_results)
                errors.extend(zip_errors)
                batch.total_files += len(zip_results) + len(zip_errors) - 1  # replace 1 zip with n files
            else:
                try:
                    r = _process_single_file(uploaded_file, filename, org, request.user, batch, request)
                    results.append(r)
                    batch.processed_files += 1
                except Exception as e:
                    logger.error(f"Failed processing {filename}: {e}")
                    errors.append({"filename": filename, "error": str(e)})
                    batch.failed_files += 1

        # Finalize batch
        batch.status = (
            InvoiceBatch.BatchStatus.COMPLETED  if not errors else
            InvoiceBatch.BatchStatus.PARTIAL    if results else
            InvoiceBatch.BatchStatus.FAILED
        )
        batch.completed_at = timezone.now()
        batch.processing_log = results + errors
        batch.save()

        log_action(request, AuditLog.Action.DOCUMENT_UPLOAD, "invoice_batch", str(batch.id),
                   {"files": len(results), "errors": len(errors)})

        return Response({
            "batch_id":      str(batch.id),
            "batch_name":    batch_name,
            "total_files":   len(results) + len(errors),
            "processed":     len(results),
            "failed":        len(errors),
            "status":        batch.status,
            "results":       results,
            "errors":        errors,
        }, status=status.HTTP_201_CREATED)


def _process_zip(zip_file, org, user, batch, request) -> tuple[list, list]:
    """Extract and process all invoice files inside a ZIP archive."""
    results, errors = [], []
    try:
        with zipfile.ZipFile(io.BytesIO(zip_file.read()), "r") as zf:
            for member in zf.infolist():
                if member.is_dir():
                    continue
                name = os.path.basename(member.filename)
                ext = os.path.splitext(name)[1].lower()
                if ext not in {".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".tif"}:
                    continue
                try:
                    data = zf.read(member)
                    file_like = io.BytesIO(data)
                    file_like.name = name
                    file_like.content_type = _guess_mime(ext)
                    r = _process_single_file(file_like, name, org, user, batch, request)
                    results.append(r)
                    batch.processed_files += 1
                except Exception as e:
                    logger.error(f"ZIP member {name} failed: {e}")
                    errors.append({"filename": name, "error": str(e)})
                    batch.failed_files += 1
    except zipfile.BadZipFile:
        errors.append({"filename": zip_file.name, "error": "Invalid ZIP file"})
    return results, errors


def _guess_mime(ext: str) -> str:
    return {"pdf": "application/pdf", "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "png": "image/png", "tiff": "image/tiff", "tif": "image/tiff"}.get(ext.lstrip("."), "application/octet-stream")


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

    @extend_schema(tags=["Invoices"], summary="Get full invoice details with validation results")
    def get(self, request, *args, **kwargs):
        invoice = self.get_object()
        data = InvoiceDetailSerializer(invoice).data
        try:
            data["validation"] = InvoiceValidationResultSerializer(invoice.validation).data
        except InvoiceValidationResult.DoesNotExist:
            data["validation"] = None
        data["audit_trail"] = list(
            invoice.audit_events.order_by("-timestamp").values(
                "event_type", "description", "timestamp", "user__full_name", "ip_address"
            )[:20]
        )
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
        return Invoice.objects.filter(organization=self.request.user.organization)


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

        file_hash = invoice.extracted_data.get("file_hash", "")
        val_result = run_all_rules(invoice, organization=request.user.organization, file_hash=file_hash)

        InvoiceValidationResult.objects.filter(invoice=invoice).update(
            rules_passed=val_result["rules_passed"],
            rules_failed=val_result["rules_failed"],
            validation_score=val_result["validation_score"],
            failed_rule_codes=val_result["failed_rule_codes"],
            validation_details=val_result["rule_details"],
        )
        risk_result = {}
        try:
            risk_result = analyze_invoice_risk(invoice.extracted_data or {}, _get_vendor_history(request.user.organization, invoice.vendor_name))
        except Exception as exc:
            logger.warning(f"AI risk re-analysis failed: {exc}")

        _merge_risk_assessment(invoice, val_result, risk_result)
        invoice.save(update_fields=["risk_score", "risk_level", "ai_recommendations", "ai_summary", "is_duplicate", "status"])

        _save_audit_event(invoice, request.user, InvoiceAuditEvent.EventType.REPROCESSED,
                          f"Re-validated: score={val_result['validation_score']}%", request=request)

        return Response(val_result)


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
