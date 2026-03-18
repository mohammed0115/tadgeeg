from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.audit.models import AuditFinding, AuditSession
from apps.audit.services import AuditSessionService
from apps.authentication.models import Organization, User
from apps.invoices.models import Invoice
from core.services.validation_pipeline import ValidationPipelineService


class AuditFindingPipelineTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(
            name="Findings Org",
            name_ar="منظمة الملاحظات",
            country=Organization.Country.SAUDI_ARABIA,
            currency=Organization.Currency.SAR,
            vat_number="300000000000003",
        )
        self.user = User.objects.create_user(
            email="auditor@findings.test",
            password="TestPass123!",
            full_name="Findings Auditor",
            role=User.Role.SENIOR_AUDITOR,
            organization=self.organization,
        )
        self.session = AuditSessionService.create_session(
            organization=self.organization,
            created_by=self.user,
            total_count=1,
        )
        self.invoice = Invoice.objects.create(
            organization=self.organization,
            uploaded_by=self.user,
            audit_session=self.session,
            original_filename="invoice.pdf",
            invoice_number="INV-500",
            invoice_date=date(2026, 3, 17),
            vendor_name="Vendor X",
            vendor_vat_number="",
            currency=Invoice.Currency.SAR,
            subtotal=Decimal("100.00"),
            vat_amount=Decimal("15.00"),
            vat_rate=Decimal("15.00"),
            total_amount=Decimal("115.00"),
            has_qr_code=False,
            qr_code_valid=False,
            has_alterations=True,
            is_clear=True,
            ocr_confidence=96,
            extracted_data={"file_hash": "abc123"},
        )

    def test_validation_pipeline_creates_and_resolves_findings(self):
        result = ValidationPipelineService.validate_invoice(
            invoice=self.invoice,
            organization=self.organization,
            file_hash="abc123",
            created_by=self.user,
        )

        self.assertIn("VAT-004", result["failed_rule_codes"])
        self.assertIn("DOC-003", result["failed_rule_codes"])
        self.assertTrue(
            AuditFinding.objects.filter(invoice=self.invoice, rule_code="DOC-003", status=AuditFinding.Status.OPEN).exists()
        )

        self.invoice.vendor_vat_number = "300000000000003"
        self.invoice.has_qr_code = True
        self.invoice.qr_code_valid = True
        self.invoice.has_alterations = False
        self.invoice.cost_center = "FIN-01"
        self.invoice.account_code = "4000"
        self.invoice.approved_by = self.user
        self.invoice.save()

        ValidationPipelineService.validate_invoice(
            invoice=self.invoice,
            organization=self.organization,
            file_hash="abc123",
            created_by=self.user,
        )

        self.assertEqual(
            AuditFinding.objects.get(invoice=self.invoice, rule_code="DOC-003").status,
            AuditFinding.Status.RESOLVED,
        )
        self.assertEqual(
            AuditFinding.objects.get(invoice=self.invoice, rule_code="VAT-004").status,
            AuditFinding.Status.RESOLVED,
        )

    def test_session_escalates_to_action_required_when_critical_findings_exist(self):
        ValidationPipelineService.validate_invoice(
            invoice=self.invoice,
            organization=self.organization,
            file_hash="abc123",
            created_by=self.user,
        )

        self.session.status = AuditSession.Status.VALIDATING
        self.session.total_count = 1
        self.session.processed_count = 1
        self.session.success_count = 1
        self.session.save()

        AuditSessionService.finalize_if_ready(self.session)
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, AuditSession.Status.ACTION_REQUIRED)
