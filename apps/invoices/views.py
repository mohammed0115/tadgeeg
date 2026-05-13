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
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.core.files.base import ContentFile
from django.db.models import Avg, Count, F, Max, Min, Q, Sum
from django.http import FileResponse
from django.shortcuts import render
from rest_framework import mixins
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.translation import gettext as _
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
from core.services.parsers.structured import iter_structured_records, normalize_row
from apps.invoices.services.processor import (
    process_single_file as _process_single_file_impl,
    process_structured_rows_chunk as _process_structured_rows_chunk_impl,
    process_structured_upload as _process_structured_upload_impl,
    process_zip as _process_zip_impl,
    get_vendor_history as _get_vendor_history_impl,
)
from core.services.validation_pipeline import ValidationPipelineService
from core.services.zip_validator import validate_zip_bomb, ZipValidationError
from core.utils.audit import log_action, record_invoice_event
from apps.authentication.models import AuditLog
from apps.rule_engine.models import RiskScoreSummary

from .models import (
    Invoice, InvoiceAuditEvent, InvoiceBatch, InvoiceValidationResult, VendorProfile
)
from .services.validation_service import InvoiceValidationService
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
ALLOWED_EXT  = {".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".webp",
                ".gif", ".bmp", ".zip", ".xlsx", ".xls", ".xlsm",
                ".json", ".jsonl", ".ndjson", ".csv", ".tsv",
                ".xml", ".txt", ".md"}

DEFAULT_BULK_CHUNK_SIZE = 250
MIN_BULK_CHUNK_SIZE = 25
MAX_BULK_CHUNK_SIZE = 1000
AUTO_ASYNC_FILE_SIZE = 512 * 1024
STRUCTURED_BULK_EXTENSIONS = {".csv", ".tsv", ".json", ".xlsx", ".xls"}

# Loaded lazily to avoid circular imports while still allowing tests to patch it.
process_invoice_rows_chunk_task = None


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _get_client_ip(request):
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    return xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR", "")


def _save_audit_event(invoice, user, event_type, description="", before=None, after=None, request=None):
    """Thin wrapper kept for call-site compatibility; delegates to the canonical helper."""
    record_invoice_event(invoice, user, event_type, description, before, after, request)


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


# ── Risk helpers — delegated to InvoiceValidationService ──────────────────────
def _to_float(value, default=0.0):
    return InvoiceValidationService.to_float(value, default)


def _risk_level_from_score(score):
    return InvoiceValidationService.risk_level_from_score(score)


def _fallback_risk_score(validation_result):
    return InvoiceValidationService.fallback_risk_score(validation_result)


def _merge_risk_assessment(invoice, validation_result, risk_result):
    return InvoiceValidationService.merge_risk_assessment(invoice, validation_result, risk_result)


REVIEW_FIELD_META = [
    ("vendor_name", _("Vendor Name"), "text"),
    ("vendor_vat_number", _("Vendor VAT Number"), "text"),
    ("invoice_number", _("Invoice Number"), "text"),
    ("invoice_date", _("Invoice Date"), "date"),
    ("due_date", _("Due Date"), "date"),
    ("subtotal", _("Subtotal"), "amount"),
    ("vat_amount", _("VAT Amount"), "amount"),
    ("total_amount", _("Total Amount"), "amount"),
    ("currency", _("Currency"), "text"),
    ("customer_name", _("Customer Name"), "text"),
    ("customer_vat_number", _("Customer VAT Number"), "text"),
    ("cost_center", _("Cost Center"), "text"),
    ("account_code", _("Account Code"), "text"),
    ("budget_code", _("Budget Code"), "text"),
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
        raise ValueError(_("Invalid date for %(field_name)s.") % {"field_name": field_name})

    if field_name in {"subtotal", "vat_amount", "total_amount"}:
        try:
            return Decimal(str(raw_value).replace(",", "").strip())
        except (InvalidOperation, ValueError, TypeError, AttributeError) as exc:
            raise ValueError(_("Invalid amount for %(field_name)s.") % {"field_name": field_name}) from exc

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
    """Delegate to InvoiceValidationService.revalidate()."""
    result = InvoiceValidationService.revalidate(invoice, acting_user, request=request)
    result.raise_if_failed()
    return result.data


def _process_single_file(file_obj, filename: str, org, user, batch=None, request=None, audit_session=None) -> dict:
    """Delegate to InvoiceProcessor.process_single_file (apps/invoices/services/processor.py)."""
    return _process_single_file_impl(file_obj, filename, org, user, batch, request, audit_session)




def _get_vendor_history(org, vendor_name: str) -> dict:
    """Delegate to processor.get_vendor_history (single canonical implementation)."""
    return _get_vendor_history_impl(org, vendor_name)


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


# ── Processing helpers — all delegated to apps/invoices/services/processor.py ──

def _iter_structured_records(uploaded_file, filename: str):
    return iter_structured_records(uploaded_file, filename)

def _normalize_structured_mapping(raw_mapping: dict) -> dict:
    return normalize_row(raw_mapping)

def _process_structured_rows_chunk(rows, *, base_name, org, user, batch,
                                    request=None, audit_session=None,
                                    persist_batch_progress=True):
    return _process_structured_rows_chunk_impl(
        rows, base_name=base_name, org=org, user=user, batch=batch,
        request=request, audit_session=audit_session,
        persist_batch_progress=persist_batch_progress,
    )

def _process_structured_upload(uploaded_file, filename, org, user, batch,
                                request=None, audit_session=None):
    return _process_structured_upload_impl(
        uploaded_file, filename, org, user, batch, request, audit_session,
    )


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
            return Response({"error": _("User has no organization.")}, status=400)

        uploaded_files = request.FILES.getlist("files")
        if not uploaded_files:
            # Try single file key
            single = request.FILES.get("file")
            if single:
                uploaded_files = [single]
            else:
                return Response({"error": _("No files uploaded. Use 'files' or 'file' field.")}, status=400)

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
        async_jobs = []

        from core.utils.file_validation import validate_uploaded_file
        from rest_framework.exceptions import ValidationError as _ValidationError

        for uploaded_file in uploaded_files:
            filename = uploaded_file.name
            ext = os.path.splitext(filename)[1].lower()

            if ext not in ALLOWED_EXT:
                errors.append({"filename": filename, "error": _("Unsupported file type: %(ext)s") % {"ext": ext}})
                batch.failed_files += 1
                AuditSessionService.record_failure(audit_session, f"Unsupported file type: {ext}")
                continue

            # Defensive: validate MIME by inspecting the actual bytes (not just the
            # extension). Catches an .exe renamed to .pdf or scripts disguised as docs.
            try:
                validate_uploaded_file(uploaded_file, filename=filename, check_content=True)
            except _ValidationError as exc:
                errors.append({"filename": filename, "error": str(exc.detail if hasattr(exc, "detail") else exc)})
                batch.failed_files += 1
                AuditSessionService.record_failure(audit_session, f"MIME validation failed: {exc}")
                continue

            # ── ZIP: extract and process each file inside ─────────────────────
            if ext == ".zip":
                zip_results, zip_errors, zip_async_jobs = _process_zip(uploaded_file, org, request.user, batch, request, audit_session)
                results.extend(zip_results)
                errors.extend(zip_errors)
                async_jobs.extend(zip_async_jobs)
                continue

            # ── Structured bulk uploads: CSV / TSV / JSON list / Excel ───────
            if ext in STRUCTURED_BULK_EXTENSIONS:
                structured = _process_structured_upload(uploaded_file, filename, org, request.user, batch, request, audit_session)
                if structured and structured.get("handled"):
                    results.extend(structured.get("results", []))
                    errors.extend(structured.get("errors", []))
                    if structured.get("mode") == "async_chunked":
                        async_jobs.append({
                            "filename": filename,
                            "queued_rows": structured.get("queued_rows", 0),
                            "queued_chunks": structured.get("queued_chunks", 0),
                            "task_ids": structured.get("task_ids", []),
                            "chunk_size": structured.get("chunk_size"),
                            "streaming": structured.get("streaming", True),
                        })
                    continue

            try:
                r = _process_single_file(uploaded_file, filename, org, request.user, batch, request, audit_session)
                _handle_processing_result(r, filename, batch, results, errors, audit_session)
            except Exception as e:
                logger.error(f"Failed processing {filename}: {e}")
                errors.append({"filename": filename, "error": str(e)})
                batch.failed_files += 1
                AuditSessionService.record_failure(audit_session, str(e))

        # Finalize or keep running when async chunks were queued.
        batch.processing_log = list(batch.processing_log or []) + results + errors
        if async_jobs:
            batch.status = InvoiceBatch.BatchStatus.PROCESSING if not errors else InvoiceBatch.BatchStatus.PARTIAL
            batch.save(update_fields=["status", "total_files", "processed_files", "failed_files", "processing_log"])
            AuditSessionService.sync_expected_total(audit_session, batch.total_files)

            log_action(request, AuditLog.Action.DOCUMENT_UPLOAD, "invoice_batch", str(batch.id), {
                "files": len(results),
                "errors": len(errors),
                "async_jobs": len(async_jobs),
                "chunked": True,
            })

            return Response({
                "batch_id": str(batch.id),
                "audit_session_id": str(audit_session.id),
                "batch_name": batch_name,
                "total_files": batch.total_files,
                "processed": batch.processed_files,
                "failed": batch.failed_files,
                "status": batch.status,
                "processing_mode": "async_chunked",
                "streaming": True,
                "queued_chunks": sum(job.get("queued_chunks", 0) for job in async_jobs),
                "queued_rows": sum(job.get("queued_rows", 0) for job in async_jobs),
                "async_jobs": async_jobs,
                "results": results,
                "errors": errors,
            }, status=status.HTTP_202_ACCEPTED)

        batch.status = (
            InvoiceBatch.BatchStatus.COMPLETED if not errors else
            InvoiceBatch.BatchStatus.PARTIAL if results else
            InvoiceBatch.BatchStatus.FAILED
        )
        batch.completed_at = timezone.now()
        batch.save(update_fields=["status", "completed_at", "total_files", "processed_files", "failed_files", "processing_log"])
        AuditSessionService.sync_expected_total(audit_session, batch.total_files)
        AuditSessionService.finalize_if_ready(audit_session)

        log_action(request, AuditLog.Action.DOCUMENT_UPLOAD, "invoice_batch", str(batch.id),
                   {"files": len(results), "errors": len(errors), "chunked": True})

        return Response({
            "batch_id":      str(batch.id),
            "audit_session_id": str(audit_session.id),
            "batch_name":    batch_name,
            "total_files":   batch.total_files,
            "processed":     len(results),
            "failed":        len(errors),
            "status":        batch.status,
            "processing_mode": "sync_chunked",
            "streaming": True,
            "results":       results,
            "errors":        errors,
        }, status=status.HTTP_201_CREATED)


def _process_zip(zip_file, org, user, batch, request, audit_session=None) -> tuple[list, list, list]:
    """Delegate to processor.process_zip."""
    return _process_zip_impl(zip_file, org, user, batch, request, audit_session)


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
        qs = Invoice.objects.filter(
            organization=self.request.user.organization,
            is_deleted=False  # Exclude soft-deleted invoices
        ).select_related(
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


class InvoiceDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = InvoiceDetailSerializer
    permission_classes = [IsAuthenticated, IsOwnOrganization]
    authentication_classes = [JWTAuthentication, SessionAuthentication]

    @extend_schema(tags=["Invoices"], summary="Get full invoice details with validation results")
    def get(self, request, *args, **kwargs):
        invoice = self.get_object()
        
        # Generate ZATCA QR code if not already present and invoice has required fields
        if not invoice.qr_code_image and invoice.vendor_vat_number and invoice.total_amount:
            try:
                invoice.generate_zatca_qr()
                invoice.save(update_fields=['qr_code_image', 'qr_code_data', 'has_qr_code', 'qr_code_valid'])
            except Exception as e:
                import logging
                logging.warning(f"Failed to generate QR code for invoice {invoice.id}: {str(e)}")
        
        if request.path.startswith("/invoices/") and "sessionid" in request.COOKIES:
            from apps.frontend.page_views import _build_invoice_display, _ctx

            audit_trail = invoice.audit_events.select_related("user").order_by("-timestamp")[:40]

            # Cross-doc linkage (PO ↔ GRN ↔ Payment + 3-way match) — parity with Phase-2 detail.
            try:
                from core.services.cross_doc_linker import find_links
                cross_links = find_links("invoice", invoice, getattr(request.user, "organization", None))
            except Exception:
                cross_links = {}

            return render(
                request._request,
                "invoices/detail_premium.html",
                _ctx(
                    request._request,
                    "invoices",
                    invoice=invoice,
                    invoice_display=_build_invoice_display(invoice),
                    audit_trail=audit_trail,
                    cross_links=cross_links,
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

    def perform_destroy(self, instance):
        """Soft delete: mark as deleted with audit trail (GDPR Article 17)."""
        instance.is_deleted = True
        instance.deleted_at = timezone.now()
        instance.deleted_by = self.request.user
        instance.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by', 'updated_at'])
        
        # Log deletion in audit trail
        _save_audit_event(
            instance, 
            self.request.user, 
            InvoiceAuditEvent.EventType.DELETED,
            f"Invoice soft-deleted by {self.request.user.full_name} (GDPR Article 17)",
            request=self.request
        )

    def get_queryset(self):
        return Invoice.objects.filter(
            organization=self.request.user.organization,
            is_deleted=False
        ).select_related(
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
            return Response({"error": _("Invoice not found.")}, status=404)

        action = request.data.get("action")
        if action not in ("approve", "reject"):
            return Response({"error": _("action must be 'approve' or 'reject'")}, status=400)

        # ── Segregation of Duties (Four-Eyes Principle) ────────────────────────
        # The user who uploaded an invoice must not approve it, and the
        # user who reviewed it must not approve it. Reject covers both
        # rules. Service raises SegregationOfDutiesError on violation;
        # surface as JSON 403 with a clear code so the UI can render
        # the localised message.
        from apps.invoices.services.sod_service import (
            SegregationOfDutiesError,
            assert_can_approve,
        )
        try:
            assert_can_approve(invoice, request.user)
        except SegregationOfDutiesError as exc:
            return Response(
                {"error": exc.user_message, "code": "sod_violation",
                 "conflicting_with": exc.conflicting_with,
                 "action": exc.action},
                status=403,
            )

        # ── Approval Gate (Golden Rule) ────────────────────────────────────────
        if action == "approve":
            try:
                risk = RiskScoreSummary.objects.get(document_id=invoice.id)
                has_blocking = risk.blocks_approval
            except RiskScoreSummary.DoesNotExist:
                risk = None
                has_blocking = True  # conservative: no audit run yet = block

            # Admin and CAO can override blocking-rule approval; others can't.
            # Use role check rather than `has_perm` because the Django permission
            # is never granted on a fresh install, leaving admins unable to use
            # their own override workflow.
            from apps.authentication.models import User as _User
            override_roles = {_User.Role.ADMIN, _User.Role.CHIEF_AUDIT_OFFICER}
            is_override = (
                request.data.get("override") is True
                and (
                    request.user.is_superuser
                    or request.user.role in override_roles
                    or request.user.has_perm("invoices.can_override_approval")
                )
            )

            if has_blocking and not is_override:
                return Response({
                    "error": "لا يمكن الاعتماد — يوجد أخطاء حرجة تمنع الاعتماد.",
                    "error_en": "Approval blocked — critical audit failures exist.",
                    "blocking_count": risk.blocking_failures if risk is not None else 0,
                }, status=403)

            if is_override:
                override_reason = request.data.get("override_reason", "").strip()
                if not override_reason:
                    return Response({
                        "error": "سبب الاستثناء مطلوب. / Override reason is required.",
                    }, status=400)
                # Log override to AuditLog immediately before status change
                AuditLog.objects.create(
                    user=request.user,
                    organization=request.user.organization,
                    action=AuditLog.Action.CONFIG_CHANGED,
                    resource_type="invoice",
                    resource_id=str(invoice.id),
                    ip_address=_get_client_ip(request),
                    user_agent=request.META.get("HTTP_USER_AGENT", ""),
                    details={
                        "event": "approval_override",
                        "override_reason": override_reason,
                        "blocking_count": risk.blocking_failures if risk is not None else 0,
                        "before_status": invoice.status,
                        "approver": request.user.full_name,
                    },
                )
        # ── End Approval Gate ──────────────────────────────────────────────────

        before = {"status": invoice.status}

        if action == "approve":
            override_reason = request.data.get("override_reason", "").strip()
            invoice.status      = Invoice.Status.APPROVED
            invoice.approved_by = request.user
            invoice.approved_at = timezone.now()
            event_type          = InvoiceAuditEvent.EventType.APPROVED
            msg = (
                f"Approved with override by {request.user.full_name}: {override_reason}"
                if override_reason
                else f"Approved by {request.user.full_name}"
            )
            # Log workflow transition
            try:
                from apps.workflow.engine import WorkflowTransitionService, WorkflowState
                workflow_svc = WorkflowTransitionService()
                workflow_svc.transition(invoice, WorkflowState.APPROVED, request.user,
                                        override_reason=override_reason or "")
            except Exception as e:
                import logging
                logging.warning(f"Workflow transition logging skipped for invoice {invoice.id}: {e}")
        else:
            reason = request.data.get("reason", "")
            if not reason:
                return Response({"error": _("reason is required for rejection.")}, status=400)
            invoice.status          = Invoice.Status.REJECTED
            invoice.rejected_reason = reason
            event_type              = InvoiceAuditEvent.EventType.REJECTED
            msg                     = f"Rejected: {reason}"
            # Log workflow transition for rejection
            try:
                from apps.workflow.engine import WorkflowTransitionService, WorkflowState
                workflow_svc = WorkflowTransitionService()
                workflow_svc.transition(invoice, WorkflowState.REJECTED, request.user,
                                        reason=reason)
            except Exception as e:
                import logging
                logging.warning(f"Workflow transition logging skipped for rejected invoice {invoice.id}: {e}")

        invoice.save()
        _save_audit_event(invoice, request.user, event_type, msg,
                          before=before, after={"status": invoice.status}, request=request)

        # Fire outbound webhook so customers' ERPs see the state change.
        try:
            from apps.webhooks.services import emit
            emit(
                "invoice.approved" if action == "approve" else "invoice.rejected",
                request.user.organization,
                {
                    "invoice_id":     str(invoice.id),
                    "invoice_number": invoice.invoice_number,
                    "vendor_name":    invoice.vendor_name,
                    "total_amount":   float(invoice.total_amount or 0),
                    "currency":       invoice.currency,
                    "status":         invoice.status,
                    "actor":          getattr(request.user, "email", str(request.user)),
                    "reason":         msg,
                },
            )
        except Exception:
            pass  # never let a webhook failure break the approval flow

        return Response({"invoice_id": str(invoice.id), "status": invoice.status, "message": msg})


class InvoiceEscalateView(APIView):
    """Escalate an invoice to senior review (Scenario 5: high risk / high fraud score)."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Invoices"],
        summary="Escalate an invoice to senior review",
        request={"type": "object", "properties": {
            "reason": {"type": "string", "description": "Escalation reason"},
        }},
    )
    def post(self, request, pk):
        try:
            invoice = Invoice.objects.get(pk=pk, organization=request.user.organization)
        except Invoice.DoesNotExist:
            return Response({"error": _("Invoice not found.")}, status=404)

        if invoice.status in (Invoice.Status.APPROVED, Invoice.Status.REJECTED):
            return Response(
                {"error": _("Cannot escalate an approved or rejected invoice.")},
                status=400,
            )

        reason = request.data.get("reason", "").strip()
        before = {"status": invoice.status}
        invoice.status = Invoice.Status.FLAGGED
        invoice.save(update_fields=["status", "updated_at"])

        _save_audit_event(
            invoice,
            request.user,
            InvoiceAuditEvent.EventType.FLAGGED,
            f"Escalated for senior review: {reason}" if reason else "Escalated for senior review",
            before=before,
            after={"status": invoice.status},
            request=request,
        )
        return Response({
            "invoice_id": str(invoice.id),
            "status": invoice.status,
            "message": "تم إرسال الفاتورة للمراجعة الإضافية. / Invoice escalated for senior review.",
        })


class InvoiceRevalidateView(APIView):
    """Re-run all 30 validation rules on an existing invoice."""
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Invoices"], summary="Re-run all 30 validation rules on an existing invoice")
    def post(self, request, pk):
        try:
            invoice = Invoice.objects.get(pk=pk, organization=request.user.organization)
        except Invoice.DoesNotExist:
            return Response({"error": _("Invoice not found.")}, status=404)
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
            return Response({"error": _("Invoice not found.")}, status=404)

        # Segregation of Duties: the uploader of an invoice cannot also
        # review it. Service raises PermissionError-derived
        # SegregationOfDutiesError → DRF maps that to 403 by default,
        # but we surface the localised message in JSON for cleaner UX.
        from apps.invoices.services.sod_service import (
            SegregationOfDutiesError,
            assert_can_review,
        )
        try:
            assert_can_review(invoice, request.user)
        except SegregationOfDutiesError as exc:
            return Response(
                {"error": exc.user_message, "code": "sod_violation",
                 "conflicting_with": exc.conflicting_with},
                status=403,
            )

        corrections = request.data.get("corrections") or {}
        if not isinstance(corrections, dict):
            return Response({"error": _("corrections must be an object.")}, status=400)

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
        # Stamp the SoD Checker role on the invoice. record_review writes
        # the user + timestamp + a hash-chained audit event so the
        # reviewer's identity is durable for the four-eyes audit.
        from apps.invoices.services.sod_service import record_review
        record_review(invoice, request.user, note=note or "Manual review corrections")

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
            return Response({"error": _("Batch not found.")}, status=404)

        invoices = Invoice.objects.filter(batch=batch, is_deleted=False).values(
            "id", "original_filename", "vendor_name", "total_amount", "currency",
            "invoice_date", "status", "risk_level", "is_duplicate", "ocr_confidence",
        )
        stats = Invoice.objects.filter(batch=batch, is_deleted=False).aggregate(
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


class InvoiceDownloadView(APIView):
    """Securely download an invoice file for the current organization."""
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Invoices"], summary="Download an invoice file")
    def get(self, request, pk):
        try:
            invoice = Invoice.objects.get(
                pk=pk,
                organization=request.user.organization,
                is_deleted=False  # Exclude soft-deleted invoices
            )
        except Invoice.DoesNotExist:
            return Response({"error": _("Invoice not found.")}, status=404)

        if not invoice.file:
            return Response({"error": _("Invoice file is unavailable.")}, status=404)

        filename = invoice.original_filename or os.path.basename(invoice.file.name)
        return FileResponse(invoice.file.open("rb"), as_attachment=True, filename=filename)


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

        high_risk_filter = (
            Q(risk_level__in=["high", "critical"])
            | Q(risk_score__gte=60)
            | Q(status=Invoice.Status.FLAGGED)
        )
        if v := request.query_params.get("risk_level"):
            normalized = str(v).strip().lower()
            if normalized in {"high_risk", "high", "critical"}:
                qs = qs.filter(high_risk_filter)
            else:
                qs = qs.filter(risk_level=normalized)
        else:
            qs = qs.filter(high_risk_filter)

        try:
            page_size = min(max(int(request.query_params.get("page_size", 20) or 20), 1), 100)
        except (TypeError, ValueError):
            page_size = 20

        stats = qs.aggregate(
            count=Count("id"), total=Sum("total_amount"), avg_risk=Avg("risk_score")
        )
        items = list(
            qs.order_by("-risk_score", "-invoice_date").values(
                "id", "invoice_number", "vendor_name", "total_amount", "currency",
                "invoice_date", "risk_level", "risk_score", "ai_summary",
                "is_duplicate", "status", "ai_recommendations",
            )[:page_size]
        )
        return Response({
            "report_type": "risk_report",
            "generated_at": timezone.now().isoformat(),
            "count": stats.get("count") or 0,
            "stats": stats,
            "results": items,
            "invoices": items,
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
    """Report: Vendor intelligence and supplier risk analysis."""
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Invoices"], summary="Vendor intelligence risk analysis report")
    def get(self, request):
        org = request.user.organization
        if not org:
            return Response({"report_type": "vendor_risk_report", "summary": {}, "vendors": []})

        vendors = VendorProfile.objects.filter(organization=org).order_by("-risk_score", "-total_amount")
        if search := request.query_params.get("search"):
            vendors = vendors.filter(vendor_name__icontains=search)
        if risk_tier := request.query_params.get("risk_tier"):
            vendors = vendors.filter(risk_tier=risk_tier)

        limit = min(int(request.query_params.get("limit", 100) or 100), 250)
        summary = vendors.aggregate(
            total_vendors=Count("id"),
            high_risk_vendors=Count("id", filter=Q(risk_tier__in=["high", "blocked"])),
            blocked_vendors=Count("id", filter=Q(risk_tier="blocked")),
            unapproved_vendors=Count("id", filter=Q(is_approved=False)),
            avg_risk_score=Avg("risk_score"),
            avg_frequency_30d=Avg("transaction_frequency_30d"),
            compliance_issue_total=Sum("compliance_issue_count"),
        )
        top_risky = vendors[:5]

        return Response({
            "report_type": "vendor_risk_report",
            "generated_at": timezone.now().isoformat(),
            "summary": {
                "total_vendors": summary.get("total_vendors") or 0,
                "high_risk_vendors": summary.get("high_risk_vendors") or 0,
                "blocked_vendors": summary.get("blocked_vendors") or 0,
                "unapproved_vendors": summary.get("unapproved_vendors") or 0,
                "avg_risk_score": round(float(summary.get("avg_risk_score") or 0), 2),
                "avg_frequency_30d": round(float(summary.get("avg_frequency_30d") or 0), 2),
                "compliance_issue_total": summary.get("compliance_issue_total") or 0,
            },
            "top_risky": VendorProfileSerializer(top_risky, many=True).data,
            "vendors": VendorProfileSerializer(vendors[:limit], many=True).data,
        })


class VendorListView(APIView):
    """Compatibility vendor list endpoint for dashboard and API consumers."""

    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Invoices"], summary="List vendor intelligence profiles for the current organization")
    def get(self, request):
        org = request.user.organization
        if not org:
            return Response({"count": 0, "results": []})

        vendors = VendorProfile.objects.filter(organization=org).order_by("-risk_score", "-total_amount", "vendor_name")
        if search := request.query_params.get("search"):
            vendors = vendors.filter(vendor_name__icontains=search)
        if risk_tier := request.query_params.get("risk_tier"):
            vendors = vendors.filter(risk_tier=risk_tier)
        if approved := request.query_params.get("is_approved"):
            if approved.lower() in {"true", "1", "yes"}:
                vendors = vendors.filter(is_approved=True)
            elif approved.lower() in {"false", "0", "no"}:
                vendors = vendors.filter(is_approved=False)

        return Response({"count": vendors.count(), "results": VendorProfileSerializer(vendors[:100], many=True).data})


class HighRiskVendorListView(APIView):
    """List only high-risk vendor intelligence profiles for the current organization."""

    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Invoices"], summary="List high-risk vendors for the current organization")
    def get(self, request):
        org = request.user.organization
        if not org:
            return Response({"count": 0, "results": []})

        vendors = VendorProfile.objects.filter(
            organization=org,
            risk_tier__in=["high", "blocked"],
        ).order_by("-risk_score", "-updated_at")
        return Response({"count": vendors.count(), "results": VendorProfileSerializer(vendors[:100], many=True).data})


class VendorDetailView(APIView):
    """Detailed Vendor Intelligence profile for a single tenant-scoped vendor."""

    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Invoices"], summary="Get vendor intelligence details for a single supplier")
    def get(self, request, pk):
        org = request.user.organization
        vendor = VendorProfile.objects.filter(organization=org, pk=pk).first()
        if not vendor:
            return Response({"detail": "Not found."}, status=404)

        payload = VendorProfileSerializer(vendor).data
        payload["recent_documents"] = (vendor.transaction_history or {}).get("recent_documents", [])
        payload["compliance_summary"] = vendor.compliance_history or {}
        return Response(payload)


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


class InvoiceBulkActionView(APIView):
    """POST /api/v1/invoices/bulk/

    Apply ``approve`` / ``reject`` / ``flag`` to many invoices in one call.
    Body: ``{"action": "approve|reject|flag", "ids": ["...", "..."], "reason": "..."}``

    Notes:
      - Operates only on invoices in the caller's organization.
      - Each invoice still goes through the same approval-gate logic as the
        single-invoice endpoint (so blocked invoices stay blocked).
      - Webhook fires per affected invoice.
      - Returns per-id success/failure so the caller can show partial results.
    """
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    @extend_schema(
        tags=["Invoices"],
        summary="Bulk approve / reject / flag invoices",
        request={"type": "object", "properties": {
            "action": {"type": "string", "enum": ["approve", "reject", "flag"]},
            "ids":    {"type": "array", "items": {"type": "string", "format": "uuid"}},
            "reason": {"type": "string"},
        }},
    )
    def post(self, request):
        action = request.data.get("action")
        ids = request.data.get("ids") or []
        reason = (request.data.get("reason") or "").strip()
        if action not in ("approve", "reject", "flag"):
            return Response({"error": "action must be approve|reject|flag"}, status=400)
        if not isinstance(ids, list) or not ids:
            return Response({"error": "ids must be a non-empty list"}, status=400)
        if action == "reject" and not reason:
            return Response({"error": "reason is required for reject"}, status=400)
        if len(ids) > 200:
            return Response({"error": "max 200 invoices per bulk call"}, status=400)

        org = request.user.organization
        invoices = Invoice.objects.filter(id__in=ids, organization=org)
        results = []
        from apps.webhooks.services import emit

        for inv in invoices:
            before = inv.status
            try:
                if action == "approve":
                    # Reuse the approval gate from the single endpoint.
                    try:
                        risk = RiskScoreSummary.objects.get(document_id=inv.id)
                        if risk.blocks_approval:
                            results.append({"id": str(inv.id), "ok": False,
                                            "error": "blocked by critical audit failures"})
                            continue
                    except RiskScoreSummary.DoesNotExist:
                        results.append({"id": str(inv.id), "ok": False,
                                        "error": "no audit run yet"})
                        continue
                    inv.status = Invoice.Status.APPROVED
                    inv.approved_by = request.user
                    inv.approved_at = timezone.now()
                    event = "invoice.approved"
                elif action == "reject":
                    inv.status = Invoice.Status.REJECTED
                    inv.rejected_reason = reason
                    event = "invoice.rejected"
                else:  # flag
                    inv.status = Invoice.Status.FLAGGED
                    event = "invoice.flagged"
                inv.save()
                results.append({"id": str(inv.id), "ok": True,
                                "before": before, "after": inv.status})
                try:
                    emit(event, org, {
                        "invoice_id": str(inv.id),
                        "invoice_number": inv.invoice_number,
                        "vendor_name": inv.vendor_name,
                        "total_amount": float(inv.total_amount or 0),
                        "status": inv.status,
                        "actor": getattr(request.user, "email", str(request.user)),
                        "reason": reason or None,
                    })
                except Exception:
                    pass
            except Exception as exc:
                results.append({"id": str(inv.id), "ok": False, "error": str(exc)[:200]})

        ok_count = sum(1 for r in results if r.get("ok"))
        return Response({
            "requested": len(ids),
            "found":     invoices.count(),
            "succeeded": ok_count,
            "failed":    len(results) - ok_count,
            "results":   results,
        })
