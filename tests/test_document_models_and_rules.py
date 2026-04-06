"""
Document Typed Models & Rule Engine Integration Tests
Typed models (PurchaseOrder, etc.) extend AuditMixin and require a Document FK.
GAAP rules use full names: GAAPCompletenessCoreFieldsRule etc.
"""
import pytest
import uuid
from decimal import Decimal
from datetime import date


def make_doc(typed_data=None, org_context=None, **kwargs):
    from apps.rule_engine.rules.base import NormalizedDocument
    return NormalizedDocument(
        document_id=kwargs.pop("document_id", str(uuid.uuid4())),
        document_type=kwargs.pop("document_type", "invoice"),
        organization_id=kwargs.pop("organization_id", str(uuid.uuid4())),
        typed_data=typed_data or {},
        org_context=org_context or {},
        **kwargs,
    )


# ─── Typed document models ────────────────────────────────────────────────────

@pytest.mark.django_db
class TestTypedDocumentModels:
    """Typed models (PurchaseOrder etc.) extend AuditMixin and link via Document OneToOne."""

    @pytest.fixture
    def org(self, db):
        from apps.authentication.models import Organization
        return Organization.objects.create(
            name="Typed Org", name_ar="م", country="SA",
            currency="SAR", vat_number="300000000000007",
        )

    @pytest.fixture
    def user(self, db, org):
        from django.contrib.auth import get_user_model
        return get_user_model().objects.create_user(
            email="typed@test.finai", password="TypedPass1!",
            full_name="Typed User", organization=org,
        )

    @pytest.fixture
    def base_doc(self, db, org, user, tmp_path):
        """Create a base Document to link typed models to."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        from apps.documents.models import Document
        f = SimpleUploadedFile("base.pdf", b"%PDF-1.4", content_type="application/pdf")
        return Document.objects.create(
            organization=org, uploaded_by=user,
            original_filename="base.pdf", file=f,
            file_size=8, mime_type="application/pdf",
            document_type="purchase_order",
            processing_status="pending",
        )

    def _make_document(self, org, user, doc_type="invoice"):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from apps.documents.models import Document
        import uuid as _uuid
        fname = f"{_uuid.uuid4().hex[:6]}.pdf"
        f = SimpleUploadedFile(fname, b"%PDF-1.4", content_type="application/pdf")
        return Document.objects.create(
            organization=org, uploaded_by=user,
            original_filename=fname, file=f,
            file_size=8, mime_type="application/pdf",
            document_type=doc_type, processing_status="pending",
        )

    def test_purchase_order_created(self, db, org, user):
        from apps.documents.typed_models import PurchaseOrder
        doc = self._make_document(org, user, "purchase_order")
        po = PurchaseOrder.objects.create(
            organization=org, uploaded_by=user,
            document=doc,
            po_number="PO-00001", vendor_name="Test Vendor",
        )
        assert po.pk is not None
        assert po.po_number == "PO-00001"

    def test_bank_statement_created(self, db, org, user):
        from apps.documents.typed_models import BankStatement
        doc = self._make_document(org, user, "bank_statement")
        bs = BankStatement.objects.create(
            organization=org, uploaded_by=user,
            document=doc,
            account_number="SA1234567890", bank_name="Test Bank",
            statement_period_from=date(2026, 1, 1),
            statement_period_to=date(2026, 1, 31),
        )
        assert bs.pk is not None
        assert bs.account_number == "SA1234567890"

    def test_payroll_sheet_created(self, db, org, user):
        from apps.documents.typed_models import PayrollSheet
        doc = self._make_document(org, user, "payroll")
        pr = PayrollSheet.objects.create(
            organization=org, uploaded_by=user,
            document=doc,
            payroll_period_from=date(2026, 3, 1),
            payroll_period_to=date(2026, 3, 31),
        )
        assert pr.pk is not None

    def test_sales_receipt_created(self, db, org, user):
        from apps.documents.typed_models import SalesReceipt
        doc = self._make_document(org, user, "receipt")
        sr = SalesReceipt.objects.create(
            organization=org, uploaded_by=user,
            document=doc,
            receipt_number="REC-001",
            receipt_date=date(2026, 1, 15),
        )
        assert sr.pk is not None

    def test_po_links_to_document(self, db, org, user):
        from apps.documents.typed_models import PurchaseOrder
        from apps.documents.models import Document
        doc = self._make_document(org, user, "purchase_order")
        po = PurchaseOrder.objects.create(
            organization=org, uploaded_by=user,
            document=doc, po_number="PO-LINK-001",
        )
        assert po.document_id == doc.id
        assert isinstance(po.document, Document)


# ─── PAY-M04: Net salary arithmetic ──────────────────────────────────────────

@pytest.mark.unit
class TestNetSalaryArithmeticRule:
    def _rule(self):
        from apps.rule_engine.rules.payroll.net_salary_arithmetic_rule import NetSalaryArithmeticRule
        return NetSalaryArithmeticRule()

    def _doc(self, employees, total_net=None):
        calculated = sum(
            e.get("basic", 0) + e.get("allowances", 0) - e.get("deductions", 0)
            for e in employees
        )
        return make_doc(
            document_type="payroll",
            typed_data={
                "employees": employees,
                "total_net_salary": total_net if total_net is not None else float(calculated),
            },
        )

    def test_correct_net_passes(self):
        employees = [{"id": "E01", "name": "Ali", "basic": 10000, "allowances": 0, "deductions": 2000, "net": 8000}]
        assert self._rule().execute(self._doc(employees)).passed

    def test_wrong_employee_net_fails(self):
        employees = [{"id": "E01", "name": "Ali", "basic": 10000, "allowances": 0, "deductions": 2000, "net": 9000}]
        assert not self._rule().execute(self._doc(employees, total_net=9000)).passed

    def test_multiple_employees_correct(self):
        employees = [
            {"id": "E01", "basic": 8000, "allowances": 500, "deductions": 1000, "net": 7500},
            {"id": "E02", "basic": 12000, "allowances": 1000, "deductions": 2000, "net": 11000},
        ]
        assert self._rule().execute(self._doc(employees)).passed

    def test_empty_employees_fails_precondition(self):
        rule = self._rule()
        doc = make_doc(document_type="payroll", typed_data={"employees": []})
        assert not rule.check_preconditions(doc)

    def test_total_net_mismatch_fails(self):
        employees = [{"id": "E01", "basic": 5000, "allowances": 0, "deductions": 0, "net": 5000}]
        doc = make_doc(document_type="payroll", typed_data={
            "employees": employees, "total_net_salary": 9999,
        })
        assert not self._rule().execute(doc).passed

    def test_allowances_included_in_net(self):
        employees = [{"id": "E01", "basic": 8000, "allowances": 2000, "deductions": 1000, "net": 9000}]
        assert self._rule().execute(self._doc(employees)).passed

    def test_fail_explanation_is_non_empty(self):
        employees = [{"id": "E01", "basic": 10000, "allowances": 0, "deductions": 2000, "net": 9500}]
        result = self._rule().execute(self._doc(employees, total_net=9500))
        assert not result.passed
        assert result.explanation_en


# ─── BNK-M01: Balance reconciliation ─────────────────────────────────────────

@pytest.mark.unit
class TestBalanceReconciliationRule:
    def _rule(self):
        from apps.rule_engine.rules.bank_statement.balance_reconciliation_rule import BalanceReconciliationRule
        return BalanceReconciliationRule()

    def _doc(self, opening, closing, credits, debits):
        return make_doc(
            document_type="bank_statement",
            typed_data={
                "opening_balance": str(opening),
                "closing_balance": str(closing),
                "total_credits": str(credits),
                "total_debits": str(debits),
            },
        )

    def test_balanced_passes(self):
        assert self._rule().execute(self._doc(10000, 15000, 8000, 3000)).passed

    def test_unbalanced_fails(self):
        assert not self._rule().execute(self._doc(10000, 20000, 8000, 3000)).passed

    def test_zero_activity_passes(self):
        assert self._rule().execute(self._doc(5000, 5000, 0, 0)).passed

    def test_tiny_rounding_within_tolerance(self):
        assert self._rule().execute(self._doc(10000, 10500.01, 1000, 500)).passed

    def test_fail_has_explanation(self):
        result = self._rule().execute(self._doc(10000, 20000, 8000, 3000))
        assert not result.passed
        assert result.explanation_en


# ─── GAAP rules (actual class names) ─────────────────────────────────────────

@pytest.mark.unit
class TestGAAPRules:

    def test_completeness_rule_importable(self):
        from apps.rule_engine.rules.gaap.categories.completeness import GAAPCompletenessCoreFieldsRule
        rule = GAAPCompletenessCoreFieldsRule()
        assert hasattr(rule, "execute")
        assert rule.rule_code

    def test_revenue_recognition_rule_importable(self):
        from apps.rule_engine.rules.gaap.categories.recognition import GAAPRevenueRecognitionRule
        rule = GAAPRevenueRecognitionRule()
        assert hasattr(rule, "execute")

    def test_expense_matching_rule_importable(self):
        from apps.rule_engine.rules.gaap.categories.recognition import GAAPExpenseMatchingRule
        rule = GAAPExpenseMatchingRule()
        assert hasattr(rule, "execute")

    def test_anomaly_rule_importable(self):
        from apps.rule_engine.rules.gaap.categories.anomaly import GAAPAnomalyPatternRule
        rule = GAAPAnomalyPatternRule()
        assert hasattr(rule, "execute")

    def test_consistency_rule_importable(self):
        from apps.rule_engine.rules.gaap.categories.consistency import GAAPConsistencyTreatmentRule
        rule = GAAPConsistencyTreatmentRule()
        assert hasattr(rule, "execute")

    def test_cutoff_rule_importable(self):
        from apps.rule_engine.rules.gaap.categories.cutoff import GAAPCutoffPeriodRule
        rule = GAAPCutoffPeriodRule()
        assert hasattr(rule, "execute")

    def test_documentation_rule_importable(self):
        from apps.rule_engine.rules.gaap.categories.documentation import GAAPDocumentationSupportRule
        rule = GAAPDocumentationSupportRule()
        assert hasattr(rule, "execute")

    def test_classification_rule_importable(self):
        from apps.rule_engine.rules.gaap.categories.classification import GAAPClassificationCapexOpexRule
        rule = GAAPClassificationCapexOpexRule()
        assert hasattr(rule, "execute")

    def test_gaap_registry_importable(self):
        import dataclasses
        from apps.rule_engine.rules.gaap.registry import GAAPRuleDefinition
        assert GAAPRuleDefinition is not None
        # GAAPRuleDefinition is a frozen dataclass with rule_code as an instance field
        fields = [f.name for f in dataclasses.fields(GAAPRuleDefinition)]
        assert "rule_code" in fields
        assert "rule_class" in fields

    def test_all_gaap_rules_have_rule_codes(self):
        import importlib, inspect
        cats = ["completeness", "recognition", "anomaly", "consistency",
                "cutoff", "documentation", "classification"]
        for cat in cats:
            mod = importlib.import_module(f"apps.rule_engine.rules.gaap.categories.{cat}")
            classes = [obj for _, obj in inspect.getmembers(mod, inspect.isclass)
                       if hasattr(obj, "rule_code") and obj.rule_code
                       and obj.__name__ != "GAAPRuleBase"]
            assert len(classes) >= 1, f"No rules found in {cat}"
            for cls in classes:
                assert cls.rule_code, f"{cls.__name__} has empty rule_code"


# ─── Normalizers ──────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestNormalizerImports:

    def test_invoice_normalizer(self):
        from apps.rule_engine.normalizers.invoice_normalizer import InvoiceNormalizer
        assert InvoiceNormalizer() is not None

    def test_po_normalizer(self):
        from apps.rule_engine.normalizers.purchase_order_normalizer import PurchaseOrderNormalizer
        assert PurchaseOrderNormalizer() is not None

    def test_payroll_normalizer(self):
        from apps.rule_engine.normalizers.payroll_normalizer import PayrollNormalizer
        assert PayrollNormalizer() is not None

    def test_bank_normalizer(self):
        from apps.rule_engine.normalizers.bank_statement_normalizer import BankStatementNormalizer
        assert BankStatementNormalizer() is not None

    def test_expense_normalizer(self):
        from apps.rule_engine.normalizers.expense_normalizer import ExpenseNormalizer
        assert ExpenseNormalizer() is not None

    def test_tax_return_normalizer(self):
        from apps.rule_engine.normalizers.tax_return_normalizer import TaxReturnNormalizer
        assert TaxReturnNormalizer() is not None
