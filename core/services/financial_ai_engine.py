"""
Financial Intelligence Engine

The central orchestrator for financial document analysis in FinAI.

This engine takes an ingested document and runs the complete intelligence
pipeline:

  Step 1 — Document Classification
  Step 2 — Field Extraction & Normalization
  Step 3 — Duplicate Detection
  Step 4 — Fraud Detection
  Step 5 — Risk Scoring
  Step 6 — Compliance Validation

It returns a FinancialAnalysisResult that combines all signals into a
single unified output ready for database storage and audit case creation.

The engine is designed to be called from:
  - Celery tasks (background processing)
  - Django views (synchronous for small files)
  - The audit engine (as input to rule evaluation)

Architecture:
  views / tasks
    └── DocumentEngine.ingest()        ← file parsing
          └── FinancialAIEngine.analyse()  ← this module
                ├── DocumentClassifier
                ├── AIExtractor
                ├── DuplicateDetector
                ├── FraudDetector
                ├── RiskEngine
                └── VATValidator
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("finai")


@dataclass
class FinancialAnalysisResult:
    """
    Complete output of the Financial AI Engine for one document.

    All fields are serialisable to JSON for storage in the database.
    """

    # ── Classification ────────────────────────────────────────────────────────
    document_type: str = "other"
    classification_confidence: float = 0.0
    classification_method: str = "unknown"

    # ── Extracted fields ──────────────────────────────────────────────────────
    vendor_name: str = ""
    vendor_name_ar: str = ""
    vendor_vat_number: str = ""
    document_number: str = ""
    date: Optional[str] = None
    due_date: Optional[str] = None
    currency: str = "SAR"
    subtotal: float = 0.0
    vat_rate: float = 15.0
    tax_amount: float = 0.0
    discount: float = 0.0
    total_amount: float = 0.0
    line_items: list = field(default_factory=list)
    payment_terms: str = ""
    notes: str = ""
    language: str = "unknown"
    extraction_tier: str = "none"
    extraction_confidence: float = 0.0

    # ── Duplicate detection ───────────────────────────────────────────────────
    duplicate_score: float = 0.0
    is_duplicate: bool = False
    duplicate_reasons: list = field(default_factory=list)
    matched_document_ids: list = field(default_factory=list)

    # ── Fraud detection ───────────────────────────────────────────────────────
    fraud_score: float = 0.0
    fraud_patterns: list = field(default_factory=list)
    requires_review: bool = False

    # ── Compliance ────────────────────────────────────────────────────────────
    compliance_score: float = 1.0
    vat_valid: bool = True
    missing_fields: list = field(default_factory=list)
    compliance_issues: list = field(default_factory=list)

    # ── Risk ──────────────────────────────────────────────────────────────────
    risk_score: int = 0
    risk_level: str = "low"
    risk_factors: list = field(default_factory=list)
    escalate: bool = False

    # ── Source ────────────────────────────────────────────────────────────────
    source_file: str = ""
    raw_text: str = ""
    processing_errors: list = field(default_factory=list)
    processing_time_ms: int = 0

    def to_dict(self) -> dict:
        return {
            "document_type": self.document_type,
            "classification_confidence": self.classification_confidence,
            "classification_method": self.classification_method,
            "vendor_name": self.vendor_name,
            "vendor_name_ar": self.vendor_name_ar,
            "vendor_vat_number": self.vendor_vat_number,
            "document_number": self.document_number,
            "date": self.date,
            "due_date": self.due_date,
            "currency": self.currency,
            "subtotal": self.subtotal,
            "vat_rate": self.vat_rate,
            "tax_amount": self.tax_amount,
            "discount": self.discount,
            "total_amount": self.total_amount,
            "line_items": self.line_items,
            "payment_terms": self.payment_terms,
            "notes": self.notes,
            "language": self.language,
            "extraction_tier": self.extraction_tier,
            "extraction_confidence": self.extraction_confidence,
            "duplicate_score": self.duplicate_score,
            "is_duplicate": self.is_duplicate,
            "duplicate_reasons": self.duplicate_reasons,
            "matched_document_ids": self.matched_document_ids,
            "fraud_score": self.fraud_score,
            "fraud_patterns": self.fraud_patterns,
            "requires_review": self.requires_review,
            "compliance_score": self.compliance_score,
            "vat_valid": self.vat_valid,
            "missing_fields": self.missing_fields,
            "compliance_issues": self.compliance_issues,
            "risk_score": self.risk_score,
            "risk_level": self.risk_level,
            "risk_factors": self.risk_factors,
            "escalate": self.escalate,
            "source_file": self.source_file,
            "processing_errors": self.processing_errors,
            "processing_time_ms": self.processing_time_ms,
        }


class FinancialAIEngine:
    """
    Financial Intelligence Engine.

    Accepts an IngestionResult from DocumentEngine and produces a
    FinancialAnalysisResult with full analysis.

    Usage:
        from core.services.document_engine import DocumentEngine
        from core.services.financial_ai_engine import FinancialAIEngine

        engine = DocumentEngine()
        ingest = engine.ingest("/path/to/invoice.pdf")

        ai_engine = FinancialAIEngine(organization_id=org.id, country_code="SA")
        result = ai_engine.analyse(ingest)
        print(result.risk_level)
    """

    def __init__(
        self,
        organization_id: int = None,
        country_code: str = "SA",
        use_ai: bool = True,
    ):
        self.organization_id = organization_id
        self.country_code = country_code
        self.use_ai = use_ai

    def analyse(self, ingestion_result) -> FinancialAnalysisResult:
        """
        Run the full financial intelligence pipeline on an ingested document.

        Args:
            ingestion_result: IngestionResult from DocumentEngine.ingest().

        Returns:
            FinancialAnalysisResult
        """
        t_start = time.monotonic()
        result = FinancialAnalysisResult(
            source_file=ingestion_result.file_name,
            raw_text=ingestion_result.raw_text[:5000],
        )

        if not ingestion_result.success:
            result.processing_errors.append(
                f"Ingestion failed: {ingestion_result.fatal_error}"
            )
            result.risk_level = "high"
            result.risk_score = 60
            result.processing_time_ms = int((time.monotonic() - t_start) * 1000)
            return result

        # ── Step 1: Classification ─────────────────────────────────────────────
        try:
            self._step_classify(result, ingestion_result)
        except Exception as exc:
            result.processing_errors.append(f"Classification error: {exc}")
            logger.exception("[FinancialAIEngine] Classification failed")

        # ── Step 2: Field Extraction ───────────────────────────────────────────
        extracted: dict = {}
        try:
            extracted = self._step_extract(result, ingestion_result)
        except Exception as exc:
            result.processing_errors.append(f"Extraction error: {exc}")
            logger.exception("[FinancialAIEngine] Extraction failed")

        # Fallback: use normalised data from ingestion result
        if not extracted:
            extracted = ingestion_result.normalized or {}

        self._apply_extraction(result, extracted)

        # ── Step 3: Duplicate Detection ────────────────────────────────────────
        try:
            self._step_duplicate(result, extracted)
        except Exception as exc:
            result.processing_errors.append(f"Duplicate detection error: {exc}")
            logger.warning("[FinancialAIEngine] Duplicate detection failed: %s", exc)

        # ── Step 4: Fraud Detection ────────────────────────────────────────────
        try:
            self._step_fraud(result, extracted)
        except Exception as exc:
            result.processing_errors.append(f"Fraud detection error: {exc}")
            logger.warning("[FinancialAIEngine] Fraud detection failed: %s", exc)

        # ── Step 5: Compliance Validation ─────────────────────────────────────
        try:
            self._step_compliance(result, extracted)
        except Exception as exc:
            result.processing_errors.append(f"Compliance validation error: {exc}")
            logger.warning("[FinancialAIEngine] Compliance validation failed: %s", exc)

        # ── Step 6: Risk Scoring ───────────────────────────────────────────────
        try:
            self._step_risk(result)
        except Exception as exc:
            result.processing_errors.append(f"Risk scoring error: {exc}")
            logger.exception("[FinancialAIEngine] Risk scoring failed")

        result.processing_time_ms = int((time.monotonic() - t_start) * 1000)

        logger.info(
            "[FinancialAIEngine] Analysed %s | type=%s | risk=%s (%d) | "
            "dup=%.2f | fraud=%.2f | compliance=%.2f | %dms",
            result.source_file,
            result.document_type,
            result.risk_level,
            result.risk_score,
            result.duplicate_score,
            result.fraud_score,
            result.compliance_score,
            result.processing_time_ms,
        )

        return result

    # ── Pipeline steps ────────────────────────────────────────────────────────

    def _step_classify(self, result: FinancialAnalysisResult, ingestion):
        from core.services.classification.document_classifier import DocumentClassifier

        classifier = DocumentClassifier()
        classification = classifier.classify(
            raw_text=ingestion.raw_text,
            structured=ingestion.structured or ingestion.normalized,
            use_ai=self.use_ai,
        )
        result.document_type = classification.get("document_type", "other")
        result.classification_confidence = float(classification.get("confidence", 0.0))
        result.classification_method = classification.get("method", "unknown")

    def _step_extract(self, result: FinancialAnalysisResult, ingestion) -> dict:
        from core.services.extraction.ai_extractor import AIExtractor

        extractor = AIExtractor()
        extracted = extractor.extract(
            raw_text=ingestion.raw_text,
            structured=ingestion.normalized,
            document_type=result.document_type,
        )
        return extracted

    def _step_duplicate(self, result: FinancialAnalysisResult, document: dict):
        from core.services.detection.duplicate_detector import DuplicateDetector

        detector = DuplicateDetector(organization_id=self.organization_id)
        dup_result = detector.detect(document)

        result.duplicate_score = float(dup_result.get("duplicate_score", 0.0))
        result.is_duplicate = bool(dup_result.get("is_duplicate", False))
        result.duplicate_reasons = dup_result.get("duplicate_reasons", [])
        result.matched_document_ids = dup_result.get("matched_document_ids", [])

    def _step_fraud(self, result: FinancialAnalysisResult, document: dict):
        from core.services.detection.fraud_detector import FraudDetector

        detector = FraudDetector(organization_id=self.organization_id)
        fraud_result = detector.detect(document)

        result.fraud_score = float(fraud_result.get("fraud_score", 0.0))
        result.fraud_patterns = fraud_result.get("fraud_patterns", [])
        result.requires_review = bool(fraud_result.get("requires_review", False))

    def _step_compliance(self, result: FinancialAnalysisResult, document: dict):
        from core.services.compliance.vat_validator import VATValidator

        validator = VATValidator(country_code=self.country_code)
        comp_result = validator.validate(document)

        result.compliance_score = float(comp_result.get("compliance_score", 1.0))
        result.vat_valid = bool(comp_result.get("vat_valid", True))
        result.missing_fields = comp_result.get("missing_fields", [])
        result.compliance_issues = comp_result.get("issues", [])

    def _step_risk(self, result: FinancialAnalysisResult):
        from core.services.scoring.risk_engine import RiskEngine

        engine = RiskEngine()
        risk_result = engine.score(
            document=self._result_to_doc(result),
            duplicate_result={
                "duplicate_score": result.duplicate_score,
                "duplicate_reasons": result.duplicate_reasons,
            },
            fraud_result={
                "fraud_score": result.fraud_score,
                "fraud_patterns": result.fraud_patterns,
            },
            compliance_result={
                "compliance_score": result.compliance_score,
                "issues": result.compliance_issues,
            },
        )

        result.risk_score = risk_result.get("risk_score", 0)
        result.risk_level = risk_result.get("risk_level", "low")
        result.risk_factors = risk_result.get("risk_factors", [])
        result.escalate = bool(risk_result.get("escalate", False))

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _apply_extraction(self, result: FinancialAnalysisResult, extracted: dict):
        """Map extracted dict fields to FinancialAnalysisResult attributes."""
        str_fields = [
            "vendor_name", "vendor_name_ar", "vendor_vat_number",
            "document_number", "date", "due_date", "currency",
            "payment_terms", "notes", "language", "extraction_tier",
        ]
        float_fields = [
            "subtotal", "vat_rate", "tax_amount", "discount", "total_amount",
        ]

        for f in str_fields:
            val = extracted.get(f)
            if val:
                setattr(result, f, str(val))

        for f in float_fields:
            val = extracted.get(f)
            if val is not None:
                try:
                    setattr(result, f, float(val))
                except (TypeError, ValueError):
                    pass

        line_items = extracted.get("line_items")
        if line_items and isinstance(line_items, list):
            result.line_items = line_items

        confidence = extracted.get("confidence")
        if confidence is not None:
            result.extraction_confidence = float(confidence)

    def _result_to_doc(self, result: FinancialAnalysisResult) -> dict:
        """Convert FinancialAnalysisResult to a plain dict for risk engine."""
        return {
            "vendor_name": result.vendor_name,
            "vendor_vat_number": result.vendor_vat_number,
            "document_number": result.document_number,
            "date": result.date,
            "currency": result.currency,
            "subtotal": result.subtotal,
            "vat_rate": result.vat_rate,
            "tax_amount": result.tax_amount,
            "total_amount": result.total_amount,
            "line_items": result.line_items,
            "missing_fields": result.missing_fields,
        }


# ── Convenience function ──────────────────────────────────────────────────────

def process_document(
    file_path: str,
    organization_id: int = None,
    country_code: str = "SA",
    use_ai: bool = True,
) -> FinancialAnalysisResult:
    """
    One-call document processing: ingest + analyse.

    Args:
        file_path:       Absolute path to the uploaded file.
        organization_id: Organisation ID for multi-tenant isolation.
        country_code:    ISO country code for compliance rules.
        use_ai:          Whether to use OpenAI.

    Returns:
        FinancialAnalysisResult
    """
    from core.services.document_engine import DocumentEngine

    doc_engine = DocumentEngine(use_ai=use_ai)
    ingestion = doc_engine.ingest(file_path)

    ai_engine = FinancialAIEngine(
        organization_id=organization_id,
        country_code=country_code,
        use_ai=use_ai,
    )
    return ai_engine.analyse(ingestion)
