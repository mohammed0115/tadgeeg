"""
Audit Processing Service — orchestrate the full AI audit pipeline.

.. deprecated::
    This service is DEPRECATED as of AuditPipeline V2.
    All new code should use:

        from apps.rule_engine.services.compatibility.legacy_audit_adapter import (
            LegacyAuditProcessingServiceAdapter as AuditProcessingService,
        )

    This file is retained for backward compatibility only.
"""

import logging

from ..models import AuditDocument
from ..repositories.document_repository import DocumentRepository
from ..repositories.finding_repository import FindingRepository
from .file_router import FileRouterService
from .ocr_service import OCRService
from .parser_service import ParserService
from .zip_service import ZipExtractionService
from .normalization_service import TextNormalizationService
from .document_detection_service import DocumentDetectionService
from .ai_auditor_service import AIAuditorService
from .risk_service import RiskAssessmentService
from .validation_service import ValidationService

logger = logging.getLogger(__name__)


class AuditProcessingService:
    """Orchestrate the full audit pipeline for a financial document."""

    def __init__(self):
        self.router = FileRouterService()
        self.ocr = OCRService()
        self.parser = ParserService()
        self.zip_svc = ZipExtractionService()
        self.normalizer = TextNormalizationService()
        self.detector = DocumentDetectionService()
        self.ai = AIAuditorService()
        self.risk = RiskAssessmentService()
        self.validator = ValidationService()

    def process(self, doc: AuditDocument) -> AuditDocument:
        DocumentRepository.set_processing(doc)
        try:
            return self._run(doc)
        except Exception as exc:
            logger.exception("Processing failed for %s", doc.pk)
            DocumentRepository.save_error(doc, str(exc)[:500])
            return doc

    def _run(self, doc: AuditDocument) -> AuditDocument:
        file_path = doc.file.path
        family = self.router.route(file_path)

        # Step 1: Extract raw text (and decide if Vision is preferred)
        raw_text = self._extract(file_path, family, doc)
        use_vision = self._should_use_vision(family, raw_text)

        # Step 2: Normalize
        result = self.normalizer.normalize(raw_text)
        # normalizer may return a dict or a string depending on implementation
        if isinstance(result, dict):
            normalized = result.get("text", raw_text)
            detected_lang = result.get("language", "unknown")
        else:
            normalized = result or raw_text
            detected_lang = self.normalizer.detect_language(normalized) if hasattr(self.normalizer, "detect_language") else "unknown"

        language = (
            doc.language
            if doc.language not in ("auto", "unknown", "")
            else (detected_lang or "unknown")
        )

        # Step 3: Detect document type
        detection = self.detector.detect(normalized, doc.selected_doc_type or "auto")
        if isinstance(detection, tuple):
            detected_type_raw, type_confidence = detection
        elif isinstance(detection, dict):
            detected_type_raw = detection.get("type", "other")
            type_confidence = detection.get("confidence", 0.0)
        else:
            detected_type_raw = "other"
            type_confidence = 0.0

        detected_type = (
            doc.selected_doc_type
            if doc.selected_doc_type and doc.selected_doc_type != AuditDocument.DocumentType.OTHER
            else detected_type_raw
        )

        # Step 4: AI audit (Vision for images / image-based PDFs, text otherwise)
        if use_vision:
            try:
                images = self._collect_images(file_path, family)
                if images:
                    ai_result = self.ai.audit_images(
                        images,
                        doc_type_hint=detected_type,
                        language=language,
                        ocr_text=normalized or raw_text,
                    )
                else:
                    ai_result = self.ai.audit(normalized or raw_text, doc_type_hint=detected_type, language=language)
            except Exception as exc:
                logger.warning("Vision audit failed, falling back to text: %s", exc)
                ai_result = self.ai.audit(normalized or raw_text, doc_type_hint=detected_type, language=language)
        else:
            ai_result = self.ai.audit(normalized or raw_text, doc_type_hint=detected_type, language=language)

        # Merge: use AI's detected type if higher confidence
        ai_type = ai_result.get("document_type", "")
        ai_type_confidence = float(ai_result.get("document_type_confidence", 0.0) or 0.0)
        if ai_type and ai_type_confidence > type_confidence:
            final_type = ai_type
        else:
            final_type = detected_type

        # Step 5a: Rule-based validation
        extracted_data = ai_result.get("extracted_data") or {}
        try:
            validation_findings = self.validator.validate(detected_type, extracted_data)
        except Exception as exc:
            logger.warning("ValidationService.validate failed: %s", exc)
            validation_findings = []

        # Step 5b: Risk assessment — now uses real validation findings
        if hasattr(self.risk, "assess"):
            import inspect
            sig = inspect.signature(self.risk.assess)
            if len(sig.parameters) >= 2:
                risk_level = self.risk.assess(ai_result, validation_findings)
            else:
                risk_level = self.risk.assess(ai_result)
        else:
            risk_level = ai_result.get("overall_risk_level", "low") or "low"

        # Step 6: Executive summary
        summary = ai_result.get("executive_summary") or ""

        # Step 7: Confidence
        confidence = ai_result.get("overall_confidence") or ai_result.get("confidence_score")
        if confidence is not None:
            try:
                confidence = float(confidence)
            except (TypeError, ValueError):
                confidence = None

        # Step 8: Save document
        DocumentRepository.save_result(
            doc,
            extracted_text=raw_text[:10000],
            normalized_text=normalized[:10000],
            detected_doc_type=final_type,
            language=language,
            ai_result=ai_result,
            overall_confidence=confidence,
            overall_risk_level=risk_level,
            executive_summary=summary,
        )

        # Step 9: Save findings (AI + validation)
        FindingRepository.bulk_create_from_ai_result(doc, ai_result, validation_findings)

        logger.info(
            "AuditProcessingService: completed document %s | risk=%s | confidence=%s",
            doc.pk,
            risk_level,
            confidence,
        )
        return doc

    def _extract(self, file_path: str, family: str, doc: AuditDocument) -> str:
        language_hint = doc.language or "auto"

        if family == "pdf":
            # Try embedded text first; OCR only if the PDF is image-based.
            text = self.parser.parse_pdf_text(file_path)
            if text and len(text.strip()) > 80:
                return text
            return self._call_ocr(file_path, language_hint)
        elif family == "image":
            return self._call_ocr(file_path, language_hint)
        elif family == "excel":
            return self.parser.parse_excel(file_path)
        elif family == "csv":
            return self.parser.parse_csv(file_path)
        elif family == "json":
            return self.parser.parse_json(file_path)
        elif family == "xml":
            return self.parser.parse_xml(file_path)
        elif family == "text":
            return self.parser.parse_text(file_path)
        elif family == "zip":
            result = self.zip_svc.extract_and_parse(file_path)
            if isinstance(result, dict):
                return result.get("combined_text", "")
            return result or ""
        else:
            logger.warning(
                "AuditProcessingService: unknown file family '%s', attempting OCR",
                family,
            )
            return self._call_ocr(file_path, language_hint)

    def _should_use_vision(self, family: str, raw_text: str) -> bool:
        """Use Vision for images, and for PDFs when extracted text is sparse."""
        if family == "image":
            return True
        if family == "pdf" and (not raw_text or len(raw_text.strip()) < 200):
            return True
        return False

    def _collect_images(self, file_path: str, family: str) -> list:
        """Build a list of image bytes/paths to send to Vision."""
        if family == "image":
            return [file_path]
        if family == "pdf":
            return self.parser.render_pdf_pages(file_path, max_pages=3, dpi=200)
        return []

    def _call_ocr(self, file_path: str, language_hint: str) -> str:
        """Call OCR service with the appropriate method signature."""
        if hasattr(self.ocr, "extract_from_file"):
            return self.ocr.extract_from_file(file_path, language_hint)
        elif hasattr(self.ocr, "extract_pdf"):
            return self.ocr.extract_pdf(file_path)
        elif hasattr(self.ocr, "extract_image"):
            return self.ocr.extract_image(file_path)
        return ""
