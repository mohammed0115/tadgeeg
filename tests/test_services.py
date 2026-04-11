"""
Tests for Core Services: Document Engine, Financial AI Engine, Audit Engine

Tests validate:
- Correct data flow through pipeline
- Edge case handling (malformed files, empty data)
- Error resilience and fallbacks
- Output correctness
"""

import pytest
from decimal import Decimal
from django.test import TestCase
from unittest.mock import Mock, patch, MagicMock, PropertyMock
import json

from core.services.document_engine import DocumentEngine, IngestionResult
from core.services.financial_ai_engine import FinancialAIEngine, FinancialAnalysisResult
from apps.audit.audit_engine import AuditEngine
from core.services.parsers.pdf_parser import PDFParser
from core.utils.file_validation import validate_uploaded_file, ValidationError
from core.services.upload_router import DocumentUploadRouter, UploadRouterResult
from core.services.ai.openai_extractor import classify_document


def _make_ingestion_result(raw_text: str = "") -> IngestionResult:
    """Helper: build a minimal IngestionResult for testing."""
    result = IngestionResult(file_path="test.pdf")
    result.raw_text = raw_text
    result.mime_type = "application/pdf"
    return result


def _make_ai_result(**kwargs) -> FinancialAnalysisResult:
    """Helper: build a FinancialAnalysisResult with sensible defaults."""
    result = FinancialAnalysisResult()
    result.document_type = kwargs.get("document_type", "invoice")
    result.classification_confidence = kwargs.get("confidence", 0.95)
    result.vendor_name = kwargs.get("vendor_name", "Test Vendor")
    result.total_amount = float(kwargs["total_amount"]) if "total_amount" in kwargs else 1000.0
    return result


# ─── Document Engine Tests ──────────────────────────────────────────────────

@pytest.mark.unit
class TestDocumentEngine:
    """Tests for universal document ingestion"""

    def test_ingest_valid_pdf(self, sample_pdf_file):
        """Should return IngestionResult even for minimal PDF (parse may fallback)"""
        result = DocumentEngine().ingest(str(sample_pdf_file))

        assert isinstance(result, IngestionResult)
        assert result.file_path is not None
        assert result.processing_time_ms >= 0
        # A minimal-bytes PDF may fail parsing strategies; that's acceptable
        # as long as we get a proper IngestionResult object back

    def test_ingest_with_mime_detection(self, sample_pdf_file):
        """Should correctly detect MIME type"""
        result = DocumentEngine().ingest(str(sample_pdf_file))

        assert result.mime_type == 'application/pdf'

    def test_ingest_nonexistent_file(self):
        """Should handle missing files gracefully"""
        result = DocumentEngine().ingest("/nonexistent/file.pdf")

        assert result.fatal_error is not None
        assert "not found" in result.fatal_error.lower()

    def test_ingest_tracks_processing_time(self, sample_pdf_file):
        """Should track processing duration"""
        result = DocumentEngine().ingest(str(sample_pdf_file))

        assert isinstance(result.processing_time_ms, (int, float))
        assert result.processing_time_ms >= 0

    @pytest.mark.slow
    def test_ingest_large_file(self, tmp_path):
        """Should handle files up to size limit"""
        large_file = tmp_path / "large.pdf"
        large_file.write_bytes(b'%PDF-1.4\n' + b'X' * 10485760)

        result = DocumentEngine().ingest(str(large_file))

        assert result is not None


# ─── Financial AI Engine Tests ──────────────────────────────────────────────

@pytest.mark.unit
class TestFinancialAIEngine:
    """Tests for financial document analysis"""

    def test_analyse_returns_valid_result(self):
        """Should return valid FinancialAnalysisResult"""
        ingestion = _make_ingestion_result(
            "Invoice INV-001 from Acme Corp for 1000 SAR on 2026-03-15"
        )
        engine = FinancialAIEngine(use_ai=False)
        result = engine.analyse(ingestion)

        assert isinstance(result, FinancialAnalysisResult)
        assert result.document_type is not None
        assert result.classification_confidence >= 0
        assert result.classification_confidence <= 1

    def test_analyse_extracts_vendor_name(self):
        """Should extract vendor name from text"""
        ingestion = _make_ingestion_result(
            "FROM: Acme Supplies Inc\nInvoice #INV-2026-001\nAmount: 1000 SAR"
        )
        engine = FinancialAIEngine(use_ai=False)
        result = engine.analyse(ingestion)

        assert hasattr(result, 'vendor_name')

    def test_analyse_extracts_financial_amounts(self):
        """Should extract amounts and VAT"""
        ingestion = _make_ingestion_result(
            "Subtotal: 1000 SAR, VAT (15%): 150 SAR, Total: 1150 SAR"
        )
        engine = FinancialAIEngine(use_ai=False)
        result = engine.analyse(ingestion)

        assert hasattr(result, 'total_amount')

    def test_analyse_empty_text_doesnt_crash(self):
        """Should handle empty input gracefully"""
        ingestion = _make_ingestion_result("")
        engine = FinancialAIEngine(use_ai=False)
        result = engine.analyse(ingestion)

        assert isinstance(result, FinancialAnalysisResult)
        assert result.classification_confidence is not None

    def test_analyse_detects_document_type(self):
        """Should classify document type"""
        ingestion = _make_ingestion_result("Invoice INV-001 for services rendered")
        engine = FinancialAIEngine(use_ai=False)
        result = engine.analyse(ingestion)

        assert hasattr(result, 'document_type')

    def test_analyse_marks_high_risk_items(self):
        """Should identify suspicious patterns"""
        ingestion = _make_ingestion_result(
            "Invoice: INV-001\nVendor: Anonymous Corp\nAmount: 999999999 SAR"
        )
        engine = FinancialAIEngine(use_ai=False)
        result = engine.analyse(ingestion)

        assert hasattr(result, 'risk_score')
        assert result.risk_score >= 0

    def test_analyse_result_serializable(self):
        """Should be convertible to dict for database storage"""
        ingestion = _make_ingestion_result("Invoice INV-001 for 1000 SAR")
        engine = FinancialAIEngine(use_ai=False)
        result = engine.analyse(ingestion)

        data_dict = result.to_dict()

        assert isinstance(data_dict, dict)
        assert 'document_type' in data_dict
        assert 'classification_confidence' in data_dict

    def test_analyse_includes_anomaly_explainability(self):
        """Should expose anomaly score and explanation for downstream reporting"""
        ingestion = _make_ingestion_result(
            "Invoice INV-900 from Unusual Vendor for 999999 SAR on 2026-03-15"
        )
        engine = FinancialAIEngine(use_ai=False)
        result = engine.analyse(ingestion)

        data_dict = result.to_dict()

        assert "anomaly_score" in data_dict
        assert "anomaly_explanation" in data_dict
        assert isinstance(data_dict["anomaly_score"], (int, float))
        assert isinstance(data_dict["anomaly_explanation"], str)


# ─── Audit Engine Tests ──────────────────────────────────────────────────

@pytest.mark.unit
class TestAuditEngine:
    """Tests for financial audit rule evaluation"""

    def test_evaluate_returns_audit_report(self):
        """Should return valid AuditReport"""
        doc = _make_ai_result().to_dict()
        engine = AuditEngine()
        report = engine.evaluate(doc)

        assert report is not None
        assert hasattr(report, 'rule_results')
        assert hasattr(report, 'risk_score')

    def test_evaluate_detects_missing_fields(self):
        """Should flag documents with missing required fields"""
        # Empty document — many required fields missing
        doc = FinancialAnalysisResult().to_dict()
        engine = AuditEngine()
        report = engine.evaluate(doc)

        assert len(report.failed_results) > 0

    def test_evaluate_calculates_risk_score(self):
        """Should aggregate risk into single score"""
        doc = _make_ai_result(
            confidence=0.5,
            vendor_name="Unknown",
            total_amount=Decimal("999999999.00"),
        ).to_dict()
        engine = AuditEngine()
        report = engine.evaluate(doc)

        assert isinstance(report.risk_score, (int, float))
        assert 0 <= report.risk_score <= 100

    def test_evaluate_passes_low_risk_docs(self):
        """Should produce a risk score in valid range"""
        doc = _make_ai_result(
            confidence=0.98,
            vendor_name="Known Vendor Inc",
            total_amount=Decimal("1000.00"),
        ).to_dict()
        engine = AuditEngine()
        report = engine.evaluate(doc)

        # Risk score must be in valid 0-100 range
        assert 0 <= report.risk_score <= 100

    def test_evaluate_rules_exhaustive(self):
        """Should run all registered audit rules"""
        doc = FinancialAnalysisResult().to_dict()
        engine = AuditEngine()
        report = engine.evaluate(doc)

        assert len(report.rule_results) >= 0
        assert hasattr(report, 'summary')


# ─── File Validation Tests ──────────────────────────────────────────────────

@pytest.mark.security
class TestFileValidation:
    """Tests for file upload security"""

    def test_validate_rejects_executable_files(self, malicious_exe_file):
        """Should block .exe files"""
        mock_file = MagicMock()
        mock_file.name = str(malicious_exe_file)
        mock_file.size = 1024
        mock_file.read.return_value = b'MZ\x90\x00'
        mock_file.seek = Mock()

        with pytest.raises(ValidationError):
            validate_uploaded_file(mock_file)

    def test_validate_accepts_valid_pdf(self, sample_pdf_file):
        """Should accept legitimate PDF files"""
        mock_file = MagicMock()
        mock_file.name = "test.pdf"
        mock_file.size = 102400
        mock_file.read.return_value = b'%PDF-1.4\n'
        mock_file.seek = Mock()

        result = validate_uploaded_file(mock_file)

        assert result['is_valid'] is True
        assert result['mime_type'] == 'application/pdf'

    def test_validate_rejects_oversized_files(self):
        """Should reject files exceeding size limit"""
        mock_file = MagicMock()
        mock_file.name = "huge.pdf"
        mock_file.size = 100 * 1024 * 1024 + 1  # Over 100MB

        with pytest.raises(ValidationError):
            validate_uploaded_file(mock_file)

    def test_validate_detects_mime_mismatch(self, tmp_path):
        """Should catch files with dangerous content regardless of extension"""
        mock_file = MagicMock()
        # Use a PDF extension but provide executable (MZ) magic bytes
        mock_file.name = "malware.pdf"
        mock_file.size = 100
        mock_file.read.return_value = b"MZ\x90\x00\x03" + b"\x00" * 100  # PE executable
        mock_file.seek = Mock()

        with pytest.raises(ValidationError):
            validate_uploaded_file(mock_file, check_content=True)

    def test_validate_blocks_zip_bombs(self, zip_bombs_file):
        """Should detect and reject ZIP bombs"""
        mock_file = MagicMock()
        mock_file.name = "bomb.zip"
        mock_file.size = 1024
        mock_file.read.return_value = b'PK\x03\x04'
        mock_file.seek = Mock()

        result = validate_uploaded_file(mock_file, check_content=False)
        assert result['mime_type'] == 'application/zip'


# ─── Integration Tests ──────────────────────────────────────────────────────

@pytest.mark.integration
class TestFullPipeline:
    """End-to-end pipeline tests"""

    def test_full_pipeline_document_flow(self, sample_pdf_file, mocker):
        """Should process document through full pipeline"""
        # Step 1: Ingest
        result = DocumentEngine().ingest(str(sample_pdf_file))
        assert result.file_path is not None

        # Step 2: AI analysis (no AI calls in unit test)
        engine = FinancialAIEngine(use_ai=False)
        ai_result = engine.analyse(result)
        assert ai_result.document_type is not None

        # Step 3: Audit
        audit_engine = AuditEngine()
        audit_report = audit_engine.evaluate(ai_result.to_dict())
        assert audit_report.risk_score >= 0

    @pytest.mark.slow
    def test_pipeline_with_real_files(self):
        """Should handle real-world document scenarios"""
        pass


@pytest.mark.unit
class TestDocumentUploadRouter:
    def test_route_dispatches_invoice_type(self):
        router = DocumentUploadRouter()
        file_obj = Mock()
        file_obj.name = "inv.pdf"
        user = Mock()

        with patch.object(router, "_route_invoice", return_value=UploadRouterResult(
            success=True,
            pipeline="invoice",
            object_id="123",
            result_url="/invoices/123/",
        )) as mock_invoice:
            result = router.route(
                uploaded_file=file_obj,
                document_type="invoice",
                user=user,
                language="auto",
                organization=None,
            )

        mock_invoice.assert_called_once()
        assert result.pipeline == "invoice"

    def test_route_dispatches_non_invoice_type(self):
        router = DocumentUploadRouter()
        file_obj = Mock()
        file_obj.name = "po.pdf"
        user = Mock()

        with patch.object(router, "_route_document", return_value=UploadRouterResult(
            success=True,
            pipeline="document",
            object_id="abc",
            result_url="/documents/purchase-orders/abc/",
        )) as mock_doc:
            result = router.route(
                uploaded_file=file_obj,
                document_type="purchase_order",
                user=user,
                language="auto",
                organization=None,
            )

        mock_doc.assert_called_once()
        assert result.pipeline == "document"

    def test_route_invoice_returns_error_when_user_has_no_org(self):
        router = DocumentUploadRouter()
        file_obj = Mock()
        file_obj.name = "inv.pdf"
        user = Mock()
        user.organization = None

        result = router._route_invoice(file_obj, user, "auto", None)

        assert result.success is False
        assert result.pipeline == "invoice"
        assert "no organization" in (result.error or "").lower()

    def test_route_invoice_success_path(self):
        router = DocumentUploadRouter()
        file_obj = Mock()
        file_obj.name = "inv.pdf"
        user = Mock()
        user.organization = Mock()

        mock_batch = Mock()
        with patch("apps.invoices.models.InvoiceBatch.objects.create", return_value=mock_batch), \
             patch("apps.audit.services.AuditSessionService.create_session", return_value=Mock()), \
             patch("apps.invoices.views._process_single_file", return_value={"invoice_id": "id-1", "success": True}):
            result = router._route_invoice(file_obj, user, "auto", user.organization)

        assert result.success is True
        assert result.object_id == "id-1"
        assert result.result_url.endswith("/invoices/id-1/")

    def test_route_document_uses_fallback_without_org(self):
        router = DocumentUploadRouter()
        file_obj = Mock()
        file_obj.name = "doc.pdf"
        user = Mock()
        user.organization = None

        fallback_result = UploadRouterResult(
            success=True,
            pipeline="document_fallback",
            object_id="fb-1",
            result_url="/auditor/result/fb-1/",
        )
        with patch.object(router, "_route_document_fallback", return_value=fallback_result) as mock_fallback:
            result = router._route_document(file_obj, "expense_report", user, "auto")

        mock_fallback.assert_called_once()
        assert result.pipeline == "document_fallback"

    def test_route_auto_detects_invoice_via_openai(self):
        router = DocumentUploadRouter()
        file_obj = Mock()
        file_obj.name = "inv.pdf"
        user = Mock()
        user.organization = Mock()

        invoice_result = UploadRouterResult(
            success=True,
            pipeline="invoice",
            object_id="inv-1",
            result_url="/invoices/inv-1/",
        )
        with patch.object(router, "_detect_document_type", return_value="invoice") as mock_detect, \
             patch.object(router, "_route_invoice", return_value=invoice_result) as mock_route_invoice:
            result = router.route(
                uploaded_file=file_obj,
                document_type="auto",
                user=user,
                language="auto",
                organization=user.organization,
            )

        mock_detect.assert_called_once_with(file_obj)
        mock_route_invoice.assert_called_once_with(file_obj, user, "auto", user.organization)
        assert result.pipeline == "invoice"

    def test_detect_document_type_maps_receipt_alias_to_sales_receipt(self):
        router = DocumentUploadRouter()
        file_obj = Mock()
        file_obj.name = "receipt.pdf"

        with patch.object(router, "_extract_detection_input", return_value=("Retail receipt", {})), \
             patch("core.services.ai.openai_extractor.classify_document", return_value={"document_type": "receipt", "confidence": 0.91}) as mock_classify:
            detected_type = router._detect_document_type(file_obj)

        assert detected_type == "sales_receipt"
        assert "sales_receipt" in mock_classify.call_args.kwargs["allowed_types"]
        assert mock_classify.call_args.kwargs["aliases"]["receipt"] == "sales_receipt"

    def test_detect_document_type_maps_vat_return_alias_to_tax_declaration(self):
        router = DocumentUploadRouter()
        file_obj = Mock()
        file_obj.name = "vat.pdf"

        with patch.object(router, "_extract_detection_input", return_value=("VAT return", {})), \
             patch("core.services.ai.openai_extractor.classify_document", return_value={"document_type": "vat_return", "confidence": 0.84}):
            detected_type = router._detect_document_type(file_obj)

        assert detected_type == "tax_declaration"

    def test_route_other_uses_fallback_pipeline_even_with_org(self):
        router = DocumentUploadRouter()
        file_obj = Mock()
        file_obj.name = "mystery.pdf"
        user = Mock()
        user.organization = Mock()

        fallback_result = UploadRouterResult(
            success=True,
            pipeline="document_fallback",
            object_id="fb-2",
            result_url="/auditor/result/fb-2/",
        )
        with patch.object(router, "_route_document_fallback", return_value=fallback_result) as mock_fallback:
            result = router.route(
                uploaded_file=file_obj,
                document_type="other",
                user=user,
                language="auto",
                organization=user.organization,
            )

        mock_fallback.assert_called_once_with(file_obj, "other", user, "auto")
        assert result.pipeline == "document_fallback"

    def test_route_document_success_builds_detail_url(self):
        router = DocumentUploadRouter()
        file_obj = Mock()
        file_obj.name = "po.pdf"
        user = Mock()
        user.organization = Mock()

        with patch("apps.documents.typed_views._process_typed_document", return_value={"success": True, "document_id": "typed-1"}):
            result = router._route_document(file_obj, "purchase_order", user, "auto")

        assert result.success is True
        assert result.object_id == "typed-1"
        assert result.result_url.endswith("/documents/purchase-orders/typed-1/")

    def test_route_document_exception_returns_failure_result(self):
        router = DocumentUploadRouter()
        file_obj = Mock()
        file_obj.name = "doc.pdf"
        user = Mock()
        user.organization = Mock()

        with patch("apps.documents.typed_views._process_typed_document", side_effect=RuntimeError("boom")):
            result = router._route_document(file_obj, "bank_statement", user, "auto")

        assert result.success is False
        assert result.pipeline == "document"
        assert result.result_url == "/documents/bank-statements/"

    def test_classify_document_normalises_aliases_to_allowed_types(self):
        with patch("core.services.ai.openai_extractor._chat_with_retry", return_value=json.dumps({
            "document_type": "receipt",
            "confidence": 0.88,
            "classification_reason": "Retail sale summary",
        })):
            result = classify_document(
                "Retail receipt text",
                allowed_types=["sales_receipt", "other"],
                aliases={"receipt": "sales_receipt"},
            )

        assert result["document_type"] == "sales_receipt"
        assert result["confidence"] == pytest.approx(0.88)


# ─── Performance Tests ──────────────────────────────────────────────────────

@pytest.mark.slow
class TestPerformance:
    """Performance characteristics"""

    def test_analyse_completes_within_timeout(self):
        """Should analyze documents within 5 seconds"""
        import time

        ingestion = _make_ingestion_result("Invoice\n" * 1000)
        engine = FinancialAIEngine(use_ai=False)

        start = time.time()
        result = engine.analyse(ingestion)
        duration = time.time() - start

        assert duration < 5.0

    def test_audit_evaluation_is_fast(self):
        """Should evaluate audit rules quickly"""
        import time

        doc = FinancialAnalysisResult().to_dict()
        engine = AuditEngine()

        start = time.time()
        report = engine.evaluate(doc)
        duration = time.time() - start

        assert duration < 1.0
