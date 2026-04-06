import uuid
from decimal import Decimal
from types import SimpleNamespace

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from apps.authentication.models import Organization, User
from apps.documents.models import Document, DocumentAnalysisResult
from apps.documents.serializers import DocumentAnalysisResultSerializer, DocumentSerializer
from apps.reports.services.invoice_audit_service import InvoiceAuditReportService


class DocumentAnalysisExplainabilitySerializerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(name="Anomaly Org")
        cls.user = User.objects.create_user(
            email="anomaly@example.com",
            password="StrongPass123!",
            full_name="Anomaly Reviewer",
            organization=cls.organization,
            role=User.Role.ADMIN,
        )

    def test_document_analysis_serializers_expose_anomaly_score_and_explanation(self):
        document = Document.objects.create(
            organization=self.organization,
            uploaded_by=self.user,
            file=SimpleUploadedFile("invoice.pdf", b"pdf-bytes", content_type="application/pdf"),
            original_filename="invoice.pdf",
            file_size=9,
            mime_type="application/pdf",
            document_type=Document.DocumentType.INVOICE,
            processing_status=Document.ProcessingStatus.COMPLETED,
        )
        analysis = DocumentAnalysisResult.objects.create(
            document=document,
            ai_document_type="invoice",
            vendor_name="Risky Vendor",
            document_number="INV-900",
            currency="SAR",
            risk_score=86,
            risk_level=DocumentAnalysisResult.RiskLevel.HIGH,
            analysis_data={
                "anomaly_score": 86,
                "anomaly_explanation": "Duplicate pattern and unusual price spike detected.",
                "anomaly_findings": [
                    {"code": "duplicate_pattern", "severity": "critical"},
                    {"code": "price_zscore_critical", "severity": "high"},
                ],
                "anomaly_methods": ["z_score", "iqr", "duplicate_pattern"],
            },
        )

        detail_data = DocumentAnalysisResultSerializer(analysis).data
        summary_data = DocumentSerializer(document).data["analysis_summary"]

        self.assertEqual(detail_data["anomaly_score"], 86)
        self.assertIn("Duplicate pattern", detail_data["anomaly_explanation"])
        self.assertEqual(detail_data["anomaly_findings"][0]["code"], "duplicate_pattern")
        self.assertIn("z_score", detail_data["anomaly_methods"])
        self.assertEqual(summary_data["anomaly_score"], 86)
        self.assertIn("price spike", summary_data["anomaly_explanation"])


class InvoiceAuditReportExplainabilityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(name="Report Anomaly Org")
        cls.user = User.objects.create_user(
            email="reports@example.com",
            password="StrongPass123!",
            full_name="Reports User",
            organization=cls.organization,
            role=User.Role.ADMIN,
        )

    def test_anomalies_section_includes_explainability_metadata(self):
        service = InvoiceAuditReportService(self.organization, self.user)
        invoice_id = uuid.uuid4()
        invoices = [
            SimpleNamespace(
                id=invoice_id,
                invoice_number="INV-900",
                vendor_name="Risky Vendor",
                total_amount=Decimal("99999.00"),
                currency="SAR",
                is_duplicate=True,
                risk_level="high",
                risk_score=82,
            )
        ]

        anomalies = service._build_anomalies(
            invoices=invoices,
            validations={},
            risk_summaries={
                str(invoice_id): SimpleNamespace(
                    score_breakdown={
                        "anomaly_score": 82,
                        "anomaly_explanation": "Duplicate pattern and unusual frequency spike.",
                        "anomaly_flags": ["duplicate_pattern", "frequency_spike"],
                        "anomaly_methods": ["z_score", "iqr", "duplicate_pattern", "frequency"],
                    }
                )
            },
        )

        self.assertIn("summary", anomalies)
        self.assertIn("top_anomalous_documents", anomalies)
        self.assertIn("explainability", anomalies)
        self.assertEqual(anomalies["explainability"]["scoring_scale"], "0-100")
        self.assertIn("frequency", anomalies["explainability"]["methods_used"])
        self.assertIn("Duplicate pattern", anomalies["top_anomalous_documents"][0]["explanation"])
