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
        """Route to the invoice processing pipeline."""
        from apps.auditing.models import AuditDocument
        from apps.auditing.repositories.document_repository import DocumentRepository
        from apps.auditing.services.audit_processing_service import AuditProcessingService
        try:
            document = DocumentRepository.create(
                uploaded_by=user,
                file=uploaded_file,
                original_name=uploaded_file.name,
                selected_doc_type=AuditDocument.DocumentType.INVOICE,
                language=language,
            )
            service = AuditProcessingService()
            service.process(document)
            from django.urls import reverse
            result_url = reverse("auditor:result", kwargs={"pk": document.pk})
            return UploadRouterResult(
                success=True,
                pipeline="invoice",
                object_id=str(document.pk),
                result_url=result_url,
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

    def _route_document(self, uploaded_file, document_type, user, language) -> UploadRouterResult:
        """Route to the document auditing pipeline."""
        from apps.auditing.models import AuditDocument
        from apps.auditing.repositories.document_repository import DocumentRepository
        from apps.auditing.services.audit_processing_service import AuditProcessingService
        try:
            document = DocumentRepository.create(
                uploaded_by=user,
                file=uploaded_file,
                original_name=uploaded_file.name,
                selected_doc_type=document_type or AuditDocument.DocumentType.OTHER,
                language=language,
            )
            service = AuditProcessingService()
            service.process(document)
            from django.urls import reverse
            result_url = reverse("auditor:result", kwargs={"pk": document.pk})
            return UploadRouterResult(
                success=True,
                pipeline="document",
                object_id=str(document.pk),
                result_url=result_url,
            )
        except Exception as exc:
            logger.exception("Document routing failed: %s", exc)
            return UploadRouterResult(
                success=False,
                pipeline="document",
                object_id="",
                result_url="/auditor/upload/",
                error=str(exc)[:300],
            )
