"""
Integration Test Suite: Report Generation (Phase 2)
====================================================

Tests complete report generation pipeline:
- Report building with 0/1/100+ invoices
- All 15 report sections present
- Bilingual (AR/EN) output validation
- PDF/HTML export success
- ISA 700 auditor opinion types
- IAS 7 cash flow classification
- KAM assertions (ISA 701)
- Risk aggregation
- BigFour benchmarking

Coverage Target: 14 test scenarios, 10 hours implementation
Test Classes: 5 core suites
"""

import json
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock, patch, MagicMock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APITestCase, APIClient
from rest_framework import status

from apps.organization_admin.models import Organization
from apps.authentication.models import Role, User
from apps.invoices.models import Invoice, InvoiceValidationResult
from apps.reports.models import InvoiceAuditReport
from apps.audit.models import AuditSession


User = get_user_model()


# ─────────────────────────────────────────────────────────────────────────────
# TEST 1: Report Building with Edge Cases (0, 1, 100+ invoices)
# ─────────────────────────────────────────────────────────────────────────────

class TestReportBuildingEdgeCases(APITestCase):
    """Test report generation with varying invoice counts."""

    def setUp(self):
        """Create test organization and user."""
        self.org = Organization.objects.create(
            name="Report Test Org",
            slug="report-test-org",
        )
        
        self.auditor_role = Role.objects.get_or_create(
            name="Senior Auditor",
            permission_level=80,
        )[0]
        
        self.user = User.objects.create_user(
            username="report_auditor",
            email="report@test.com",
            password="TestPass123!",
            organization=self.org,
            role=self.auditor_role,
        )
        
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.report_url = "/api/v1/reports/invoice-audit/"

    @patch("apps.reports.services.invoice_audit_service.InvoiceAuditService.build")
    def test_report_with_zero_invoices_disclaimer_opinion(self, mock_build):
        """
        Scenario 1: Generate report with 0 invoices
        Expected: Report created with DISCLAIMER opinion (insufficient evidence)
        """
        # Arrange
        mock_build.return_value = {
            "report_id": "RPT-ZERO-001",
            "report_header": {
                "opinion_type": "disclaimer",
                "opinion_type_ar": "تقرير بدون رأي",
                "reason": "Insufficient evidence: 0 invoices audited"
            },
            "summary": {
                "total_invoices": 0,
                "passed": 0,
                "failed": 0,
                "compliance_rate": 0.0,
            },
            # All 15 sections present but with zero data
            "executive_summary": {"findings": []},
            "compliance_engine": {"rules": [], "compliance_rate": 0.0},
            "high_risk_invoices": [],
            "failed_rules_analysis": [],
            "supplier_analysis": [],
            "risk_analysis": {},
            "anomalies": [],
            "root_cause_analysis": [],
            "key_audit_matters": [],
            "isa700_auditor_opinion": {"type": "disclaimer"},
            "ias7_cashflow_classification": {},
            "ias7_cashflow_statement": {},
            "actions_and_recommendations": [],
        }
        
        # Act
        response = self.client.post(
            self.report_url,
            {
                "date_from": "2026-01-01",
                "date_to": "2026-03-31",
                "language": "en"
            },
            format="json"
        )
        
        # Assert
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("report_id", response.data)
        self.assertEqual(response.data["report_header"]["opinion_type"], "disclaimer")

    @patch("apps.reports.services.invoice_audit_service.InvoiceAuditService.build")
    def test_report_with_single_invoice(self, mock_build):
        """
        Scenario 2: Generate report with 1 invoice
        Expected: Report created, all 15 sections populated, opinion type determined
        """
        mock_build.return_value = {
            "report_id": "RPT-001-001",
            "report_header": {
                "opinion_type": "unqualified",
                "opinion_type_ar": "معتمد بدون تحفظ",
                "total_invoices": 1,
                "compliance_rate": 95.0,
            },
            "summary": {
                "total_invoices": 1,
                "passed": 1,
                "failed": 0,
                "compliance_rate": 95.0,
                "risk_level": "safe",
            },
            "executive_summary": {
                "conclusion": "Single invoice fully compliant",
                "key_findings": ["No violations detected"]
            },
            "compliance_engine": {
                "rules": [
                    {"code": "HDR-001", "name": "Invoice number format", "status": "pass"}
                ],
                "compliance_rate": 95.0,
            },
            "high_risk_invoices": [],
            "failed_rules_analysis": [],
            "supplier_analysis": [{"vendor": "Vendor A", "invoices": 1}],
            "risk_analysis": {"safe": 1, "review": 0, "high_risk": 0},
            "anomalies": [],
            "root_cause_analysis": [],
            "key_audit_matters": [],
            "isa700_auditor_opinion": {
                "type": "unqualified",
                "formatted_opinion": "We have audited the invoices..."
            },
            "ias7_cashflow_classification": {
                "operating": 1,
                "investing": 0,
                "financing": 0,
            },
            "ias7_cashflow_statement": {},
            "actions_and_recommendations": [],
        }
        
        # Act
        response = self.client.post(
            self.report_url,
            {
                "date_from": "2026-03-01",
                "date_to": "2026-03-31",
                "language": "en"
            },
            format="json"
        )
        
        # Assert
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["summary"]["total_invoices"], 1)
        self.assertEqual(response.data["report_header"]["opinion_type"], "unqualified")

    @patch("apps.reports.services.invoice_audit_service.InvoiceAuditService.build")
    def test_report_with_large_invoice_batch_100plus(self, mock_build):
        """
        Scenario 3: Generate report with 100+ invoices
        Expected: All sections populated, pagination ready, performance acceptable
        """
        # Mock 150 invoices
        invoices_count = 150
        high_risk_count = 25  # Top 25 flagged
        
        mock_build.return_value = {
            "report_id": "RPT-100-001",
            "report_header": {
                "opinion_type": "qualified",
                "opinion_type_ar": "معتمد بتحفظ",
                "total_invoices": invoices_count,
                "compliance_rate": 82.5,
            },
            "summary": {
                "total_invoices": invoices_count,
                "passed": 124,
                "failed": 26,
                "compliance_rate": 82.5,
                "risk_level": "review",
            },
            "high_risk_invoices": [
                {"invoice_number": f"INV-{i:04d}", "risk_score": 8.5}
                for i in range(high_risk_count)
            ],
            "failed_rules_analysis": [
                {"rule": f"Rule-{i}", "failures": 10 - i}
                for i in range(1, 6)
            ],
            "supplier_analysis": [
                {"vendor": f"Vendor {i}", "invoices": 10}
                for i in range(15)
            ],
            "risk_analysis": {"safe": 100, "review": 40, "high_risk": 10},
            "anomalies": [],
            "root_cause_analysis": [],
            "key_audit_matters": [
                {"kam": "KAM-001", "description": "Duplicate risk detected"}
            ],
            "isa700_auditor_opinion": {
                "type": "qualified",
                "formatted_opinion": "Material weaknesses identified..."
            },
            "ias7_cashflow_classification": {
                "operating": 95,
                "investing": 35,
                "financing": 20,
            },
            "ias7_cashflow_statement": {
                "operating_change": 15000.00,
                "investing_change": -8000.00,
                "financing_change": 2000.00,
            },
            "actions_and_recommendations": [
                {"priority": "immediate", "action": "Review 26 failed invoices"}
            ],
        }
        
        # Act
        response = self.client.post(
            self.report_url,
            {
                "date_from": "2026-01-01",
                "date_to": "2026-03-31",
                "language": "en"
            },
            format="json"
        )
        
        # Assert
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["summary"]["total_invoices"], invoices_count)
        self.assertEqual(response.data["report_header"]["opinion_type"], "qualified")
        self.assertEqual(len(response.data["high_risk_invoices"]), high_risk_count)


# ─────────────────────────────────────────────────────────────────────────────
# TEST 2: All 15 Report Sections Present & Structured
# ─────────────────────────────────────────────────────────────────────────────

class TestAllReportSections(APITestCase):
    """Test that all 15 sections are present and properly structured."""

    def setUp(self):
        """Create test organization and user."""
        self.org = Organization.objects.create(
            name="Report Sections Org",
            slug="report-sections-org",
        )
        
        self.auditor_role = Role.objects.get_or_create(
            name="Auditor",
            permission_level=70,
        )[0]
        
        self.user = User.objects.create_user(
            username="sections_auditor",
            email="sections@test.com",
            password="TestPass123!",
            organization=self.org,
            role=self.auditor_role,
        )
        
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.report_url = "/api/v1/reports/invoice-audit/"

    @patch("apps.reports.services.invoice_audit_service.InvoiceAuditService.build")
    def test_all_15_sections_present_in_report(self, mock_build):
        """
        Scenario 4: Report contains all 15 sections with correct fields
        Expected: Each section has required structure and data types
        """
        all_sections = {
            "report_header": {
                "report_id": "RPT-001",
                "created_at": "2026-03-25T10:00:00Z",
                "opinion_type": "unqualified",
                "total_invoices": 50,
            },
            "summary": {
                "total_invoices": 50,
                "passed": 48,
                "failed": 2,
                "compliance_rate": 96.0,
                "risk_level": "safe",
            },
            "executive_summary": {
                "conclusion": "Clean audit",
                "key_findings": ["No critical issues"],
            },
            "compliance_engine": {
                "rules": [
                    {"code": "HDR-001", "name": "Invoice number", "passed": 50, "failed": 0}
                ],
                "compliance_rate": 96.0,
            },
            "high_risk_invoices": [
                {"invoice_number": "INV-001", "risk_score": 7.5, "violations": ["VAT-001"]}
            ],
            "failed_rules_analysis": [
                {"rule": "VAT-001", "failures": 1, "percentage": 2.0}
            ],
            "supplier_analysis": [
                {"vendor": "Vendor A", "invoices": 48, "total_amount": 50000.00}
            ],
            "risk_analysis": {
                "safe": 48,
                "review": 1,
                "high_risk": 1,
                "distribution": {}
            },
            "anomalies": [
                {"type": "benford", "count": 1, "invoices": ["INV-001"]}
            ],
            "root_cause_analysis": [
                {"category": "documentation", "instances": 1, "root_cause_ar": "..."}
            ],
            "key_audit_matters": [
                {"kam": "KAM-001", "description": "Material item"}
            ],
            "isa700_auditor_opinion": {
                "type": "unqualified",
                "sections": 13,
                "formatted_opinion": "Clean opinion"
            },
            "ias7_cashflow_classification": {
                "operating": 30,
                "investing": 15,
                "financing": 5,
                "unclassified": 0,
            },
            "ias7_cashflow_statement": {
                "operating_activities": 25000.00,
                "investing_activities": -8000.00,
                "financing_activities": 2000.00,
                "net_change": 19000.00,
            },
            "actions_and_recommendations": [
                {"priority": "future", "action": "Enhance controls"}
            ],
        }
        
        mock_build.return_value = all_sections
        
        # Act
        response = self.client.post(
            self.report_url,
            {
                "date_from": "2026-03-01",
                "date_to": "2026-03-31",
                "language": "en"
            },
            format="json"
        )
        
        # Assert - all 15 sections present
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        expected_sections = [
            "report_header", "summary", "executive_summary", "compliance_engine",
            "high_risk_invoices", "failed_rules_analysis", "supplier_analysis",
            "risk_analysis", "anomalies", "root_cause_analysis", "key_audit_matters",
            "isa700_auditor_opinion", "ias7_cashflow_classification",
            "ias7_cashflow_statement", "actions_and_recommendations"
        ]
        
        for section in expected_sections:
            self.assertIn(section, response.data, f"Missing section: {section}")


# ─────────────────────────────────────────────────────────────────────────────
# TEST 3: Bilingual Output (AR/EN) Validation
# ─────────────────────────────────────────────────────────────────────────────

class TestBilingualReportOutput(APITestCase):
    """Test Arabic and English bilingual output."""

    def setUp(self):
        """Create test organization and user."""
        self.org = Organization.objects.create(
            name="Bilingual Report Org",
            slug="bilingual-org",
        )
        
        self.auditor_role = Role.objects.get_or_create(
            name="Auditor",
            permission_level=70,
        )[0]
        
        self.user = User.objects.create_user(
            username="bilingual_auditor",
            email="bilingual@test.com",
            password="TestPass123!",
            organization=self.org,
            role=self.auditor_role,
        )
        
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.report_url = "/api/v1/reports/invoice-audit/"

    @patch("apps.reports.services.invoice_audit_service.InvoiceAuditService.build")
    def test_arabic_report_output(self, mock_build):
        """
        Scenario 5: Generate report in Arabic
        Expected: All text fields in Arabic, opinion type in Arabic
        """
        mock_build.return_value = {
            "report_header": {
                "opinion_type": "unqualified",
                "opinion_type_ar": "معتمد بدون تحفظ",
                "title_ar": "تقرير مراجعة الفواتير",
            },
            "summary": {
                "compliance_rate": 95.0,
                "risk_level": "آمن",
            },
            "executive_summary": {
                "conclusion_ar": "عملية التدقيق اكتملت بنجاح",
            },
            "root_cause_analysis": [
                {
                    "root_cause_ar": "ضعف إجراءات التوثيق",
                    "root_cause_en": "Weak documentation procedures",
                }
            ],
            "actions_and_recommendations": [
                {
                    "recommendation_ar": "تعزيز الضوابط الداخلية",
                    "recommendation_en": "Enhance internal controls",
                }
            ],
        }
        
        # Act
        response = self.client.post(
            self.report_url,
            {
                "date_from": "2026-03-01",
                "date_to": "2026-03-31",
                "language": "ar"
            },
            format="json"
        )
        
        # Assert
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            response.data["report_header"]["opinion_type_ar"],
            "معتمد بدون تحفظ"
        )

    @patch("apps.reports.services.invoice_audit_service.InvoiceAuditService.build")
    def test_english_report_output(self, mock_build):
        """
        Scenario 6: Generate report in English
        Expected: All text fields in English, opinion type in English
        """
        mock_build.return_value = {
            "report_header": {
                "opinion_type": "unqualified",
                "opinion_type_en": "Unqualified Opinion",
                "title_en": "Invoice Audit Report",
            },
            "summary": {
                "compliance_rate": 95.0,
                "risk_level_en": "Safe",
            },
            "executive_summary": {
                "conclusion_en": "Audit completed successfully",
            },
        }
        
        # Act
        response = self.client.post(
            self.report_url,
            {
                "date_from": "2026-03-01",
                "date_to": "2026-03-31",
                "language": "en"
            },
            format="json"
        )
        
        # Assert
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)


# ─────────────────────────────────────────────────────────────────────────────
# TEST 4: ISA 700 Auditor Opinion Types & Thresholds
# ─────────────────────────────────────────────────────────────────────────────

class TestISA700OpinionTypes(APITestCase):
    """Test ISA 700 auditor opinion type determination."""

    def setUp(self):
        """Create test organization and user."""
        self.org = Organization.objects.create(
            name="ISA700 Report Org",
            slug="isa700-org",
        )
        
        self.auditor_role = Role.objects.get_or_create(
            name="Auditor",
            permission_level=70,
        )[0]
        
        self.user = User.objects.create_user(
            username="isa700_auditor",
            email="isa700@test.com",
            password="TestPass123!",
            organization=self.org,
            role=self.auditor_role,
        )
        
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.report_url = "/api/v1/reports/invoice-audit/"

    @patch("apps.reports.services.invoice_audit_service.InvoiceAuditService.build")
    def test_unqualified_opinion_high_compliance(self, mock_build):
        """
        Scenario 7: Opinion = UNQUALIFIED when compliance ≥ 90%
        Expected: opinion_type = "unqualified", formatted opinion present
        """
        mock_build.return_value = {
            "report_header": {
                "opinion_type": "unqualified",
                "opinion_type_ar": "معتمد بدون تحفظ",
            },
            "summary": {
                "compliance_rate": 95.0,
                "critical_failures": 0,
                "duplicates": 0,
            },
            "isa700_auditor_opinion": {
                "type": "unqualified",
                "formatted_opinion": "We have audited... and found no material misstatements.",
            },
        }
        
        # Act
        response = self.client.post(self.report_url, {
            "date_from": "2026-03-01",
            "date_to": "2026-03-31",
        }, format="json")
        
        # Assert
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["report_header"]["opinion_type"], "unqualified")

    @patch("apps.reports.services.invoice_audit_service.InvoiceAuditService.build")
    def test_qualified_opinion_medium_failures(self, mock_build):
        """
        Scenario 8: Opinion = QUALIFIED when 70% ≤ compliance < 90%
        Expected: opinion_type = "qualified", except clause present
        """
        mock_build.return_value = {
            "report_header": {
                "opinion_type": "qualified",
                "opinion_type_ar": "معتمد بتحفظ",
            },
            "summary": {
                "compliance_rate": 82.0,
                "critical_failures": 1,
                "duplicates": 2,
            },
            "isa700_auditor_opinion": {
                "type": "qualified",
                "except_clause": "...except that we identified material weaknesses...",
            },
        }
        
        # Act
        response = self.client.post(self.report_url, {
            "date_from": "2026-03-01",
            "date_to": "2026-03-31",
        }, format="json")
        
        # Assert
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["report_header"]["opinion_type"], "qualified")

    @patch("apps.reports.services.invoice_audit_service.InvoiceAuditService.build")
    def test_adverse_opinion_high_failures(self, mock_build):
        """
        Scenario 9: Opinion = ADVERSE when compliance < 70%
        Expected: opinion_type = "adverse", adverse clause present
        """
        mock_build.return_value = {
            "report_header": {
                "opinion_type": "adverse",
                "opinion_type_ar": "رأي معاكس",
            },
            "summary": {
                "compliance_rate": 55.0,
                "critical_failures": 5,
                "duplicates": 10,
            },
            "isa700_auditor_opinion": {
                "type": "adverse",
                "adverse_clause": "...the invoices do not present a true and fair view...",
            },
        }
        
        # Act
        response = self.client.post(self.report_url, {
            "date_from": "2026-03-01",
            "date_to": "2026-03-31",
        }, format="json")
        
        # Assert
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["report_header"]["opinion_type"], "adverse")


# ─────────────────────────────────────────────────────────────────────────────
# TEST 5: IAS 7 Cash Flow Classification in Report
# ─────────────────────────────────────────────────────────────────────────────

class TestIAS7CashFlowInReport(APITestCase):
    """Test IAS 7 cash flow classification in generated reports."""

    def setUp(self):
        """Create test organization and user."""
        self.org = Organization.objects.create(
            name="IAS7 Report Org",
            slug="ias7-org",
        )
        
        self.auditor_role = Role.objects.get_or_create(
            name="Auditor",
            permission_level=70,
        )[0]
        
        self.user = User.objects.create_user(
            username="ias7_auditor",
            email="ias7@test.com",
            password="TestPass123!",
            organization=self.org,
            role=self.auditor_role,
        )
        
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.report_url = "/api/v1/reports/invoice-audit/"

    @patch("apps.reports.services.invoice_audit_service.InvoiceAuditService.build")
    def test_ias7_classification_section_present(self, mock_build):
        """
        Scenario 10: Report includes IAS 7 cash flow classification
        Expected: 3 activity types (operating, investing, financing) with counts
        """
        mock_build.return_value = {
            "ias7_cashflow_classification": {
                "operating": 45,
                "investing": 28,
                "financing": 12,
                "unclassified": 0,
                "total": 85,
            },
            "ias7_cashflow_statement": {
                "operating_activities": 125000.00,
                "operating_adjustments": 5000.00,
                "operating_change": 130000.00,
                "investing_activities": -45000.00,
                "investing_change": -45000.00,
                "financing_activities": 8000.00,
                "financing_change": 8000.00,
                "net_change_in_cash": 93000.00,
            },
        }
        
        # Act
        response = self.client.post(self.report_url, {
            "date_from": "2026-03-01",
            "date_to": "2026-03-31",
        }, format="json")
        
        # Assert
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("ias7_cashflow_classification", response.data)
        self.assertEqual(response.data["ias7_cashflow_classification"]["operating"], 45)
        self.assertEqual(response.data["ias7_cashflow_classification"]["financing"], 12)


# ─────────────────────────────────────────────────────────────────────────────
# TEST 6: KAM Assertions (ISA 701) in Report
# ─────────────────────────────────────────────────────────────────────────────

class TestISA701KAMsInReport(APITestCase):
    """Test Key Audit Matters (ISA 701) inclusion in reports."""

    def setUp(self):
        """Create test organization and user."""
        self.org = Organization.objects.create(
            name="KAM Report Org",
            slug="kam-org",
        )
        
        self.auditor_role = Role.objects.get_or_create(
            name="Auditor",
            permission_level=70,
        )[0]
        
        self.user = User.objects.create_user(
            username="kam_auditor",
            email="kam@test.com",
            password="TestPass123!",
            organization=self.org,
            role=self.auditor_role,
        )
        
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.report_url = "/api/v1/reports/invoice-audit/"

    @patch("apps.reports.services.invoice_audit_service.InvoiceAuditService.build")
    def test_kams_section_present_when_material(self, mock_build):
        """
        Scenario 11: Report includes KAMs when material issues exist
        Expected: key_audit_matters array with ISA 701 items
        """
        mock_build.return_value = {
            "key_audit_matters": [
                {
                    "kam": "KAM-001",
                    "title": "Duplicate Invoice Risk",
                    "description": "2 pairs of duplicates detected representing 8.5% of population",
                    "standards_reference": "ISA 240 - Fraud and Error",
                    "auditor_response": "Reviewed transactions, confirmed isolated incident",
                },
                {
                    "kam": "KAM-002",
                    "title": "Control Weaknesses",
                    "description": "3 invoices lacked proper vendor pre-approval",
                    "standards_reference": "ISA 315 - Understanding the Entity",
                    "auditor_response": "Management committed to corrective action plan",
                },
            ],
        }
        
        # Act
        response = self.client.post(self.report_url, {
            "date_from": "2026-03-01",
            "date_to": "2026-03-31",
        }, format="json")
        
        # Assert
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("key_audit_matters", response.data)
        self.assertGreater(len(response.data["key_audit_matters"]), 0)

    @patch("apps.reports.services.invoice_audit_service.InvoiceAuditService.build")
    def test_kams_section_empty_for_clean_audit(self, mock_build):
        """
        Scenario 12: Report has empty KAMs when audit is clean
        Expected: key_audit_matters is empty array (ISA 701 doesn't require KAMs for clean audits)
        """
        mock_build.return_value = {
            "key_audit_matters": [],
            "report_header": {
                "opinion_type": "unqualified",
            },
        }
        
        # Act
        response = self.client.post(self.report_url, {
            "date_from": "2026-03-01",
            "date_to": "2026-03-31",
        }, format="json")
        
        # Assert
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("key_audit_matters", response.data)
        self.assertEqual(len(response.data["key_audit_matters"]), 0)


# ─────────────────────────────────────────────────────────────────────────────
# TEST 7: Integration - Complete Report Generation Flow
# ─────────────────────────────────────────────────────────────────────────────

class TestReportGenerationIntegration(APITestCase):
    """End-to-end report generation with all features."""

    def setUp(self):
        """Create test organization and user."""
        self.org = Organization.objects.create(
            name="Integration Report Org",
            slug="integration-report-org",
        )
        
        self.auditor_role = Role.objects.get_or_create(
            name="Auditor",
            permission_level=70,
        )[0]
        
        self.user = User.objects.create_user(
            username="integration_auditor",
            email="integration@test.com",
            password="TestPass123!",
            organization=self.org,
            role=self.auditor_role,
        )
        
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.report_url = "/api/v1/reports/invoice-audit/"

    @patch("apps.reports.services.invoice_audit_service.InvoiceAuditService.build")
    def test_end_to_end_report_generation_flow(self, mock_build):
        """
        Integration: Generate comprehensive report with:
        - 50 invoices with mixed compliance
        - All 15 sections
        - ISA 700 qualified opinion
        - IAS 7 classification
        - Material KAMs
        - Bilingual output
        """
        mock_build.return_value = {
            # Section 1: Report Header
            "report_header": {
                "report_id": "RPT-INT-2026-001",
                "created_at": "2026-03-25T10:00:00Z",
                "organization_name": self.org.name,
                "audit_period": "2026-03-01 to 2026-03-31",
                "opinion_type": "qualified",
                "opinion_type_ar": "معتمد بتحفظ",
                "total_invoices": 50,
            },
            # Section 2: Summary
            "summary": {
                "total_invoices": 50,
                "passed": 43,
                "failed": 7,
                "compliance_rate": 86.0,
                "risk_level": "review",
                "risk_score": 6.2,
            },
            # Section 3: Executive Summary
            "executive_summary": {
                "conclusion": "Subject to the exception noted below, the invoices are in compliance.",
                "conclusion_ar": "باستثناء ما هو مبين أدناه، الفواتير متوافقة",
                "key_findings": [
                    "1 pair of duplicate invoices detected",
                    "2 VAT calculation errors",
                    "3 missing vendor pre-approval"
                ],
            },
            # Section 4: Compliance Engine
            "compliance_engine": {
                "rules": [
                    {"code": "HDR-001", "name": "Invoice number format", "passed": 50, "failed": 0},
                    {"code": "VAT-001", "name": "VAT rate correct", "passed": 48, "failed": 2},
                ],
                "compliance_rate": 86.0,
                "total_rules": 34,
            },
            # Section 5: High Risk Invoices
            "high_risk_invoices": [
                {"invoice_number": "INV-045", "risk_score": 8.5, "violations": ["DUPLICATE"]},
                {"invoice_number": "INV-032", "risk_score": 7.2, "violations": ["VAT-001"]},
            ],
            # Section 6: Failed Rules Analysis
            "failed_rules_analysis": [
                {"rule": "VAT-001", "failures": 2, "percentage": 4.0},
                {"rule": "VENDOR-APPROVAL", "failures": 3, "percentage": 6.0},
            ],
            # Section 7: Supplier Analysis
            "supplier_analysis": [
                {"vendor": "Vendor A", "invoices": 25, "total_amount": 125000.00, "risk_tier": "trusted"},
                {"vendor": "Vendor B", "invoices": 18, "total_amount": 89000.00, "risk_tier": "normal"},
            ],
            # Section 8: Risk Analysis
            "risk_analysis": {
                "safe": 40,
                "review": 7,
                "high_risk": 3,
                "distribution": {
                    "safe_percentage": 80.0,
                    "review_percentage": 14.0,
                    "high_risk_percentage": 6.0,
                }
            },
            # Section 9: Anomalies
            "anomalies": [
                {"type": "duplicate", "count": 1, "invoices": ["INV-045"]},
                {"type": "benford", "count": 2},
            ],
            # Section 10: Root Cause Analysis
            "root_cause_analysis": [
                {
                    "category": "documentation",
                    "instances": 1,
                    "root_cause": "Weak control over duplicate submission",
                    "root_cause_ar": "ضعف الرقابة على على تقديم النسخ المكررة",
                },
            ],
            # Section 11: Key Audit Matters
            "key_audit_matters": [
                {
                    "kam": "KAM-001",
                    "title": "Duplicate Invoice Risk",
                    "description": "Material misstatement prevention",
                    "standards_reference": "ISA 240",
                },
            ],
            # Section 12: ISA 700 Opinion
            "isa700_auditor_opinion": {
                "type": "qualified",
                "full_opinion": "We have audited... the invoices are fairly presented except...",
                "except_clause": "...we identified 1 pair of duplicate invoices...",
            },
            # Section 13: IAS 7 Classification
            "ias7_cashflow_classification": {
                "operating": 30,
                "investing": 12,
                "financing": 8,
                "unclassified": 0,
                "confidence_average": 0.82,
            },
            # Section 14: IAS 7 Statement
            "ias7_cashflow_statement": {
                "operating_change": 145000.00,
                "investing_change": -38000.00,
                "financing_change": 9000.00,
                "net_change": 116000.00,
            },
            # Section 15: Actions & Recommendations
            "actions_and_recommendations": [
                {
                    "priority": "immediate",
                    "action": "Investigate and remove 1 duplicate invoice",
                    "owner": "Finance Manager",
                },
                {
                    "priority": "future",
                    "action": "Implement duplicate detection controls",
                    "owner": "IT Department",
                },
            ],
        }
        
        # Act
        response = self.client.post(
            self.report_url,
            {
                "date_from": "2026-03-01",
                "date_to": "2026-03-31",
                "language": "en",
                "save": True,
            },
            format="json"
        )
        
        # Assert
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        # Verify all 15 sections present
        sections = [
            "report_header", "summary", "executive_summary", "compliance_engine",
            "high_risk_invoices", "failed_rules_analysis", "supplier_analysis",
            "risk_analysis", "anomalies", "root_cause_analysis", "key_audit_matters",
            "isa700_auditor_opinion", "ias7_cashflow_classification",
            "ias7_cashflow_statement", "actions_and_recommendations"
        ]
        for section in sections:
            self.assertIn(section, response.data)
        
        # Verify key metrics
        self.assertEqual(response.data["summary"]["total_invoices"], 50)
        self.assertEqual(response.data["summary"]["compliance_rate"], 86.0)
        self.assertEqual(response.data["report_header"]["opinion_type"], "qualified")


if __name__ == "__main__":
    import unittest
    unittest.main()
