import shutil
import tempfile
from unittest.mock import Mock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.audit.models import AuditSession
from apps.audit.services import AuditSessionService
from apps.authentication.models import Organization, User
from apps.invoices.models import Invoice, InvoiceBatch


class AuditSessionServiceTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(
            name="Test Organization",
            name_ar="منظمة الاختبار",
            country=Organization.Country.SAUDI_ARABIA,
            currency=Organization.Currency.SAR,
            vat_number="300000000000003",
        )
        self.user = User.objects.create_user(
            email="admin@test.finai",
            password="TestPass123!",
            full_name="Admin User",
            role=User.Role.ADMIN,
            organization=self.organization,
            is_staff=True,
        )

    def test_valid_state_transitions_are_enforced(self):
        session = AuditSessionService.create_session(
            organization=self.organization,
            created_by=self.user,
            name="March invoices",
            total_count=2,
        )

        AuditSessionService.advance_to_extracting(session)
        session.refresh_from_db()
        self.assertEqual(session.status, AuditSession.Status.EXTRACTING)

        AuditSessionService.advance_to_normalizing(session)
        session.refresh_from_db()
        self.assertEqual(session.status, AuditSession.Status.NORMALIZING)

        AuditSessionService.advance_to_validating(session)
        session.refresh_from_db()
        self.assertEqual(session.status, AuditSession.Status.VALIDATING)

        with self.assertRaises(ValueError):
            AuditSessionService.transition(session, AuditSession.Status.RECEIVED)

    def test_session_becomes_failed_when_everything_fails(self):
        session = AuditSessionService.create_session(
            organization=self.organization,
            created_by=self.user,
            total_count=1,
        )

        AuditSessionService.record_failure(session, "OCR failed")
        session.refresh_from_db()

        self.assertEqual(session.status, AuditSession.Status.FAILED)
        self.assertEqual(session.failed_count, 1)
        self.assertEqual(session.processed_count, 1)
        self.assertEqual(session.last_error, "OCR failed")


class AuditSessionUploadTests(TestCase):
    def setUp(self):
        self.media_dir = tempfile.mkdtemp(prefix="audit-session-tests-")
        self.override = override_settings(MEDIA_ROOT=self.media_dir)
        self.override.enable()

        self.organization = Organization.objects.create(
            name="Upload Org",
            name_ar="منظمة الرفع",
            country=Organization.Country.SAUDI_ARABIA,
            currency=Organization.Currency.SAR,
            vat_number="300000000000003",
        )
        self.user = User.objects.create_user(
            email="auditor@test.finai",
            password="TestPass123!",
            full_name="Senior Auditor",
            role=User.Role.SENIOR_AUDITOR,
            organization=self.organization,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media_dir, ignore_errors=True)

    def _ingestion_result(self):
        ingestion = Mock()
        ingestion.fatal_error = ""
        ingestion.raw_text = "Invoice text"
        ingestion.extraction_method = "mock_parser"
        ingestion.metadata = {"ocr_confidence": 98.0, "is_handwritten": False}
        ingestion.normalized = {}
        ingestion.structured = {}
        return ingestion

    def _analysis_result(self, *, requires_review=False):
        analysis = Mock()
        analysis.risk_score = 34.0
        analysis.fraud_score = 0.12
        analysis.is_duplicate = False
        analysis.requires_review = requires_review
        analysis.to_dict.return_value = {
            "risk_score": 34.0,
            "requires_review": requires_review,
        }
        return analysis

    def _ai_data(self):
        return {
            "invoice_number": "INV-1001",
            "invoice_date": "2026-03-17",
            "due_date": "2026-03-31",
            "vendor_name": "Demo Vendor",
            "vendor_name_ar": "",
            "vendor_vat_number": "300000000000003",
            "vendor_cr_number": "1010101010",
            "vendor_address": "Riyadh",
            "vendor_phone": "0500000000",
            "customer_name": "Customer",
            "customer_vat_number": "",
            "currency": "SAR",
            "subtotal": 100.0,
            "vat_rate": 15.0,
            "vat_amount": 15.0,
            "discount": 0.0,
            "total_amount": 115.0,
            "line_items": [],
            "has_qr_code": True,
            "qr_code_valid": True,
            "is_handwritten": False,
            "is_clear": True,
            "has_alterations": False,
            "language": "en",
            "ai_summary": "Looks good",
        }

    def _validation_result(self):
        return {
            "passed_rule_codes": [
                "INV-001", "INV-002", "INV-003", "INV-004", "INV-005", "INV-006", "INV-007", "INV-008",
                "VAT-001", "VAT-002", "VAT-003", "VAT-004", "VAT-005",
                "CTL-001", "CTL-002", "CTL-005",
                "DOC-001", "DOC-002", "DOC-003", "DOC-004",
            ],
            "failed_rule_codes": [],
            "rules_passed": 20,
            "rules_failed": 0,
            "validation_score": 100.0,
            "rule_details": {},
        }

    @patch("apps.invoices.views.pdf_to_images", return_value=[])
    @patch("apps.invoices.views.analyze_invoice_risk")
    @patch("apps.invoices.views.ValidationPipelineService.validate_invoice")
    @patch("apps.audit.audit_engine.run_audit", return_value=None)
    @patch("core.services.financial_ai_engine.FinancialAIEngine.analyse")
    @patch("apps.invoices.views.extract_invoice_with_ai")
    @patch("core.services.document_engine.DocumentEngine.ingest")
    def test_upload_creates_audit_session_and_links_batch(
        self,
        mock_ingest,
        mock_extract,
        mock_analyse,
        _mock_run_audit,
        mock_validation_pipeline,
        mock_ai_risk,
        _mock_pdf,
    ):
        mock_ingest.return_value = self._ingestion_result()
        mock_extract.return_value = self._ai_data()
        mock_analyse.return_value = self._analysis_result()
        mock_validation_pipeline.return_value = {**self._validation_result(), "findings_summary": {}}
        mock_ai_risk.return_value = {
            "overall_risk_score": 34.0,
            "risk_level": "low",
            "recommendations": ["No action needed"],
            "ai_summary": "Stable invoice",
        }

        upload = SimpleUploadedFile("invoice.pdf", b"%PDF-1.4\nmock", content_type="application/pdf")
        response = self.client.post(
            reverse("invoice-upload"),
            {"files": [upload], "batch_name": "Session A"},
            format="multipart",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["processed"], 1)
        self.assertEqual(response.data["failed"], 0)
        self.assertTrue(response.data["audit_session_id"])

        batch = InvoiceBatch.objects.get(pk=response.data["batch_id"])
        session = AuditSession.objects.get(pk=response.data["audit_session_id"])
        invoice = Invoice.objects.get(batch=batch)

        self.assertEqual(batch.audit_session_id, session.id)
        self.assertEqual(invoice.audit_session_id, session.id)
        self.assertEqual(session.status, AuditSession.Status.COMPLETED)
        self.assertEqual(session.success_count, 1)
        self.assertEqual(session.processed_count, 1)

    @patch("apps.invoices.views.pdf_to_images", return_value=[])
    @patch("apps.invoices.views.analyze_invoice_risk")
    @patch("apps.invoices.views.ValidationPipelineService.validate_invoice")
    @patch("apps.audit.audit_engine.run_audit", return_value=None)
    @patch("core.services.financial_ai_engine.FinancialAIEngine.analyse")
    @patch("apps.invoices.views.extract_invoice_with_ai")
    @patch("core.services.document_engine.DocumentEngine.ingest")
    def test_duplicate_file_inside_same_upload_is_blocked(
        self,
        mock_ingest,
        mock_extract,
        mock_analyse,
        _mock_run_audit,
        mock_validation_pipeline,
        mock_ai_risk,
        _mock_pdf,
    ):
        mock_ingest.return_value = self._ingestion_result()
        mock_extract.return_value = self._ai_data()
        mock_analyse.return_value = self._analysis_result()
        mock_validation_pipeline.return_value = {**self._validation_result(), "findings_summary": {}}
        mock_ai_risk.return_value = {
            "overall_risk_score": 34.0,
            "risk_level": "low",
            "recommendations": ["No action needed"],
            "ai_summary": "Stable invoice",
        }

        upload_a = SimpleUploadedFile("invoice-a.pdf", b"%PDF-1.4\nsame-content", content_type="application/pdf")
        upload_b = SimpleUploadedFile("invoice-b.pdf", b"%PDF-1.4\nsame-content", content_type="application/pdf")

        response = self.client.post(
            reverse("invoice-upload"),
            {"files": [upload_a, upload_b], "batch_name": "Session duplicates"},
            format="multipart",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["processed"], 1)
        self.assertEqual(response.data["failed"], 1)
        self.assertTrue(len(response.data["errors"][0]["error"]) > 0)  # duplicate file error returned

        session = AuditSession.objects.get(pk=response.data["audit_session_id"])
        self.assertEqual(Invoice.objects.filter(audit_session=session).count(), 1)
        self.assertEqual(session.failed_count, 1)
        self.assertEqual(session.success_count, 1)
        self.assertEqual(session.status, AuditSession.Status.REVIEW_REQUIRED)

    def test_progress_endpoint_returns_machine_readable_rollup(self):
        session = AuditSessionService.create_session(
            organization=self.organization,
            created_by=self.user,
            name="Tracked session",
            total_count=3,
        )
        AuditSessionService.advance_to_extracting(session)
        session.refresh_from_db()

        response = self.client.get(reverse("session-progress", args=[session.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], AuditSession.Status.EXTRACTING)
        self.assertEqual(response.data["total_count"], 3)
        self.assertEqual(response.data["progress_percent"], 0)
