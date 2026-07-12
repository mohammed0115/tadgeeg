"""
Tests for ISA 700 Formal Auditor Opinion Service

Test coverage:
  - Opinion type determination (unqualified, qualified, adverse, disclaimer)
  - Risk assessment summary
  - Compliance statement generation
  - Audit evidence compilation
  - KAM integration
  - Going concern assessment
  - Audit committee communications
  - Proper handling of edge cases
"""

import pytest
from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone
from apps.reports.services.isa700_opinion_service import ISA700OpinionService
from apps.authentication.models import Organization, User
from apps.invoices.models import Invoice, InvoiceValidationResult
from apps.audit.models import AuditSession


@pytest.fixture
def org():
    """Create test organization."""
    return Organization.objects.create(
        name="Test Org",
        country="SA",
    )


@pytest.fixture
def user(org):
    """Create test user."""
    return User.objects.create_user(
        email="auditor@test.com",
        password="test123",
        full_name="Test Auditor",
        organization=org,
        role="senior_auditor"
    )


@pytest.fixture
def isa700_service(org, user):
    """Create ISA 700 service instance."""
    return ISA700OpinionService(org, user)


class TestOpinionTypeDetermination:
    """Test opinion type determination logic per ISA 700 & ISA 705."""

    def test_unqualified_opinion_clean_audit(self, isa700_service):
        """Unqualified opinion: compliance >= 90%, no critical failures."""
        summary = {
            "total_invoices": 100,
            "validated_count": 100,
            "compliance_score": 95.0,
            "critical_failures": 0,
            "duplicate_count": 0,
            "high_risk_count": 0,
            "anomaly_count": 0,
        }
        validations = {}
        invoices = []

        opinion_type, basis = isa700_service._determine_opinion_type(summary, validations, invoices)

        assert opinion_type == "unqualified"
        assert basis == "no_material_misstatements"

    def test_qualified_opinion_material_issues(self, isa700_service):
        """Qualified opinion: material but non-pervasive issues (70-89% compliance)."""
        summary = {
            "total_invoices": 100,
            "validated_count": 95,
            "compliance_score": 78.5,
            "critical_failures": 1,
            "duplicate_count": 3,
            "high_risk_count": 10,
            "anomaly_count": 5,
        }
        validations = {}
        invoices = [{"id": i} for i in range(100)]

        opinion_type, basis = isa700_service._determine_opinion_type(summary, validations, invoices)

        assert opinion_type == "qualified"
        assert basis == "except_for_issues"

    def test_adverse_opinion_pervasive_issues(self, isa700_service):
        """Adverse opinion: pervasive issues (compliance < 70%)."""
        summary = {
            "total_invoices": 100,
            "validated_count": 60,
            "compliance_score": 55.0,
            "critical_failures": 5,
            "duplicate_count": 15,
            "high_risk_count": 30,
            "anomaly_count": 20,
        }
        validations = {}
        invoices = [{"id": i} for i in range(100)]

        opinion_type, basis = isa700_service._determine_opinion_type(summary, validations, invoices)

        assert opinion_type == "adverse"
        assert basis == "pervasive_material_misstatements"

    def test_disclaimer_insufficient_evidence(self, isa700_service):
        """Disclaimer of opinion: insufficient invoice data."""
        summary = {
            "total_invoices": 0,
            "validated_count": 0,
            "compliance_score": 0.0,
            "critical_failures": 0,
            "duplicate_count": 0,
            "high_risk_count": 0,
            "anomaly_count": 0,
        }
        validations = {}
        invoices = []

        opinion_type, basis = isa700_service._determine_opinion_type(summary, validations, invoices)

        assert opinion_type == "disclaimer"
        assert basis == "insufficient_evidence"

    def test_adverse_opinion_critical_failures(self, isa700_service):
        """Adverse opinion: >= 3 critical failures even with moderate compliance."""
        summary = {
            "total_invoices": 100,
            "validated_count": 85,
            "compliance_score": 80.0,  # Good score, but...
            "critical_failures": 3,    # ...critical failures override
            "duplicate_count": 5,
            "high_risk_count": 8,
            "anomaly_count": 2,
        }
        validations = {}
        invoices = [{"id": i} for i in range(100)]

        opinion_type, basis = isa700_service._determine_opinion_type(summary, validations, invoices)

        assert opinion_type == "adverse"


class TestOpinionParagraph:
    """Test formal opinion paragraph generation per ISA 700 A118."""

    def test_unqualified_opinion_paragraph_arabic(self, isa700_service):
        """Unqualified opinion paragraph in Arabic."""
        opinion = isa700_service._build_opinion_paragraph(
            "unqualified",
            "no_material_misstatements",
            90.5
        )

        # 5B/5C: safe audit-readiness wording — NOT a formal opinion.
        assert "رهن مراجعة المدقّق" in opinion["opinion_ar"]
        assert "في رأينا" not in opinion["opinion_ar"]
        assert "تعرض بعدالة" not in opinion["opinion_ar"]
        assert "90.5" in opinion["opinion_ar"]
        assert opinion["is_formal_opinion"] is False
        assert opinion["subject_to_auditor_review"] is True

    def test_qualified_opinion_paragraph_english(self, isa700_service):
        """Qualified opinion paragraph in English."""
        opinion = isa700_service._build_opinion_paragraph(
            "qualified",
            "except_for_issues",
            75.0
        )

        # 5B/5C: safe draft-direction wording — NOT a formal opinion.
        assert "subject to auditor review" in opinion["opinion_en"].lower()
        assert "75.0" in opinion["opinion_en"]
        assert "not a formal audit opinion" in opinion["opinion_en"].lower()
        assert "in our opinion" not in opinion["opinion_en"].lower()
        assert "present fairly" not in opinion["opinion_en"].lower()

    def test_adverse_opinion_paragraph(self, isa700_service):
        """Adverse opinion paragraph."""
        opinion = isa700_service._build_opinion_paragraph(
            "adverse",
            "pervasive_material_misstatements",
            45.0
        )

        assert "Adverse Opinion" in opinion["opinion_type_en"] or "adverse" in opinion["opinion_type"]
        assert "45.0" in opinion["opinion_en"]

    def test_disclaimer_opinion_paragraph(self, isa700_service):
        """Disclaimer of opinion paragraph."""
        opinion = isa700_service._build_opinion_paragraph(
            "disclaimer",
            "insufficient_evidence",
            0.0
        )

        assert "disclaimer" in opinion["opinion_type"]
        # 5B/5C: safe wording — insufficient basis, subject to auditor review.
        assert "subject to auditor review" in opinion["opinion_en"].lower()
        assert "insufficient basis" in opinion["opinion_en"].lower()
        assert opinion["is_formal_opinion"] is False
        assert opinion["disclaimer_en"]


class TestRiskAssessment:
    """Test risk assessment summary per ISA 315."""

    def test_risk_assessment_with_duplicates(self, isa700_service):
        """Risk assessment identifies duplicate risk."""
        summary = {
            "critical_failures": 0,
            "high_risk_count": 5,
            "duplicate_count": 10,
            "anomaly_count": 3,
        }
        validations = {}
        anomalies = {"count": 3, "items": []}
        compliance_engine = {}

        risk_assess = isa700_service._build_risk_assessment(
            summary, validations, anomalies, compliance_engine
        )

        assert risk_assess["identified_risks"][0]["risk_type"] == "Duplicate Transactions"
        assert risk_assess["identified_risks"][0]["count"] == 10
        assert risk_assess["identified_risks"][0]["assessed_level"] == "High"

    def test_risk_assessment_overall_high(self, isa700_service):
        """Risk assessment overall level set to High when critical failures exist."""
        summary = {
            "critical_failures": 1,
            "high_risk_count": 2,
            "duplicate_count": 1,
            "anomaly_count": 0,
        }
        validations = {}
        anomalies = {}
        compliance_engine = {}

        risk_assess = isa700_service._build_risk_assessment(
            summary, validations, anomalies, compliance_engine
        )

        assert risk_assess["overall_risk_assessment"]["en"] == "High"
        assert risk_assess["overall_risk_assessment"]["ar"] == "مرتفع"

    def test_risk_assessment_overall_low(self, isa700_service):
        """Risk assessment overall level set to Low when no issues."""
        summary = {
            "critical_failures": 0,
            "high_risk_count": 0,
            "duplicate_count": 0,
            "anomaly_count": 0,
        }
        validations = {}
        anomalies = {}
        compliance_engine = {}

        risk_assess = isa700_service._build_risk_assessment(
            summary, validations, anomalies, compliance_engine
        )

        assert risk_assess["overall_risk_assessment"]["en"] == "Low"


class TestComplianceStatement:
    """Test compliance statement generation."""

    def test_compliance_statement_standards_applied(self, isa700_service):
        """Compliance statement includes all relevant standards."""
        compliance_engine = {}
        summary = {"compliance_score": 85.5}

        compliance = isa700_service._build_compliance_statement(
            compliance_engine, summary
        )

        standards = [s["standard"] for s in compliance["standards_applied"]]
        assert "ISA 700" in standards
        assert "ISA 705" in standards
        assert "ISA 701" in standards
        assert "ZATCA Phase 2" in standards

    def test_compliance_score_displayed(self, isa700_service):
        """Compliance score is properly displayed."""
        compliance = isa700_service._build_compliance_statement({}, {"compliance_score": 87.3})
        
        assert compliance["compliance_rate"] == "87.3%"


class TestAuditEvidence:
    """Test audit evidence summary per ISA 330."""

    def test_audit_evidence_procedures(self, isa700_service):
        """Audit evidence includes all key procedures."""
        compliance_engine = {}

        evidence = isa700_service._build_audit_evidence(
            total=150,
            validations={},
            compliance_engine=compliance_engine
        )

        procedures = [p["procedure"] for p in evidence["procedures_performed"]]
        assert "Risk Identification" in procedures
        assert "Completeness Testing" in procedures
        assert "Duplicate Detection" in procedures
        assert "VAT Compliance" in procedures
        assert "Anomaly Analysis" in procedures

    def test_audit_evidence_sampling_methodology(self, isa700_service):
        """Audit evidence methodology is documented."""
        evidence = isa700_service._build_audit_evidence(
            total=200,
            validations={},
            compliance_engine={}
        )

        assert evidence["sampling_methodology"] == "All-items sampling (100% of invoices in period)"
        assert evidence["total_items_tested"] == 200


class TestGoingConcern:
    """Test going concern assessment per ISA 570."""

    def test_going_concern_no_issues(self, isa700_service):
        """Going concern assessment when no issues identified."""
        gc = isa700_service._build_going_concern({"critical_failures": 0})

        assert "No indicators" in gc["assessment"]
        assert "ISA 570" in gc["isa_reference"]

    def test_going_concern_with_issues(self, isa700_service):
        """Going concern assessment when issues identified."""
        gc = isa700_service._build_going_concern({"critical_failures": 2})

        assert "Potential" in gc["assessment"]


class TestAuditCommitteeCommunications:
    """Test audit committee communication requirements per ISA 260."""

    def test_audit_committee_comms_topics(self, isa700_service):
        """Audit committee communication includes all required topics."""
        comms = isa700_service._build_audit_committee_comms(
            opinion_type="qualified",
            critical_failures=2,
            duplicates=5,
            high_risk=10
        )

        topics = [t["topic"] for t in comms["topics"]]
        assert "Opinion Type and Basis" in topics
        assert "Critical Issues" in topics
        assert "Duplicate Invoices" in topics
        assert "High-Risk Invoices" in topics
        assert "Compliance Status" in topics

    def test_audit_committee_comms_required(self, isa700_service):
        """Audit committee communication is flagged as required."""
        comms = isa700_service._build_audit_committee_comms(
            "qualified", 1, 2, 3
        )

        assert comms["communication_required"] is True


class TestComprehensiveOpinionGeneration:
    """Integration tests for complete opinion generation."""

    def test_generate_unqualified_opinion_complete(self, isa700_service):
        """Generate complete unqualified opinion report."""
        summary = {
            "total_invoices": 150,
            "validated_count": 150,
            "compliance_score": 92.5,
            "critical_failures": 0,
            "duplicate_count": 0,
            "high_risk_count": 0,
            "anomaly_count": 0,
            "risk_level": "safe",
        }
        validations = {}
        invoices = [{"id": i} for i in range(150)]
        kams_list = []
        compliance_engine = {}
        anomalies = {}

        opinion_report = isa700_service.generate_opinion(
            summary, validations, invoices, kams_list, compliance_engine, anomalies
        )

        assert opinion_report["opinion_type"] == "unqualified"
        assert "management_responsibility" in opinion_report
        assert "auditor_responsibility" in opinion_report
        assert "opinion_paragraph" in opinion_report
        assert "basis_for_opinion" in opinion_report
        assert "audit_evidence_summary" in opinion_report
        assert "going_concern_assessment" in opinion_report
        assert "audit_committee_communications" in opinion_report

    def test_generate_qualified_opinion_complete(self, isa700_service):
        """Generate complete qualified opinion report."""
        summary = {
            "total_invoices": 100,
            "validated_count": 95,
            "compliance_score": 78.0,
            "critical_failures": 1,
            "duplicate_count": 2,
            "high_risk_count": 5,
            "anomaly_count": 3,
            "risk_level": "review",
        }
        validations = {}
        invoices = [{"id": i} for i in range(100)]
        kams_list = [{"id": 1, "title": "Test KAM", "is_kam": True}]
        compliance_engine = {}
        anomalies = {"count": 3}

        opinion_report = isa700_service.generate_opinion(
            summary, validations, invoices, kams_list, compliance_engine, anomalies
        )

        assert opinion_report["opinion_type"] == "qualified"
        assert opinion_report["critical_issues_count"] == 1
        assert opinion_report["compliance_score"] == 78.0

    def test_opinion_report_bilingual_content(self, isa700_service):
        """Verify report includes bilingual (Arabic/English) content."""
        summary = {
            "total_invoices": 50,
            "validated_count": 50,
            "compliance_score": 88.0,
            "critical_failures": 0,
            "duplicate_count": 0,
            "high_risk_count": 1,
            "anomaly_count": 1,
        }

        opinion_report = isa700_service.generate_opinion(
            summary, {}, [], [], {}, {}
        )

        # Check for Arabic content (management responsibility — no "in our opinion").
        assert "المسؤولية" in opinion_report["management_responsibility"]["ar"]
        assert "في رأينا" not in opinion_report["management_responsibility"]["ar"]

        # English: opinion is the licensed auditor's responsibility, not the system's.
        auditor_en = opinion_report["auditor_responsibility"]["en"].lower()
        assert "licensed auditor" in auditor_en
        assert "not a formal audit opinion" in auditor_en
        assert "our responsibility is to express" not in auditor_en

        # 5B/5C: top-level safe-wording guarantees on the generated report.
        assert opinion_report["is_formal_opinion"] is False
        assert opinion_report["subject_to_auditor_review"] is True
        assert opinion_report["disclaimer_en"]


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_opinion_with_zero_invoices(self, isa700_service):
        """Handle case with zero invoices."""
        summary = {
            "total_invoices": 0,
            "validated_count": 0,
            "compliance_score": 0.0,
            "critical_failures": 0,
            "duplicate_count": 0,
            "high_risk_count": 0,
            "anomaly_count": 0,
        }

        opinion_type, _ = isa700_service._determine_opinion_type(summary, {}, [])

        assert opinion_type == "disclaimer"

    def test_opinion_with_all_critical_failures(self, isa700_service):
        """Handle case where all invoices fail critical checks."""
        summary = {
            "total_invoices": 100,
            "validated_count": 100,
            "compliance_score": 10.0,  # Very low
            "critical_failures": 100,  # All fail
            "duplicate_count": 50,
            "high_risk_count": 100,
            "anomaly_count": 80,
        }

        opinion_type, _ = isa700_service._determine_opinion_type(summary, {}, [{"id": i} for i in range(100)])

        assert opinion_type == "adverse"

    def test_formatting_dates_arabic(self, isa700_service):
        """Test date formatting in Arabic."""
        test_date = date(2026, 3, 25)
        formatted = isa700_service._format_date_ar(test_date)

        assert "25" in formatted
        assert "مارس" in formatted
        assert "2026" in formatted

    def test_formatting_dates_english(self, isa700_service):
        """Test date formatting in English."""
        test_date = date(2026, 3, 25)
        formatted = isa700_service._format_date_en(test_date)

        assert "March" in formatted or "25" in formatted
        assert "2026" in formatted


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
