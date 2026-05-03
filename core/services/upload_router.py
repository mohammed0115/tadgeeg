"""
DocumentUploadRouter — Central routing service for all file uploads.

Routes any uploaded document to the correct processing pipeline
based on document type.

Invoice → Invoice pipeline (AuditProcessingService with INVOICE type)
All others → Document pipeline (AuditProcessingService)
"""
from __future__ import annotations

import json
import logging
import os
import socket
from pathlib import Path
import tempfile
from urllib.parse import urlparse
from typing import Optional

logger = logging.getLogger(__name__)


# Map upload-router document type names → SupportedDocumentType values used by rule engine
_UPLOAD_TYPE_TO_RE_TYPE = {
    "invoice":         "sales_invoice",
    "purchase_order":  "purchase_order",
    "bank_statement":  "bank_statement",
    "payroll":         "payroll",
    "expense_report":  "expense",
    "tax_declaration": "tax_return",
    "fixed_asset":     "fixed_asset",
    "sales_receipt":   "sales_receipt",
}


def _has_active_run(document_id: str, document_type: str, organization_id: str) -> bool:
    """
    Return True when a PENDING/RUNNING/COMPLETED AuditRun already exists for
    this document within the last hour — prevents double-dispatch.
    """
    try:
        from datetime import timedelta
        from django.utils import timezone
        from apps.rule_engine.models import AuditRun
        cutoff = timezone.now() - timedelta(hours=1)
        return AuditRun.objects.filter(
            document_id=str(document_id),
            document_type=document_type,
            organization_id=str(organization_id),
            status__in=[
                AuditRun.Status.PENDING,
                AuditRun.Status.RUNNING,
                AuditRun.Status.COMPLETED,
            ],
            started_at__gte=cutoff,
        ).exists()
    except Exception:
        return False  # fail open — allow dispatch if check errors


def _trigger_rule_engine(document_id: str, document_type: str, organization_id: str, triggered_by: str = "upload") -> None:
    """
    Fire the asynchronous V2 audit task via run_audit_compat_task.
    Deduplication guard prevents double-dispatch within a 1-hour window.
    Never raises — failures are logged and swallowed so the upload is unaffected.
    """
    re_type = _UPLOAD_TYPE_TO_RE_TYPE.get(document_type, "other")

    if triggered_by != "reprocess" and _has_active_run(str(document_id), re_type, str(organization_id)):
        logger.info(
            "[RuleEngine] Skipping duplicate dispatch: doc=%s type=%s already running/completed",
            document_id, re_type,
        )
        return

    try:
        from django.conf import settings

        if not getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
            broker_url = getattr(settings, "CELERY_BROKER_URL", "") or ""
            parsed = urlparse(broker_url)
            if parsed.scheme.startswith("redis") and parsed.hostname and parsed.port:
                with socket.create_connection((parsed.hostname, parsed.port), timeout=0.5):
                    pass
    except OSError:
        logger.info(
            "[RuleEngine] Broker unavailable, skipping async dispatch for doc=%s type=%s",
            document_id,
            re_type,
        )
        return
    except Exception:
        pass

    try:
        from apps.rule_engine.tasks.audit_tasks_v2 import run_audit_compat_task
        run_audit_compat_task.delay(
            document_id=str(document_id),
            document_type=re_type,
            organization_id=str(organization_id),
            triggered_by=triggered_by,
        )
        logger.info("[RuleEngine] Queued V2 audit: doc=%s type=%s", document_id, re_type)
    except Exception as exc:
        logger.warning("[RuleEngine] Could not queue audit task for %s: %s", document_id, exc)


class UploadRouterResult:
    """Result from the upload router."""

    def __init__(
        self,
        *,
        success: bool,
        pipeline: str,  # "invoice" | "document"
        object_id: str,
        result_url: str,
        error: Optional[str] = None,
    ):
        self.success = success
        self.pipeline = pipeline
        self.object_id = object_id
        self.result_url = result_url
        self.error = error


class DocumentUploadRouter:
    """
    Single entry point for all document uploads.
    Selects the correct processing pipeline based on document_type.
    """

    INVOICE_TYPES = {"invoice", "sales_invoice", "purchase_invoice"}
    AUTO_DETECT_TYPE = "auto"
    ROUTABLE_DOCUMENT_TYPES = {
        # Phase 1
        "invoice",
        "purchase_order",
        "bank_statement",
        "payroll",
        "expense_report",
        "tax_declaration",
        "fixed_asset",
        "sales_receipt",
        # Phase 2/3 — full 20-type catalog
        "sales_invoice",
        "purchase_invoice",
        "sales_order",
        "quotation",
        "proforma_invoice",
        "goods_receipt_note",
        "payment_voucher",
        "receipt_voucher",
        "cash_voucher",
        "journal_entry",
        "general_ledger",
        "ledger",
        "contract",
        "supplier_statement",
        "customer_statement",
        "other",
    }
    OPENAI_TYPE_ALIASES = {
        "receipt": "sales_receipt",
        "vat_return": "tax_declaration",
        "tax_return": "tax_declaration",
        "tax_vat_document": "tax_declaration",
        "grn": "goods_receipt_note",
        "goods_receipt": "goods_receipt_note",
        "po": "purchase_order",
        "so": "sales_order",
        "sales_invoice": "invoice",       # SI uses the canonical invoice pipeline
        "purchase_invoice": "invoice",    # PI also uses the canonical invoice pipeline
    }

    def route(
        self,
        *,
        uploaded_file,
        document_type: str,
        user,
        language: str = "auto",
        organization=None,
    ) -> UploadRouterResult:
        """
        Route uploaded file to the correct pipeline.

        Args:
            uploaded_file: Django InMemoryUploadedFile / TemporaryUploadedFile
            document_type: One of AuditDocument.DocumentType values
            user: authenticated User instance
            language: language hint
            organization: optional Organization instance (for multi-tenant pipelines)

        Returns:
            UploadRouterResult with object_id and result_url for redirect
        """
        # Phase 1: EngineRouter delegates back to existing pipelines.
        # Phase 2: EngineRouter will own the routing decision directly.
        # No functional change is introduced here in Phase 1.
        resolved_type = self._resolve_document_type(uploaded_file, document_type)

        if resolved_type in self.INVOICE_TYPES:
            return self._route_invoice(uploaded_file, user, language, organization)
        if resolved_type == "other":
            return self._route_document_fallback(uploaded_file, resolved_type, user, language)
        return self._route_document(uploaded_file, resolved_type, user, language)

    def _resolve_document_type(self, uploaded_file, document_type: Optional[str]) -> str:
        normalized_type = self._normalise_document_type(document_type)
        if normalized_type != self.AUTO_DETECT_TYPE:
            return normalized_type

        detected_type = self._detect_document_type(uploaded_file)
        logger.info(
            "[UploadRouter] Auto-detected %s for %s",
            detected_type,
            getattr(uploaded_file, "name", "uploaded-file"),
        )
        return detected_type

    def _normalise_document_type(self, document_type: Optional[str]) -> str:
        normalized_type = str(document_type or "").strip().lower()
        if not normalized_type:
            return self.AUTO_DETECT_TYPE

        normalized_type = self.OPENAI_TYPE_ALIASES.get(normalized_type, normalized_type)
        if normalized_type == self.AUTO_DETECT_TYPE:
            return normalized_type
        if normalized_type in self.ROUTABLE_DOCUMENT_TYPES:
            return normalized_type

        logger.warning(
            "[UploadRouter] Unsupported document type '%s'; defaulting to other.",
            document_type,
        )
        return "other"

    def _detect_document_type(self, uploaded_file) -> str:
        raw_text, structured = self._extract_detection_input(uploaded_file)
        detection_text = raw_text or self._structured_to_text(structured)
        if not detection_text:
            return "other"

        try:
            from core.services.ai.openai_extractor import classify_document

            result = classify_document(
                detection_text,
                allowed_types=sorted(self.ROUTABLE_DOCUMENT_TYPES),
                aliases=self.OPENAI_TYPE_ALIASES,
            )
            detected_type = self._normalise_document_type(result.get("document_type"))
            if detected_type != "other":
                return detected_type
        except Exception as exc:
            logger.warning(
                "[UploadRouter] OpenAI document classification failed for %s: %s",
                getattr(uploaded_file, "name", "uploaded-file"),
                exc,
            )

        return self._fallback_detect_document_type(raw_text, structured)

    def _fallback_detect_document_type(self, raw_text: str, structured: Optional[dict]) -> str:
        try:
            from core.services.classification.document_classifier import DocumentClassifier

            result = DocumentClassifier().classify(
                raw_text=raw_text,
                structured=structured or {},
                use_ai=False,
            )
            return self._normalise_document_type(result.get("document_type"))
        except Exception as exc:
            logger.warning("[UploadRouter] Fallback document classification failed: %s", exc)
            return "other"

    def _extract_detection_input(self, uploaded_file) -> tuple[str, dict]:
        temp_path = None
        try:
            if hasattr(uploaded_file, "seek"):
                uploaded_file.seek(0)

            suffix = Path(getattr(uploaded_file, "name", "upload")).suffix or ".bin"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp_file:
                if hasattr(uploaded_file, "chunks"):
                    for chunk in uploaded_file.chunks():
                        temp_file.write(chunk)
                else:
                    temp_file.write(uploaded_file.read())
                temp_path = temp_file.name

            from core.services.document_engine import DocumentEngine

            ingestion = DocumentEngine(use_ai=False).ingest(temp_path, use_ai=False)
            raw_text = (getattr(ingestion, "raw_text", "") or "").strip()
            structured = (
                getattr(ingestion, "structured", None)
                or getattr(ingestion, "normalized", None)
                or {}
            )
            return raw_text, structured
        except Exception as exc:
            logger.warning(
                "[UploadRouter] Could not prepare auto-detect input for %s: %s",
                getattr(uploaded_file, "name", "uploaded-file"),
                exc,
            )
            return "", {}
        finally:
            try:
                if hasattr(uploaded_file, "seek"):
                    uploaded_file.seek(0)
            except Exception:
                pass

            if temp_path:
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    @staticmethod
    def _structured_to_text(structured: Optional[dict]) -> str:
        if not structured:
            return ""

        try:
            return json.dumps(structured, ensure_ascii=False, default=str)
        except TypeError:
            return " ".join(
                str(value)
                for value in structured.values()
                if value not in (None, "", [], {})
            )

    def _route_invoice(self, uploaded_file, user, language, organization) -> UploadRouterResult:
        """
        Route to the invoice processing pipeline.

        Calls the canonical _process_single_file() function from apps.invoices.views
        so the invoice runs through all 30 audit rules, AI extraction, and ZATCA
        compliance checks, and is saved as an Invoice record visible at /invoices/.
        """
        from apps.invoices.views import _process_single_file, _process_structured_upload
        from apps.audit.services import AuditSessionService
        from apps.invoices.models import InvoiceBatch
        from django.utils import timezone

        try:
            org = getattr(user, "organization", None)
            if not org:
                return UploadRouterResult(
                    success=False,
                    pipeline="invoice",
                    object_id="",
                    result_url="/auditor/upload/",
                    error="User has no organization. Invoice upload requires an organisation.",
                )

            batch_name = f"Upload {timezone.now().strftime('%Y-%m-%d %H:%M')}"
            batch = InvoiceBatch.objects.create(
                organization=org,
                uploaded_by=user,
                batch_name=batch_name,
                total_files=1,
            )
            audit_session = AuditSessionService.create_session(
                organization=org,
                created_by=user,
                name=batch_name,
                total_count=1,
                context={"source": "unified_upload"},
            )
            batch.audit_session = audit_session
            batch.save(update_fields=["audit_session"])

            structured = _process_structured_upload(
                uploaded_file,
                uploaded_file.name,
                org,
                user,
                batch=batch,
                request=None,
                audit_session=audit_session,
            )
            if structured and structured.get("handled"):
                if structured.get("mode") == "async_chunked":
                    return UploadRouterResult(
                        success=True,
                        pipeline="invoice",
                        object_id=str(batch.id),
                        result_url=f"/invoices/?batch_id={batch.id}",
                        error=None,
                    )

                chunk_results = structured.get("results", [])
                chunk_errors = structured.get("errors", [])
                if len(chunk_results) == 1 and not chunk_errors:
                    invoice_id = chunk_results[0].get("invoice_id")
                    if invoice_id and org:
                        _trigger_rule_engine(invoice_id, "invoice", org.id)
                    return UploadRouterResult(
                        success=True,
                        pipeline="invoice",
                        object_id=invoice_id or str(batch.id),
                        result_url=f"/invoices/{invoice_id}/" if invoice_id else f"/invoices/?batch_id={batch.id}",
                        error=None,
                    )

                return UploadRouterResult(
                    success=bool(chunk_results),
                    pipeline="invoice",
                    object_id=str(batch.id),
                    result_url=f"/invoices/?batch_id={batch.id}",
                    error=chunk_errors[0].get("error") if chunk_errors and not chunk_results else None,
                )

            result = _process_single_file(
                uploaded_file,
                uploaded_file.name,
                org,
                user,
                batch=batch,
                request=None,
                audit_session=audit_session,
            )

            invoice_id = result.get("invoice_id")
            if invoice_id:
                result_url = f"/invoices/{invoice_id}/"
            else:
                result_url = "/invoices/"

            if invoice_id and org:
                _trigger_rule_engine(invoice_id, "invoice", org.id)

            return UploadRouterResult(
                success=result.get("success", True),
                pipeline="invoice",
                object_id=invoice_id or "",
                result_url=result_url,
                error=result.get("error"),
            )

        except Exception as exc:
            logger.exception("Invoice routing failed: %s", exc)
            return UploadRouterResult(
                success=False,
                pipeline="invoice",
                object_id="",
                result_url="/auditor/upload/",
                error=str(exc)[:300],
            )

    # Map document types to their frontend list URLs
    _DOC_TYPE_LIST_URLS = {
        # Phase 1
        "purchase_order":      "/documents/purchase-orders/",
        "bank_statement":      "/documents/bank-statements/",
        "payroll":             "/documents/payroll/",
        "expense_report":      "/documents/expense-reports/",
        "tax_declaration":     "/documents/vat-returns/",
        "fixed_asset":         "/documents/fixed-assets/",
        "sales_receipt":       "/documents/sales-receipts/",
        # Phase 2 — typed-models v2
        "sales_order":         "/documents/sales-orders/",
        "quotation":           "/documents/quotations/",
        "proforma_invoice":    "/documents/proforma-invoices/",
        "receipt_voucher":     "/documents/receipt-vouchers/",
        "cash_voucher":        "/documents/cash-vouchers/",
        "general_ledger":      "/documents/general-ledgers/",
        "ledger":              "/documents/ledgers/",
        "contract":            "/documents/contracts/",
        "supplier_statement":  "/documents/supplier-statements/",
        "customer_statement":  "/documents/customer-statements/",
        # Late additions
        "goods_receipt_note":  "/documents/grns/",
        "payment_voucher":     "/documents/payment-vouchers/",
        "journal_entry":       "/documents/journal-entries/",
    }

    # Map document types to their frontend detail URL patterns
    _DOC_TYPE_DETAIL_URLS = {
        # Phase 1
        "purchase_order":      "/documents/purchase-orders/{pk}/",
        "bank_statement":      "/documents/bank-statements/{pk}/",
        "payroll":             "/documents/payroll/{pk}/",
        "expense_report":      "/documents/expense-reports/{pk}/",
        "tax_declaration":     "/documents/vat-returns/{pk}/",
        "fixed_asset":         "/documents/fixed-assets/{pk}/",
        "sales_receipt":       "/documents/sales-receipts/{pk}/",
        # Phase 2 — typed-models v2
        "sales_order":         "/documents/sales-orders/{pk}/",
        "quotation":           "/documents/quotations/{pk}/",
        "proforma_invoice":    "/documents/proforma-invoices/{pk}/",
        "receipt_voucher":     "/documents/receipt-vouchers/{pk}/",
        "cash_voucher":        "/documents/cash-vouchers/{pk}/",
        "general_ledger":      "/documents/general-ledgers/{pk}/",
        "ledger":              "/documents/ledgers/{pk}/",
        "contract":            "/documents/contracts/{pk}/",
        "supplier_statement":  "/documents/supplier-statements/{pk}/",
        "customer_statement":  "/documents/customer-statements/{pk}/",
        # Late additions
        "goods_receipt_note":  "/documents/grns/{pk}/",
        "payment_voucher":     "/documents/payment-vouchers/{pk}/",
        "journal_entry":       "/documents/journal-entries/{pk}/",
    }

    def _route_document(self, uploaded_file, document_type, user, language) -> UploadRouterResult:
        """
        Route to the typed document pipeline (_process_typed_document).

        Saves the document as the correct typed model record
        (PurchaseOrder, BankStatement, etc.) so it appears at
        /documents/<type>/ with full AI extraction and validation.
        """
        from apps.documents.typed_views import _process_typed_document

        # Map auditor doc type names to the typed_views expected names
        # (they use the same names so no mapping needed)
        typed_doc_type = document_type

        org = getattr(user, "organization", None)
        if not org:
            # No org — fall back to AI auditor pipeline (stores in AuditDocument)
            return self._route_document_fallback(uploaded_file, document_type, user, language)

        try:
            result = _process_typed_document(
                uploaded_file,
                uploaded_file.name,
                typed_doc_type,
                org,
                user,
                request=None,
            )

            typed_id = result.get("document_id")
            detail_pattern = self._DOC_TYPE_DETAIL_URLS.get(document_type)
            list_url = self._DOC_TYPE_LIST_URLS.get(document_type, "/documents/")

            if typed_id and detail_pattern:
                result_url = detail_pattern.format(pk=typed_id)
            else:
                result_url = list_url

            if typed_id and org:
                _trigger_rule_engine(typed_id, document_type, org.id)

            return UploadRouterResult(
                success=result.get("success", True),
                pipeline="document",
                object_id=str(typed_id or ""),
                result_url=result_url,
                error=result.get("error"),
            )
        except Exception as exc:
            logger.exception("Typed document routing failed: %s", exc)
            return UploadRouterResult(
                success=False,
                pipeline="document",
                object_id="",
                result_url=self._DOC_TYPE_LIST_URLS.get(document_type, "/documents/"),
                error=str(exc)[:300],
            )

    def _route_document_fallback(self, uploaded_file, document_type, user, language) -> UploadRouterResult:
        """Fallback for users without an organisation: use AI Auditor pipeline."""
        from apps.auditing.models import AuditDocument
        from apps.auditing.repositories.document_repository import DocumentRepository
        from apps.auditing.services.audit_processing_service import AuditProcessingService
        from django.urls import reverse
        try:
            document = DocumentRepository.create(
                uploaded_by=user,
                file=uploaded_file,
                original_name=uploaded_file.name,
                selected_doc_type=document_type or AuditDocument.DocumentType.OTHER,
                language=language,
            )
            AuditProcessingService().process(document)
            result_url = reverse("auditor:result", kwargs={"pk": document.pk})
            return UploadRouterResult(
                success=True,
                pipeline="document_fallback",
                object_id=str(document.pk),
                result_url=result_url,
            )
        except Exception as exc:
            logger.exception("Document fallback routing failed: %s", exc)
            return UploadRouterResult(
                success=False,
                pipeline="document_fallback",
                object_id="",
                result_url="/auditor/upload/",
                error=str(exc)[:300],
            )
