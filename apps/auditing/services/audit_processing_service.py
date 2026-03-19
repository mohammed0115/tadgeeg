"""Audit Processing Service — orchestrate the full AI audit pipeline."""

import logging
import os
import traceback

logger = logging.getLogger(__name__)


class AuditProcessingService:
    """Orchestrate the full audit pipeline for a financial document."""

    def __init__(self):
        from apps.auditing.services.file_router import FileRouterService
        from apps.auditing.services.ocr_service import OCRService
        from apps.auditing.services.parser_service import ParserService
        from apps.auditing.services.zip_service import ZipExtractionService
        from apps.auditing.services.normalization_service import TextNormalizationService
        from apps.auditing.services.document_detection_service import DocumentDetectionService
        from apps.auditing.services.ai_auditor_service import AIAuditorService
        from apps.auditing.services.validation_service import ValidationService
        from apps.auditing.services.risk_service import RiskAssessmentService
        from apps.auditing.repositories.document_repository import DocumentRepository
        from apps.auditing.repositories.finding_repository import FindingRepository

        self.file_router = FileRouterService()
        self.ocr = OCRService()
        self.parser = ParserService()
        self.zip_service = ZipExtractionService()
        self.normalizer = TextNormalizationService()
        self.detector = DocumentDetectionService()
        self.ai_auditor = AIAuditorService()
        self.validator = ValidationService()
        self.risk_engine = RiskAssessmentService()
        self.doc_repo = DocumentRepository()
        self.finding_repo = FindingRepository()

    def process(self, document):
        """
        Execute the full audit pipeline:
        1. Mark document as processing
        2. Route file to correct extractor
        3. Extract / parse text
        4. Normalize text
        5. Detect language
        6. Detect document type (heuristic)
        7. Run AI audit
        8. Run validation
        9. Assess risk
        10. Save findings to DB
        11. Update document with results
        12. On any exception: save error, mark as failed
        """
        from apps.auditing.models import AuditDocument

        # Step 1: Mark as processing
        self.doc_repo.update(document, status=AuditDocument.Status.PROCESSING)

        try:
            # Step 2: Route file
            file_path = self._resolve_file_path(document)
            file_family = self.file_router.route(document.original_name)
            logger.info(
                "AuditProcessingService: processing document %s | family=%s | file=%s",
                document.pk, file_family, file_path,
            )

            # Step 3: Extract / parse text
            extracted_text = self._extract_text(document, file_family, file_path)

            # Step 4: Normalize text
            normalized_text = self.normalizer.normalize(extracted_text)

            # Step 5: Detect language
            language = self.normalizer.detect_language(normalized_text)
            if document.language and document.language != "auto":
                language = document.language  # Respect user override
            else:
                language = language or "unknown"

            # Step 6: Heuristic document type detection
            hint = document.selected_doc_type or "auto"
            detected_type, type_confidence = self.detector.detect(normalized_text, hint)
            logger.info(
                "AuditProcessingService: detected_type=%s confidence=%.2f",
                detected_type, type_confidence,
            )

            # Step 7: Run AI audit (text → structured JSON)
            ai_result = self.ai_auditor.audit(
                normalized_text or extracted_text,
                doc_type_hint=detected_type,
            )

            # Merge: use AI's detected type if higher confidence
            ai_type = ai_result.get("document_type", "")
            ai_type_confidence = ai_result.get("document_type_confidence", 0.0)
            if ai_type and ai_type_confidence and float(ai_type_confidence) > type_confidence:
                final_type = ai_type
                final_confidence = float(ai_type_confidence)
            else:
                final_type = detected_type
                final_confidence = type_confidence

            # Step 8: Run validation
            extracted_data = ai_result.get("extracted_data", {})
            validation_findings = self.validator.validate(final_type, extracted_data)

            # Step 9: Assess risk
            risk_level = self.risk_engine.assess(ai_result, validation_findings)

            # Use AI confidence score if available
            ai_confidence = ai_result.get("confidence_score", final_confidence)
            try:
                overall_confidence = float(ai_confidence)
            except (TypeError, ValueError):
                overall_confidence = final_confidence

            # Step 10: Save findings
            self._save_findings(document, ai_result, validation_findings)

            # Step 11: Update document with results
            self.doc_repo.update(
                document,
                status=AuditDocument.Status.COMPLETED,
                extracted_text=extracted_text,
                normalized_text=normalized_text,
                language=language,
                detected_doc_type=final_type,
                ai_result=ai_result,
                overall_confidence=overall_confidence,
                overall_risk_level=risk_level,
                processing_error="",
            )

            logger.info(
                "AuditProcessingService: completed document %s | risk=%s | confidence=%.2f",
                document.pk, risk_level, overall_confidence,
            )

        except Exception as exc:
            error_msg = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
            logger.exception(
                "AuditProcessingService: pipeline failed for document %s: %s",
                document.pk, exc,
            )
            self.doc_repo.update(
                document,
                status=AuditDocument.Status.FAILED,
                processing_error=error_msg[:4000],
            )

        return document

    def _resolve_file_path(self, document) -> str:
        """Return absolute filesystem path to the uploaded file."""
        if not document.file:
            raise ValueError("No file attached to document.")

        file_path = document.file.path
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found on disk: {file_path}")

        return file_path

    def _extract_text(self, document, file_family: str, file_path: str) -> str:
        """Extract text from document based on its file family."""
        language_hint = document.language or "auto"

        if file_family == "pdf":
            return self.ocr.extract_from_file(file_path, language_hint)

        elif file_family == "image":
            return self.ocr.extract_from_file(file_path, language_hint)

        elif file_family == "excel":
            return self.parser.parse_excel(file_path)

        elif file_family == "csv":
            return self.parser.parse_csv(file_path)

        elif file_family == "json":
            return self.parser.parse_json(file_path)

        elif file_family == "zip":
            zip_result = self.zip_service.extract_and_parse(file_path)
            return zip_result.get("combined_text", "")

        else:
            # Unknown — attempt OCR as last resort
            logger.warning(
                "AuditProcessingService: unknown file family '%s' for %s, attempting OCR",
                file_family, document.original_name,
            )
            return self.ocr.extract_from_file(file_path, language_hint)

    def _save_findings(self, document, ai_result: dict, validation: list) -> None:
        """Convert AI anomalies, compliance notes, and validation to AuditFinding records."""
        findings_to_create = []

        # 1. Anomalies from AI
        anomalies = ai_result.get("anomalies", [])
        for anomaly in anomalies:
            if not isinstance(anomaly, dict):
                continue
            severity = anomaly.get("severity", "medium").lower()
            if severity not in ("low", "medium", "high"):
                severity = "medium"
            title = str(anomaly.get("description", anomaly.get("type", "Anomaly")))[:255]
            details_parts = []
            if anomaly.get("affected_field"):
                details_parts.append(f"الحقل المتأثر: {anomaly['affected_field']}")
            if anomaly.get("recommendation"):
                details_parts.append(f"التوصية: {anomaly['recommendation']}")
            findings_to_create.append({
                "finding_type": "anomaly",
                "severity": severity,
                "title": title,
                "details": "\n".join(details_parts),
            })

        # 2. Validation failures & warnings
        for v in validation:
            if not isinstance(v, dict):
                continue
            status = v.get("status", "pass")
            if status == "pass" or status == "not_applicable":
                continue
            severity = "high" if status == "fail" else "low"
            check_name = v.get("check", "validation").replace("_", " ").title()
            findings_to_create.append({
                "finding_type": "validation",
                "severity": severity,
                "title": check_name[:255],
                "details": v.get("details", ""),
            })

        # 3. Compliance issues
        compliance = ai_result.get("compliance_review", {})
        if isinstance(compliance, dict):
            if compliance.get("overall_status") in ("non_compliant", "partially_compliant"):
                notes = compliance.get("notes", [])
                for note in notes:
                    if note:
                        findings_to_create.append({
                            "finding_type": "compliance",
                            "severity": "medium",
                            "title": str(note)[:255],
                            "details": "",
                        })

        # 4. Recommendations
        recommendations = ai_result.get("recommendations", [])
        for rec in recommendations:
            if rec:
                findings_to_create.append({
                    "finding_type": "recommendation",
                    "severity": "low",
                    "title": str(rec)[:255],
                    "details": "",
                })

        if findings_to_create:
            self.finding_repo.bulk_create(document, findings_to_create)
            logger.info(
                "AuditProcessingService: saved %d findings for document %s",
                len(findings_to_create), document.pk,
            )
