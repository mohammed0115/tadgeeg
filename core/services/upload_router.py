"""
DocumentUploadRouter — Central routing service for all file uploads.

Routes any uploaded document to the correct processing pipeline
based on document type.

Invoice → Invoice pipeline (AuditProcessingService with INVOICE type)
All others → Document pipeline (AuditProcessingService)
"""
from __future__ import annotations
import logging
from typing import Optional

logger = logging.getLogger(__name__)


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

    INVOICE_TYPES = {"invoice"}

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
        if document_type in self.INVOICE_TYPES:
            return self._route_invoice(uploaded_file, user, language, organization)
        else:
            return self._route_document(uploaded_file, document_type, user, language)

    def _route_invoice(self, uploaded_file, user, language, organization) -> UploadRouterResult:
        """
        Route to the invoice processing pipeline.

        Calls the canonical _process_single_file() function from apps.invoices.views
        so the invoice runs through all 30 audit rules, AI extraction, and ZATCA
        compliance checks, and is saved as an Invoice record visible at /invoices/.
        """
        from apps.invoices.views import _process_single_file
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
        "purchase_order":  "/documents/purchase-orders/",
        "bank_statement":  "/documents/bank-statements/",
        "payroll":         "/documents/payroll/",
        "expense_report":  "/documents/expense-reports/",
        "tax_declaration": "/documents/vat-returns/",
        "fixed_asset":     "/documents/fixed-assets/",
        "sales_receipt":   "/documents/sales-receipts/",
    }

    # Map document types to their frontend detail URL patterns
    _DOC_TYPE_DETAIL_URLS = {
        "purchase_order":  "/documents/purchase-orders/{pk}/",
        "bank_statement":  "/documents/bank-statements/{pk}/",
        "payroll":         "/documents/payroll/{pk}/",
        "expense_report":  "/documents/expense-reports/{pk}/",
        "tax_declaration": "/documents/vat-returns/{pk}/",
        "fixed_asset":     "/documents/fixed-assets/{pk}/",
        "sales_receipt":   "/documents/sales-receipts/{pk}/",
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
