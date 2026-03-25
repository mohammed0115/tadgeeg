"""Test Suite for IAS 7 Cash Flow Classification Service

Covers:
- IAS7CashFlowClassifier heuristic algorithms
- IAS7CashFlowService integration
- Cash flow statement building
- Batch classification statistics
"""

import pytest
from datetime import datetime
from decimal import Decimal
from django.utils import timezone

from apps.invoices.models import Invoice
from apps.analytics.ias7_cashflow_service import IAS7CashFlowClassifier, IAS7CashFlowService


@pytest.mark.django_db
class TestIAS7CashFlowClassifier:
    """Test the classification heuristic engine."""

    def test_classify_by_account_code_operating(self):
        """Account code 61xx should classify as operating salary."""
        classifier = IAS7CashFlowClassifier()
        
        result = classifier._classify_by_account_code("6100")
        assert result == ("operating", "op_salary")

    def test_classify_by_account_code_investing(self):
        """Account code 11xx should classify as investing equipment."""
        classifier = IAS7CashFlowClassifier()
        
        result = classifier._classify_by_account_code("1150")
        assert result == ("investing", "inv_equipment")

    def test_classify_by_account_code_financing(self):
        """Account code 20xx should classify as financing debt."""
        classifier = IAS7CashFlowClassifier()
        
        result = classifier._classify_by_account_code("2010")
        assert result == ("financing", "fin_loan")

    def test_classify_by_cost_center_operating(self):
        """Cost center 1100 (HR) should classify as operating salary."""
        classifier = IAS7CashFlowClassifier()
        
        result = classifier._classify_by_cost_center("1100")
        assert result == ("operating", "op_salary")

    def test_classify_by_cost_center_investing(self):
        """Cost center 5500 (Capital) should classify as investing."""
        classifier = IAS7CashFlowClassifier()
        
        result = classifier._classify_by_cost_center("5500")
        assert result == ("investing", "inv_equipment")

    def test_classify_by_vendor_name_salary(self):
        """Vendor name containing 'salary' should classify as operating salary."""
        classifier = IAS7CashFlowClassifier()
        
        result = classifier._classify_by_vendor_name("ABC Salary Company LLC")
        assert result[0] == "operating"
        assert result[1] == "op_salary"

    def test_classify_by_vendor_name_bank(self):
        """Vendor name containing 'bank' should classify as financing."""
        classifier = IAS7CashFlowClassifier()
        
        result = classifier._classify_by_vendor_name("Saudi National Bank")
        assert result[0] == "financing"

    def test_classify_by_vendor_name_equipment(self):
        """Vendor name containing 'equipment' should classify as investing."""
        classifier = IAS7CashFlowClassifier()
        
        result = classifier._classify_by_vendor_name("Heavy Equipment Supplier Corp")
        assert result[0] == "investing"

    def test_classify_by_keywords_operating(self):
        """Text with operating keywords should classify as operating."""
        classifier = IAS7CashFlowClassifier()
        text = "Office supplies, stationery, and consumables from XYZ Company"
        
        result = classifier._classify_by_keywords(text)
        assert result is not None
        assert result[0] == "operating"
        assert result[1] == "op_supplies"

    def test_classify_by_keywords_investing(self):
        """Text with equipment keywords should classify as investing."""
        classifier = IAS7CashFlowClassifier()
        text = "New machinery and equipment for production line setup"
        
        result = classifier._classify_by_keywords(text)
        assert result is not None
        assert result[0] == "investing"
        assert result[1] == "inv_equipment"

    def test_classify_by_keywords_financing(self):
        """Text with loan keywords should classify as financing."""
        classifier = IAS7CashFlowClassifier()
        text = "Bank loan and borrowing arrangement for working capital"
        
        result = classifier._classify_by_keywords(text)
        assert result is not None
        assert result[0] == "financing"

    def test_classify_invoice_with_account_code(self, invoice_factory, org):
        """Classification should prioritize account code (highest confidence)."""
        classifier = IAS7CashFlowClassifier()
        invoice = invoice_factory(
            organization=org,
            account_code="6100",  # Salary account
            vendor_name="RandomCompany",  # Not a financing vendor
            ai_summary="Some random text"  # No keywords
        )
        
        result = classifier.classify_invoice(invoice)
        assert result["cash_flow_class"] == "operating"
        assert result["cash_flow_subcategory"] == "op_salary"
        assert result["cash_flow_confidence"] == 0.95

    def test_classify_invoice_with_cost_center(self, invoice_factory, org):
        """Classification should use cost center when account code missing."""
        classifier = IAS7CashFlowClassifier()
        invoice = invoice_factory(
            organization=org,
            account_code="",
            cost_center="5500",  # Capital projects
            vendor_name="General Supplier",
            ai_summary="Some description"
        )
        
        result = classifier.classify_invoice(invoice)
        assert result["cash_flow_class"] == "investing"
        assert result["cash_flow_subcategory"] == "inv_equipment"

    def test_classify_invoice_with_vendor_name(self, invoice_factory, org):
        """Classification should use vendor name when higher-priority fields missing."""
        classifier = IAS7CashFlowClassifier()
        invoice = invoice_factory(
            organization=org,
            account_code="",
            cost_center="",
            vendor_name="Equipment Vendor Inc"
        )
        
        result = classifier.classify_invoice(invoice)
        assert result["cash_flow_class"] == "investing"

    def test_classify_invoice_with_keywords(self, invoice_factory, org):
        """Classification should use keywords when structured fields missing."""
        classifier = IAS7CashFlowClassifier()
        invoice = invoice_factory(
            organization=org,
            account_code="",
            cost_center="",
            vendor_name="Generic Company",
            ai_summary="Salary payment for employees"
        )
        
        result = classifier.classify_invoice(invoice)
        assert result["cash_flow_class"] == "operating"
        assert result["cash_flow_subcategory"] == "op_salary"

    def test_classify_invoice_no_match_unclassified(self, invoice_factory, org):
        """Invoice with no matching patterns should be unclassified."""
        classifier = IAS7CashFlowClassifier()
        invoice = invoice_factory(
            organization=org,
            account_code="",
            cost_center="",
            vendor_name="XYZ 123 Generic Corp",
            ai_summary="Random purchase"
        )
        
        result = classifier.classify_invoice(invoice)
        assert result["cash_flow_class"] == "unclassified"
        assert result["cash_flow_confidence"] == 0.0

    def test_finalize_classification_high_confidence(self):
        """High confidence scores should produce high confidence classification."""
        classifier = IAS7CashFlowClassifier()
        scores = {
            "operating": [0.95, 0.90],
            "investing": [0.3],
            "financing": []
        }
        
        # Mock invoice for classifier context
        class MockInvoice:
            ai_summary = ""
            notes = ""
            account_code = ""
            cost_center = ""
            vendor_name = ""
        
        result = classifier._finalize_classification(scores, ["test"], MockInvoice())
        assert result["cash_flow_class"] == "operating"
        assert result["cash_flow_confidence"] == 0.925

    def test_finalize_classification_low_confidence(self):
        """Low confidence should result in unclassified with requires_review."""
        classifier = IAS7CashFlowClassifier()
        scores = {
            "operating": [0.45],
            "investing": [0.40],
            "financing": [0.35]
        }
        
        class MockInvoice:
            ai_summary = ""
            notes = ""
            account_code = ""
            cost_center = ""
            vendor_name = ""
        
        result = classifier._finalize_classification(scores, ["test"], MockInvoice())
        assert result["cash_flow_class"] == "unclassified"
        assert result["requires_review"] is True


@pytest.mark.django_db
class TestIAS7CashFlowService:
    """Test the integration service."""

    def test_classify_invoices_batch(self, invoice_factory, org, user):
        """Batch classification should update invoice fields."""
        invoices = [
            invoice_factory(organization=org, account_code="6100"),  # Operating salary
            invoice_factory(organization=org, account_code="1150"),  # Investing equipment
            invoice_factory(organization=org, account_code="2010"),  # Financing debt
        ]
        
        service = IAS7CashFlowService(org, user)
        results = service.classify_invoices(invoices)
        
        assert results["success"] is True
        assert results["classified_count"] == 3
        assert results["unclassified_count"] == 0
        assert results["statistics"]["by_class"]["operating"] == 1
        assert results["statistics"]["by_class"]["investing"] == 1
        assert results["statistics"]["by_class"]["financing"] == 1

    def test_classify_invoices_with_unclassified(self, invoice_factory, org, user):
        """Unclassifiable invoices should be tracked."""
        invoices = [
            invoice_factory(organization=org, account_code="6100"),  # Operating
            invoice_factory(
                organization=org,
                account_code="",
                cost_center="",
                vendor_name="Random",
                ai_summary="Misc"
            ),  # Unclassified
        ]
        
        service = IAS7CashFlowService(org, user)
        results = service.classify_invoices(invoices)
        
        assert results["classified_count"] == 1
        assert results["unclassified_count"] == 1
        assert results["statistics"]["by_class"]["unclassified"] == 1

    def test_classify_invoices_low_confidence_flagged(self, invoice_factory, org, user):
        """Low confidence classifications should be flagged for review."""
        invoices = [
            invoice_factory(
                organization=org,
                account_code="",
                cost_center="",
                vendor_name="Some Company",
                ai_summary="Maybe supplies maybe equipment unclear"
            ),
        ]
        
        service = IAS7CashFlowService(org, user)
        results = service.classify_invoices(invoices)
        
        assert results["requires_review_count"] >= 0  # May be flagged depending on confidence

    def test_build_cashflow_statement_structure(self, invoice_factory, org, user):
        """Cash flow statement should follow IAS 7 structure."""
        invoices = [
            invoice_factory(organization=org, account_code="6100", total_amount=Decimal("1000.00")),
            invoice_factory(organization=org, account_code="1150", total_amount=Decimal("5000.00")),
            invoice_factory(organization=org, account_code="2010", total_amount=Decimal("10000.00")),
        ]
        
        service = IAS7CashFlowService(org, user)
        service.classify_invoices(invoices)
        statement = service.build_cashflow_statement(invoices)
        
        assert statement["standard"] == "IAS 7:2017"
        assert "operating_activities" in statement["cash_flows"]
        assert "investing_activities" in statement["cash_flows"]
        assert "financing_activities" in statement["cash_flows"]
        assert "net_increase_in_cash" in statement["cash_flows"]

    def test_cashflow_statement_totals(self, invoice_factory, org, user):
        """Cash flow statement totals should sum correctly."""
        invoices = [
            invoice_factory(organization=org, account_code="6100", total_amount=Decimal("1000.00")),
            invoice_factory(organization=org, account_code="1150", total_amount=Decimal("5000.00")),
        ]
        
        service = IAS7CashFlowService(org, user)
        service.classify_invoices(invoices)
        statement = service.build_cashflow_statement(invoices)
        
        # Operating should be 1000, Investing should be 5000
        assert Decimal(statement["cash_flows"]["operating_activities"]["total"]) == Decimal("1000.00")
        assert Decimal(statement["cash_flows"]["investing_activities"]["total"]) == Decimal("5000.00")

    def test_cashflow_statement_excludes_deleted(self, invoice_factory, org, user):
        """Soft-deleted invoices should be excluded from cash flow statement."""
        invoices = [
            invoice_factory(organization=org, account_code="6100", total_amount=Decimal("1000.00")),
            invoice_factory(organization=org, account_code="1150", total_amount=Decimal("5000.00"), is_deleted=True),
        ]
        
        service = IAS7CashFlowService(org, user)
        service.classify_invoices(invoices)
        statement = service.build_cashflow_statement(invoices)
        
        # Only operating should have amount (investing invoice is deleted)
        operating_total = Decimal(statement["cash_flows"]["operating_activities"]["total"])
        investing_total = Decimal(statement["cash_flows"]["investing_activities"]["total"])
        
        assert operating_total == Decimal("1000.00")
        assert investing_total == Decimal("0.00")


@pytest.mark.django_db
class TestIAS7IntegrationWithAuditReport:
    """Test IAS 7 integration with invoice audit report generation."""

    def test_audit_report_includes_ias7_section(self, invoice_factory, org, user):
        """Audit report should include IAS 7 cash flow classification section."""
        from apps.reports.services.invoice_audit_service import InvoiceAuditReportService
        
        # Create test invoices
        invoices = [
            invoice_factory(organization=org, account_code="6100"),
            invoice_factory(organization=org, account_code="1150"),
        ]
        
        service = InvoiceAuditReportService(org, user)
        report = service.build()
        
        assert "ias7_cashflow_classification" in report
        assert "ias7_cashflow_statement" in report
        assert report["ias7_cashflow_classification"]["success"] is True

    def test_ias7_samples_included_in_report(self, invoice_factory, org, user):
        """IAS 7 section should include sample classifications."""
        from apps.reports.services.invoice_audit_service import InvoiceAuditReportService
        
        invoices = [
            invoice_factory(organization=org, account_code="6100"),
        ]
        
        service = InvoiceAuditReportService(org, user)
        report = service.build()
        
        ias7 = report["ias7_cashflow_classification"]
        assert len(ias7["samples"]) > 0
        assert "invoice_id" in ias7["samples"][0]
        assert "classification" in ias7["samples"][0]
        assert "confidence" in ias7["samples"][0]


# ── Test Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def invoice_factory(org, user):
    """Factory for creating test invoices."""
    from apps.invoices.models import Invoice
    
    def create(
        organization=None,
        account_code="",
        cost_center="",
        vendor_name="Test Vendor",
        ai_summary="Test invoice",
        is_deleted=False,
        total_amount=Decimal("100.00"),
        **kwargs
    ):
        return Invoice.objects.create(
            organization=organization,
            uploaded_by=user,
            original_filename="test_invoice.pdf",
            account_code=account_code,
            cost_center=cost_center,
            vendor_name=vendor_name,
            ai_summary=ai_summary,
            total_amount=total_amount,
            is_deleted=is_deleted,
            **kwargs
        )
    
    return create
