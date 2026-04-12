from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("finai.engine_router")

TYPED_DOCUMENT_TYPES = {
    "purchase_order",
    "bank_statement",
    "payroll",
    "expense_report",
    "tax_declaration",
    "fixed_asset",
    "sales_receipt",
}


@dataclass(slots=True)
class ProcessingResult:
    success: bool
    document_id: str
    result_url: str
    pipeline: str
    error: Optional[str] = None


class EngineRouter:
    """
    Phase 1 routing layer. Delegates to existing pipelines without changing
    their behaviour or public URLs.
    """

    def process(self, doc_type: str, file, user, org, language: str = "auto", **kwargs) -> ProcessingResult:
        if doc_type == "invoice":
            return self._route_invoice(file, user, org, language, **kwargs)
        if doc_type in TYPED_DOCUMENT_TYPES:
            return self._route_typed_document(file, doc_type, user, org)
        return self._route_legacy_audit(file, doc_type, user, language)

    def _route_invoice(self, file, user, org, language, **kwargs) -> ProcessingResult:
        from core.services.upload_router import DocumentUploadRouter

        router = DocumentUploadRouter()
        result = router._route_invoice(file, user, language, org)
        return ProcessingResult(
            success=result.success,
            document_id=result.object_id,
            result_url=result.result_url,
            pipeline="invoice",
            error=result.error,
        )

    def _route_typed_document(self, file, doc_type, user, org) -> ProcessingResult:
        from core.services.upload_router import DocumentUploadRouter

        router = DocumentUploadRouter()
        result = router._route_document(file, doc_type, user, "auto")
        return ProcessingResult(
            success=result.success,
            document_id=result.object_id,
            result_url=result.result_url,
            pipeline="typed_document",
            error=result.error,
        )

    def _route_legacy_audit(self, file, doc_type, user, language) -> ProcessingResult:
        from core.services.upload_router import DocumentUploadRouter

        router = DocumentUploadRouter()
        result = router._route_document_fallback(file, doc_type, user, language)
        return ProcessingResult(
            success=result.success,
            document_id=result.object_id,
            result_url=result.result_url,
            pipeline="legacy_audit",
            error=result.error,
        )