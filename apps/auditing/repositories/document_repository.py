"""Document Repository — data access layer for AuditDocument."""

import logging

from ..models import AuditDocument

logger = logging.getLogger(__name__)


class DocumentRepository:
    @staticmethod
    def create(*, uploaded_by, file, original_name, selected_doc_type, language) -> AuditDocument:
        return AuditDocument.objects.create(
            uploaded_by=uploaded_by,
            file=file,
            original_name=original_name,
            selected_doc_type=selected_doc_type,
            language=language,
        )

    @staticmethod
    def set_processing(doc: AuditDocument) -> None:
        AuditDocument.objects.filter(pk=doc.pk).update(
            status=AuditDocument.Status.PROCESSING
        )
        doc.status = AuditDocument.Status.PROCESSING

    @staticmethod
    def save_result(
        doc: AuditDocument,
        *,
        extracted_text: str,
        normalized_text: str,
        detected_doc_type: str,
        language: str,
        ai_result: dict,
        overall_confidence: float,
        overall_risk_level: str,
        executive_summary: str,
    ) -> None:
        AuditDocument.objects.filter(pk=doc.pk).update(
            status=AuditDocument.Status.COMPLETED,
            extracted_text=extracted_text,
            normalized_text=normalized_text,
            detected_doc_type=detected_doc_type,
            language=language,
            ai_result=ai_result,
            overall_confidence=overall_confidence,
            overall_risk_level=overall_risk_level,
            executive_summary=executive_summary,
            processing_error="",
        )

    @staticmethod
    def save_error(doc: AuditDocument, error: str) -> None:
        AuditDocument.objects.filter(pk=doc.pk).update(
            status=AuditDocument.Status.FAILED,
            processing_error=error,
        )

    # Legacy compatibility — used by old AuditProcessingService
    def update(self, doc, **kwargs):
        """Update fields on an existing AuditDocument (legacy interface)."""
        for field, value in kwargs.items():
            setattr(doc, field, value)
        doc.save()
        return doc
