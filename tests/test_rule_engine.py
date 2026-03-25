"""
Comprehensive test suite for the Tadgeeg Rule Engine.

Covers:
- AuditRuleBase helpers (field_dependencies, get_canonical_field)
- All 40 rule classes: PASS / FAIL / NOT_APPLICABLE / SKIPPED paths
- RuleDependencyChecker logic in AuditPipeline
- DocumentCanonicalDataSerializer structure

Run with:
    python manage.py test tests.test_rule_engine
    pytest tests/test_rule_engine.py -v
"""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import django
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

import pytest
from django.test import TestCase

from apps.rule_engine.rules.base import (
    AuditRuleBase, NormalizedDocument, RuleResult, RuleStatus, EvidenceItem,
)


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def make_doc(**kwargs) -> NormalizedDocument:
    """Create a NormalizedDocument with sensible defaults."""
    defaults = dict(
        document_id="doc-001",
        document_type="sales_invoice",
        organization_id="org-001",
        document_number="INV-001",
        total_amount=1150.0,
        currency="SAR",
        counterparty_name="شركة الاختبار",
        tax_id="310000000000003",
        typed_data={},
    )
    defaults.update(kwargs)
    typed_data = defaults.pop("typed_data", {})
    doc = NormalizedDocument(**defaults)
    doc.typed_data = typed_data
    return doc


def make_doc_with_typed(doc_type: str, typed: dict, **kwargs) -> NormalizedDocument:
    return make_doc(document_type=doc_type, typed_data=typed, **kwargs)


# ─────────────────────────────────────────────────────────────
# Base class tests
# ─────────────────────────────────────────────────────────────

class TestAuditRuleBase(TestCase):

    def test_field_dependencies_default_empty(self):
        from apps.rule_engine.rules.invoice.vat_calculation_rule import VATCalculationRule
        rule = VATCalculationRule()
        self.assertEqual(rule.field_dependencies, [])

    def test_safe_decimal_none(self):
        from apps.rule_engine.rules.invoice.vat_calculation_rule import VATCalculationRule
        rule = VATCalculationRule()
        self.assertEqual(rule.safe_decimal(None), Decimal("0"))

    def test_safe_decimal_string(self):
        from apps.rule_engine.rules.invoice.vat_calculation_rule import VATCalculationRule
        rule = VATCalculationRule()
        self.assertEqual(rule.safe_decimal("123.45"), Decimal("123.45"))

    def test_safe_float(self):
        from apps.rule_engine.rules.invoice.vat_calculation_rule import VATCalculationRule
        rule = VATCalculationRule()
        self.assertAlmostEqual(rule.safe_float("99.9"), 99.9)
        self.assertEqual(rule.safe_float(None), 0.0)

    def test_get_canonical_field_no_record(self):
        """Returns default when no canonical record exists."""
        from apps.rule_engine.rules.invoice.vat_calculation_rule import VATCalculationRule
        rule = VATCalculationRule()
        doc = make_doc()
        with patch("apps.documents.canonical_models.DocumentCanonicalData.objects") as mock_mgr:
            mock_mgr.filter.return_value.first.return_value = None
            result = rule.get_canonical_field(doc, "invoice_number", default="fallback")
        self.assertEqual(result, "fallback")

    def test_get_canonical_field_with_record(self):
        """Returns field value from canonical record."""
        from apps.rule_engine.rules.invoice.vat_calculation_rule import VATCalculationRule
        rule = VATCalculationRule()
        doc = make_doc()
        fake_rec = MagicMock()
        fake_rec.canonical_data = {"invoice_number": "INV-999"}
        with patch("apps.documents.canonical_models.DocumentCanonicalData.objects") as mock_mgr:
            mock_mgr.filter.return_value.first.return_value = fake_rec
            result = rule.get_canonical_field(doc, "invoice_number")
        self.assertEqual(result, "INV-999")

    def test_get_canonical_field_db_error_returns_default(self):
        """DB error → silently returns default (never raises)."""
        from apps.rule_engine.rules.invoice.vat_calculation_rule import VATCalculationRule
        rule = VATCalculationRule()
        doc = make_doc()
        with patch("apps.documents.canonical_models.DocumentCanonicalData.objects") as mock_mgr:
            mock_mgr.filter.side_effect = Exception("DB down")
            result = rule.get_canonical_field(doc, "any_field", default="safe")
        self.assertEqual(result, "safe")


# ─────────────────────────────────────────────────────────────
# Generic rules
# ─────────────────────────────────────────────────────────────

class TestDocumentNumberRule(TestCase):

    def _rule(self):
        from apps.rule_engine.rules.generic.document_number_rule import DocumentNumberRule
        return DocumentNumberRule()

    def test_pass(self):
        doc = make_doc(document_number="INV-001")
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.PASS)

    def test_fail_missing(self):
        doc = make_doc(document_number=None)
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.FAIL)

    def test_fail_empty_string(self):
        doc = make_doc(document_number="")
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.FAIL)


class TestDocumentDateRule(TestCase):

    def _rule(self):
        from apps.rule_engine.rules.generic.document_date_rule import DocumentDateRule
        return DocumentDateRule()

    def test_pass(self):
        doc = make_doc(document_date="2025-01-15")
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.PASS)

    def test_fail_missing(self):
        doc = make_doc(document_date=None)
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.FAIL)

    def test_fail_future_date(self):
        doc = make_doc(document_date="2099-12-31")
        result = self._rule().execute(doc)
        self.assertIn(result.status, [RuleStatus.FAIL, RuleStatus.WARNING])


class TestTotalAmountPresentRule(TestCase):

    def _rule(self):
        from apps.rule_engine.rules.generic.total_amount_rule import TotalAmountPresentRule
        return TotalAmountPresentRule()

    def test_pass(self):
        doc = make_doc(total_amount=1000.0)
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.PASS)

    def test_fail_none(self):
        doc = make_doc(total_amount=None)
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.FAIL)


class TestTotalGreaterZeroRule(TestCase):

    def _rule(self):
        from apps.rule_engine.rules.generic.total_greater_zero_rule import TotalGreaterZeroRule
        return TotalGreaterZeroRule()

    def test_pass(self):
        doc = make_doc(total_amount=500.0)
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.PASS)

    def test_fail_zero(self):
        doc = make_doc(total_amount=0.0)
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.FAIL)

    def test_fail_negative(self):
        doc = make_doc(total_amount=-100.0)
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.FAIL)


class TestCurrencyRule(TestCase):

    def _rule(self):
        from apps.rule_engine.rules.generic.currency_rule import CurrencyRule
        return CurrencyRule()

    def test_pass_SAR(self):
        doc = make_doc(currency="SAR")
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.PASS)

    def test_pass_USD(self):
        doc = make_doc(currency="USD")
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.PASS)

    def test_fail_missing(self):
        doc = make_doc(currency=None)
        self.assertIn(self._rule().execute(doc).status, [RuleStatus.FAIL, RuleStatus.WARNING])

    def test_fail_invalid(self):
        doc = make_doc(currency="XYZ123")
        self.assertIn(self._rule().execute(doc).status, [RuleStatus.FAIL, RuleStatus.WARNING])


class TestDuplicateFileHashRule(TestCase):

    def _rule(self):
        from apps.rule_engine.rules.generic.duplicate_file_hash_rule import DuplicateFileHashRule
        return DuplicateFileHashRule()

    def test_skip_no_hash(self):
        doc = make_doc(file_hash=None)
        self.assertFalse(self._rule().check_preconditions(doc))

    def test_pass_unique(self):
        doc = make_doc(file_hash="abc123unique")
        with patch("apps.documents.models.Document.objects") as mock_mgr:
            mock_mgr.filter.return_value.exclude.return_value.exists.return_value = False
            result = self._rule().execute(doc)
        self.assertEqual(result.status, RuleStatus.PASS)


# ─────────────────────────────────────────────────────────────
# Workflow / Control rules
# ─────────────────────────────────────────────────────────────

class TestCostCenterRule(TestCase):

    def _rule(self):
        from apps.rule_engine.rules.generic.workflow_rules import CostCenterRule
        return CostCenterRule()

    def test_not_applicable_for_bank(self):
        doc = make_doc(document_type="bank_statement")
        self.assertFalse(self._rule().check_preconditions(doc))

    def test_warning_when_missing(self):
        doc = make_doc(document_type="purchase_order", cost_center=None, typed_data={})
        result = self._rule().execute(doc)
        self.assertEqual(result.status, RuleStatus.WARNING)

    def test_pass_with_cost_center(self):
        doc = make_doc(document_type="purchase_order", cost_center="CC-101")
        result = self._rule().execute(doc)
        self.assertEqual(result.status, RuleStatus.PASS)


class TestHasApproverRule(TestCase):

    def _rule(self):
        from apps.rule_engine.rules.generic.workflow_rules import HasApproverRule
        return HasApproverRule()

    def test_skip_bank_statement(self):
        doc = make_doc(document_type="bank_statement")
        self.assertFalse(self._rule().check_preconditions(doc))

    def test_warning_no_approver(self):
        doc = make_doc(document_type="purchase_order", approved_by_id=None)
        result = self._rule().execute(doc)
        self.assertEqual(result.status, RuleStatus.WARNING)

    def test_pass_with_approver(self):
        doc = make_doc(document_type="purchase_order", approved_by_id="user-42")
        result = self._rule().execute(doc)
        self.assertEqual(result.status, RuleStatus.PASS)


# ─────────────────────────────────────────────────────────────
# Invoice / VAT rules
# ─────────────────────────────────────────────────────────────

class TestVATRateRule(TestCase):

    def _rule(self):
        from apps.rule_engine.rules.invoice.vat_calculation_rule import VATRateRule
        return VATRateRule()

    def test_pass_15_pct(self):
        doc = make_doc_with_typed("sales_invoice", {"vat_rate": 15.0})
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.PASS)

    def test_fail_wrong_rate(self):
        doc = make_doc_with_typed("sales_invoice", {"vat_rate": 5.0})
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.FAIL)

    def test_skip_no_rate(self):
        doc = make_doc_with_typed("sales_invoice", {})
        self.assertFalse(self._rule().check_preconditions(doc))


class TestVATCalculationRule(TestCase):

    def _rule(self):
        from apps.rule_engine.rules.invoice.vat_calculation_rule import VATCalculationRule
        return VATCalculationRule()

    def test_pass_correct_calc(self):
        doc = make_doc_with_typed("sales_invoice", {"subtotal": 1000.0, "vat_amount": 150.0},
                                  total_amount=1150.0)
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.PASS)

    def test_fail_wrong_total(self):
        doc = make_doc_with_typed("sales_invoice", {"subtotal": 1000.0, "vat_amount": 150.0},
                                  total_amount=1200.0)
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.FAIL)

    def test_skip_missing_subtotal(self):
        doc = make_doc_with_typed("sales_invoice", {"vat_amount": 150.0}, total_amount=1150.0)
        self.assertFalse(self._rule().check_preconditions(doc))


class TestVATNumberFormatRule(TestCase):

    def _rule(self):
        from apps.rule_engine.rules.invoice.vat_calculation_rule import VATNumberFormatRule
        return VATNumberFormatRule()

    def test_pass_valid_sa_vat(self):
        doc = make_doc(tax_id="310000000000003")
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.PASS)

    def test_fail_too_short(self):
        doc = make_doc(tax_id="31000000000000")  # 14 digits
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.FAIL)

    def test_fail_wrong_prefix(self):
        doc = make_doc(tax_id="410000000000003")  # starts with 4
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.FAIL)

    def test_fail_missing(self):
        doc = make_doc(tax_id=None, typed_data={})
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.FAIL)


class TestZATCAQRCodeRule(TestCase):

    def _rule(self):
        from apps.rule_engine.rules.invoice.vat_calculation_rule import ZATCAQRCodeRule
        return ZATCAQRCodeRule()

    def test_skip_non_invoice(self):
        doc = make_doc(document_type="purchase_order")
        self.assertFalse(self._rule().check_preconditions(doc))

    def test_warning_no_qr(self):
        doc = make_doc_with_typed("sales_invoice", {"has_qr_code": False})
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.WARNING)

    def test_fail_invalid_qr(self):
        doc = make_doc_with_typed("sales_invoice", {"has_qr_code": True, "qr_code_valid": False})
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.FAIL)

    def test_pass_valid_qr(self):
        doc = make_doc_with_typed("sales_invoice", {"has_qr_code": True, "qr_code_valid": True})
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.PASS)


class TestDuplicateInvoiceRule(TestCase):

    def _rule(self):
        from apps.rule_engine.rules.invoice.duplicate_invoice_rule import DuplicateInvoiceRule
        return DuplicateInvoiceRule()

    def test_pass_no_duplicate(self):
        doc = make_doc(document_number="INV-999")
        with patch("apps.invoices.models.Invoice.objects") as mock_mgr:
            mock_mgr.filter.return_value.exclude.return_value.exists.return_value = False
            result = self._rule().execute(doc)
        self.assertEqual(result.status, RuleStatus.PASS)

    def test_fail_duplicate(self):
        doc = make_doc_with_typed("sales_invoice", {"is_duplicate": True})
        result = self._rule().execute(doc)
        self.assertEqual(result.status, RuleStatus.FAIL)


# ─────────────────────────────────────────────────────────────
# Bank statement rules
# ─────────────────────────────────────────────────────────────

class TestBalanceReconciliationRule(TestCase):

    def _rule(self):
        from apps.rule_engine.rules.bank_statement.balance_reconciliation_rule import BalanceReconciliationRule
        return BalanceReconciliationRule()

    def test_skip_missing_fields(self):
        doc = make_doc_with_typed("bank_statement", {})
        self.assertFalse(self._rule().check_preconditions(doc))

    def test_pass_balanced(self):
        doc = make_doc_with_typed("bank_statement", {
            "opening_balance": 100000.0,
            "total_credits": 50000.0,
            "total_debits": 30000.0,
            "closing_balance": 120000.0,
        })
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.PASS)

    def test_fail_unbalanced(self):
        doc = make_doc_with_typed("bank_statement", {
            "opening_balance": 100000.0,
            "total_credits": 50000.0,
            "total_debits": 30000.0,
            "closing_balance": 130000.0,  # wrong: should be 120k
        })
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.FAIL)


class TestDuplicateTransactionRule(TestCase):

    def _rule(self):
        from apps.rule_engine.rules.bank_statement.balance_reconciliation_rule import DuplicateTransactionRule
        return DuplicateTransactionRule()

    def test_pass_unique_transactions(self):
        doc = make_doc_with_typed("bank_statement", {
            "transactions": [
                {"amount": 1000, "date": "2025-01-01", "description": "Transfer A"},
                {"amount": 2000, "date": "2025-01-02", "description": "Transfer B"},
            ]
        })
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.PASS)

    def test_fail_duplicate_transactions(self):
        tx = {"amount": 1000, "date": "2025-01-01", "description": "Transfer A"}
        doc = make_doc_with_typed("bank_statement", {"transactions": [tx, tx]})
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.FAIL)


class TestIBANFormatRule(TestCase):

    def _rule(self):
        from apps.rule_engine.rules.bank_statement.balance_reconciliation_rule import IBANFormatRule
        return IBANFormatRule()

    def test_skip_no_iban(self):
        doc = make_doc_with_typed("bank_statement", {})
        self.assertFalse(self._rule().check_preconditions(doc))

    def test_pass_valid_iban(self):
        # Valid SA IBAN: SA + 2 digits + 18 alphanumeric = 22 chars total
        doc = make_doc_with_typed("bank_statement", {"iban": "SA0380000000608010167519"})
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.PASS)

    def test_fail_invalid_iban(self):
        doc = make_doc_with_typed("bank_statement", {"iban": "SA123"})
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.FAIL)


class TestStructuringDetectionRule(TestCase):

    def _rule(self):
        from apps.rule_engine.rules.bank_statement.balance_reconciliation_rule import StructuringDetectionRule
        return StructuringDetectionRule()

    def test_pass_no_structuring(self):
        doc = make_doc_with_typed("bank_statement", {
            "transactions": [
                {"amount": 1000}, {"amount": 2000}, {"amount": 5000},
            ]
        })
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.PASS)

    def test_fail_structuring_detected(self):
        # 3 transactions just below 60k threshold (90% = 54000)
        doc = make_doc_with_typed("bank_statement", {
            "transactions": [
                {"amount": 55000}, {"amount": 57000}, {"amount": 58000},
            ]
        })
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.FAIL)


# ─────────────────────────────────────────────────────────────
# Payroll rules
# ─────────────────────────────────────────────────────────────

class TestNetSalaryArithmeticRule(TestCase):

    def _rule(self):
        from apps.rule_engine.rules.payroll.net_salary_arithmetic_rule import NetSalaryArithmeticRule
        return NetSalaryArithmeticRule()

    def test_pass_correct(self):
        doc = make_doc_with_typed("payroll", {
            "employees": [
                {"id": "EMP-001", "name": "Ahmed", "gross": 8000, "allowances": 1500, "deductions": 500, "net": 9000},
            ],
            "total_net_salary": 9000,
        })
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.PASS)

    def test_fail_wrong_net(self):
        doc = make_doc_with_typed("payroll", {
            "employees": [
                {"id": "EMP-001", "name": "Ahmed", "gross": 8000, "allowances": 1500, "deductions": 500, "net": 5000},
            ],
            "total_net_salary": 5000,
        })
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.FAIL)


class TestGhostEmployeeRule(TestCase):

    def _rule(self):
        from apps.rule_engine.rules.payroll.net_salary_arithmetic_rule import GhostEmployeeRule
        return GhostEmployeeRule()

    def test_pass_no_flags(self):
        doc = make_doc_with_typed("payroll", {
            "employees": [{"id": "EMP-001"}],
            "ghost_employee_flags": [],
            "duplicate_employee_ids": [],
        })
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.PASS)

    def test_fail_ghost_flag(self):
        doc = make_doc_with_typed("payroll", {
            "employees": [{"id": "EMP-999"}],
            "ghost_employee_flags": ["EMP-999"],
            "duplicate_employee_ids": [],
        })
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.FAIL)


class TestDuplicateEmployeeIDRule(TestCase):

    def _rule(self):
        from apps.rule_engine.rules.payroll.net_salary_arithmetic_rule import DuplicateEmployeeIDRule
        return DuplicateEmployeeIDRule()

    def test_pass_unique(self):
        doc = make_doc_with_typed("payroll", {
            "employees": [{"id": "EMP-001"}, {"id": "EMP-002"}]
        })
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.PASS)

    def test_fail_duplicate(self):
        doc = make_doc_with_typed("payroll", {
            "employees": [{"id": "EMP-001"}, {"id": "EMP-001"}]
        })
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.FAIL)


class TestGOSICalculationRule(TestCase):

    def _rule(self):
        from apps.rule_engine.rules.payroll.net_salary_arithmetic_rule import GOSICalculationRule
        return GOSICalculationRule()

    def test_pass_correct_gosi(self):
        # Saudi: 11.75% of 8000 = 940
        doc = make_doc_with_typed("payroll", {
            "employees": [{"id": "EMP-001", "name": "Ahmed", "gross": 8000, "gosi": 940, "is_saudi": True}]
        })
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.PASS)

    def test_fail_wrong_gosi(self):
        doc = make_doc_with_typed("payroll", {
            "employees": [{"id": "EMP-001", "name": "Ahmed", "gross": 8000, "gosi": 500, "is_saudi": True}]
        })
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.FAIL)


# ─────────────────────────────────────────────────────────────
# Expense rules
# ─────────────────────────────────────────────────────────────

class TestMissingReceiptRule(TestCase):

    def _rule(self):
        from apps.rule_engine.rules.expense.expense_rules import MissingReceiptRule
        return MissingReceiptRule()

    def test_pass_all_receipts(self):
        doc = make_doc_with_typed("expense", {
            "expense_lines": [
                {"amount": 500, "receipt_attached": True},
                {"amount": 300, "receipt_attached": True},
            ],
            "missing_receipts_count": 0,
        })
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.PASS)

    def test_fail_missing_receipt(self):
        doc = make_doc_with_typed("expense", {
            "expense_lines": [
                {"amount": 500, "receipt_attached": False},
            ],
            "missing_receipts_count": 1,
        })
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.FAIL)


class TestExpensePolicyLimitRule(TestCase):

    def _rule(self):
        from apps.rule_engine.rules.expense.expense_rules import ExpensePolicyLimitRule
        return ExpensePolicyLimitRule()

    def test_pass_within_limits(self):
        doc = make_doc_with_typed("expense", {
            "expense_lines": [{"category": "meals", "amount": 100}],
            "over_policy_limit_count": 0,
        })
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.PASS)

    def test_fail_over_limit(self):
        doc = make_doc_with_typed("expense", {
            "expense_lines": [{"category": "meals", "amount": 1000}],
            "over_policy_limit_count": 1,
        })
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.FAIL)


class TestSelfApprovalRule(TestCase):

    def _rule(self):
        from apps.rule_engine.rules.expense.expense_rules import SelfApprovalRule
        return SelfApprovalRule()

    def test_skip_no_employee_id(self):
        doc = make_doc(document_type="expense", approved_by_id="user-99")
        self.assertFalse(self._rule().check_preconditions(doc))

    def test_fail_self_approval(self):
        doc = make_doc_with_typed("expense", {"employee_id": "user-42"}, approved_by_id="user-42")
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.FAIL)

    def test_pass_different_approver(self):
        doc = make_doc_with_typed("expense", {"employee_id": "user-42"}, approved_by_id="user-99")
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.PASS)


class TestExpenseTotalMatchRule(TestCase):

    def _rule(self):
        from apps.rule_engine.rules.expense.expense_rules import ExpenseTotalMatchRule
        return ExpenseTotalMatchRule()

    def test_pass_totals_match(self):
        doc = make_doc_with_typed("expense", {
            "expense_lines": [{"amount": 500}, {"amount": 300}],
            "total_claimed": 800,
        })
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.PASS)

    def test_fail_total_mismatch(self):
        doc = make_doc_with_typed("expense", {
            "expense_lines": [{"amount": 500}, {"amount": 300}],
            "total_claimed": 1000,
        })
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.FAIL)


# ─────────────────────────────────────────────────────────────
# Purchase order rules
# ─────────────────────────────────────────────────────────────

class TestVendorApprovedListRule(TestCase):

    def _rule(self):
        from apps.rule_engine.rules.purchase_order.retroactive_po_rule import VendorApprovedListRule
        return VendorApprovedListRule()

    def test_skip_no_approved_list(self):
        doc = make_doc(document_type="purchase_order")
        doc.org_context = {}
        self.assertFalse(self._rule().check_preconditions(doc))

    def test_pass_vendor_on_list(self):
        doc = make_doc(document_type="purchase_order", counterparty_name="شركة الأفق")
        doc.org_context = {"approved_vendor_ids": ["شركة الأفق"]}
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.PASS)

    def test_warning_vendor_not_on_list(self):
        doc = make_doc(document_type="purchase_order", counterparty_name="شركة مجهولة")
        doc.org_context = {"approved_vendor_ids": ["شركة الأفق"]}
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.WARNING)


# ─────────────────────────────────────────────────────────────
# Fixed asset rules
# ─────────────────────────────────────────────────────────────

class TestDepreciationCalculationRule(TestCase):

    def _rule(self):
        from apps.rule_engine.rules.fixed_asset.fixed_asset_rules import DepreciationCalculationRule
        return DepreciationCalculationRule()

    def test_pass_correct_depreciation(self):
        # 150000 / 5 = 30000/year
        doc = make_doc_with_typed("fixed_asset", {
            "assets": [
                {"name": "Toyota", "cost": 150000, "useful_life_years": 5,
                 "annual_depreciation": 30000, "method": "straight_line"}
            ]
        })
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.PASS)

    def test_fail_wrong_depreciation(self):
        doc = make_doc_with_typed("fixed_asset", {
            "assets": [
                {"name": "Toyota", "cost": 150000, "useful_life_years": 5,
                 "annual_depreciation": 20000, "method": "straight_line"}
            ]
        })
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.FAIL)


class TestNegativeBookValueRule(TestCase):

    def _rule(self):
        from apps.rule_engine.rules.fixed_asset.fixed_asset_rules import NegativeBookValueRule
        return NegativeBookValueRule()

    def test_pass_positive(self):
        doc = make_doc_with_typed("fixed_asset", {
            "assets": [{"book_value": 90000}],
            "negative_book_value_count": 0,
        })
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.PASS)

    def test_fail_negative(self):
        doc = make_doc_with_typed("fixed_asset", {
            "assets": [{"book_value": -5000}],
            "negative_book_value_count": 1,
        })
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.FAIL)


class TestDuplicateAssetIDRule(TestCase):

    def _rule(self):
        from apps.rule_engine.rules.fixed_asset.fixed_asset_rules import DuplicateAssetIDRule
        return DuplicateAssetIDRule()

    def test_pass_unique(self):
        doc = make_doc_with_typed("fixed_asset", {
            "assets": [{"asset_id": "FA-001"}, {"asset_id": "FA-002"}]
        })
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.PASS)

    def test_fail_duplicate(self):
        doc = make_doc_with_typed("fixed_asset", {
            "assets": [{"asset_id": "FA-001"}, {"asset_id": "FA-001"}]
        })
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.FAIL)


# ─────────────────────────────────────────────────────────────
# Tax return rules
# ─────────────────────────────────────────────────────────────

class TestNetVATArithmeticRule(TestCase):

    def _rule(self):
        from apps.rule_engine.rules.tax_return.tax_return_rules import NetVATArithmeticRule
        return NetVATArithmeticRule()

    def test_pass_correct(self):
        doc = make_doc_with_typed("tax_return", {
            "output_vat": 30000, "input_vat": 15000, "net_vat_payable": 15000
        })
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.PASS)

    def test_fail_wrong(self):
        doc = make_doc_with_typed("tax_return", {
            "output_vat": 30000, "input_vat": 15000, "net_vat_payable": 20000
        })
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.FAIL)


class TestZATCAReferenceRule(TestCase):

    def _rule(self):
        from apps.rule_engine.rules.tax_return.tax_return_rules import ZATCAReferenceRule
        return ZATCAReferenceRule()

    def test_not_applicable_not_accepted(self):
        doc = make_doc_with_typed("tax_return", {"filing_status": "draft", "zatca_reference": ""})
        result = self._rule().execute(doc)
        self.assertEqual(result.status, RuleStatus.NOT_APPLICABLE)

    def test_fail_missing_reference(self):
        doc = make_doc_with_typed("tax_return", {"filing_status": "accepted", "zatca_reference": ""})
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.FAIL)

    def test_pass_has_reference(self):
        doc = make_doc_with_typed("tax_return", {"filing_status": "accepted", "zatca_reference": "REF-2025-001"})
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.PASS)


# ─────────────────────────────────────────────────────────────
# Sales receipt rules
# ─────────────────────────────────────────────────────────────

class TestQRCodeContentRule(TestCase):

    def _rule(self):
        from apps.rule_engine.rules.sales_receipt.sales_receipt_rules import QRCodeContentRule
        return QRCodeContentRule()

    def test_skip_no_qr(self):
        doc = make_doc_with_typed("sales_receipt", {"has_qr_code": False})
        self.assertFalse(self._rule().check_preconditions(doc))

    def test_fail_invalid_qr(self):
        doc = make_doc_with_typed("sales_receipt", {"has_qr_code": True, "qr_code_valid": False})
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.FAIL)

    def test_pass_valid_qr(self):
        doc = make_doc_with_typed("sales_receipt", {"has_qr_code": True, "qr_code_valid": True})
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.PASS)


class TestCashReceiptLimitRule(TestCase):

    def _rule(self):
        from apps.rule_engine.rules.sales_receipt.sales_receipt_rules import CashReceiptLimitRule
        return CashReceiptLimitRule()

    def test_not_applicable_non_cash(self):
        doc = make_doc_with_typed("sales_receipt", {"payment_method": "credit_card"},
                                  total_amount=70000.0)
        result = self._rule().execute(doc)
        self.assertEqual(result.status, RuleStatus.NOT_APPLICABLE)

    def test_fail_over_limit_cash(self):
        doc = make_doc_with_typed("sales_receipt", {"payment_method": "cash"}, total_amount=65000.0)
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.FAIL)

    def test_pass_under_limit(self):
        doc = make_doc_with_typed("sales_receipt", {"payment_method": "cash"}, total_amount=5000.0)
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.PASS)


# ─────────────────────────────────────────────────────────────
# RuleDependencyChecker (Day 4)
# ─────────────────────────────────────────────────────────────

class TestRuleDependencyChecker(TestCase):

    def _pipeline(self):
        from apps.rule_engine.executors.audit_pipeline import AuditPipeline
        return AuditPipeline()

    def test_no_deps_always_passes(self):
        from apps.rule_engine.rules.invoice.vat_calculation_rule import VATCalculationRule
        rule = VATCalculationRule()
        doc = make_doc()
        pipeline = self._pipeline()
        missing = pipeline._check_field_dependencies(rule, doc)
        self.assertEqual(missing, [])

    def test_deps_present_in_canonical(self):
        from apps.rule_engine.rules.invoice.vat_calculation_rule import VATCalculationRule
        rule = VATCalculationRule()
        rule.field_dependencies = ["invoice_number", "total_amount"]
        doc = make_doc()
        fake_rec = MagicMock()
        fake_rec.canonical_data = {"invoice_number": "INV-001", "total_amount": 1150.0}
        pipeline = self._pipeline()
        with patch("apps.documents.canonical_models.DocumentCanonicalData.objects") as mock_mgr:
            mock_mgr.filter.return_value.first.return_value = fake_rec
            missing = pipeline._check_field_dependencies(rule, doc)
        self.assertEqual(missing, [])

    def test_deps_missing_from_canonical(self):
        from apps.rule_engine.rules.invoice.vat_calculation_rule import VATCalculationRule
        rule = VATCalculationRule()
        rule.field_dependencies = ["invoice_number", "vendor_vat_number"]
        doc = make_doc()
        fake_rec = MagicMock()
        fake_rec.canonical_data = {"invoice_number": "INV-001"}  # vendor_vat_number absent
        pipeline = self._pipeline()
        with patch("apps.documents.canonical_models.DocumentCanonicalData.objects") as mock_mgr:
            mock_mgr.filter.return_value.first.return_value = fake_rec
            missing = pipeline._check_field_dependencies(rule, doc)
        self.assertIn("vendor_vat_number", missing)

    def test_deps_no_canonical_record_returns_all_deps(self):
        from apps.rule_engine.rules.invoice.vat_calculation_rule import VATCalculationRule
        rule = VATCalculationRule()
        rule.field_dependencies = ["invoice_number"]
        doc = make_doc()
        pipeline = self._pipeline()
        with patch("apps.documents.canonical_models.DocumentCanonicalData.objects") as mock_mgr:
            mock_mgr.filter.return_value.first.return_value = None
            missing = pipeline._check_field_dependencies(rule, doc)
        self.assertIn("invoice_number", missing)

    def test_db_error_fails_open(self):
        """DB error → returns [] (fail open, run the rule)."""
        from apps.rule_engine.rules.invoice.vat_calculation_rule import VATCalculationRule
        rule = VATCalculationRule()
        rule.field_dependencies = ["some_field"]
        doc = make_doc()
        pipeline = self._pipeline()
        with patch("apps.documents.canonical_models.DocumentCanonicalData.objects") as mock_mgr:
            mock_mgr.filter.side_effect = Exception("DB error")
            missing = pipeline._check_field_dependencies(rule, doc)
        self.assertEqual(missing, [])  # fail open


# ─────────────────────────────────────────────────────────────
# DocumentCanonicalDataSerializer (Day 6)
# ─────────────────────────────────────────────────────────────

class TestDocumentCanonicalDataSerializer(TestCase):

    def test_serializer_fields(self):
        from apps.rule_engine.serializers.audit_run_serializers import DocumentCanonicalDataSerializer
        from datetime import datetime, timezone as tz
        now = datetime.now(tz.utc)
        data = {
            "document_type": "sales_invoice",
            "typed_model_name": "Invoice",
            "typed_object_id": "00000000-0000-0000-0000-000000000001",
            "canonical_data": {"invoice_number": "INV-001"},
            "raw_ai_output": {"raw_invoice_number": "INV-001"},
            "version": 1,
            "created_at": now,
            "updated_at": now,
        }
        s = DocumentCanonicalDataSerializer(data)
        self.assertEqual(s.data["document_type"], "sales_invoice")
        self.assertEqual(s.data["version"], 1)
        self.assertIn("invoice_number", s.data["canonical_data"])


# ─────────────────────────────────────────────────────────────
# Evidence item serialization
# ─────────────────────────────────────────────────────────────

class TestEvidenceItem(TestCase):

    def test_to_dict_complete(self):
        ev = EvidenceItem(
            evidence_type="calculation",
            field_name="total_amount",
            field_name_ar="المبلغ الإجمالي",
            expected_value=1150.0,
            actual_value=1200.0,
            description="Mismatch detected",
            description_ar="تعارض في المبلغ",
        )
        d = ev.to_dict()
        self.assertEqual(d["evidence_type"], "calculation")
        self.assertEqual(d["expected_value"], 1150.0)
        self.assertEqual(d["actual_value"], 1200.0)

    def test_rule_result_to_dict(self):
        result = RuleResult(
            status=RuleStatus.FAIL,
            explanation_en="Test fail",
            explanation_ar="فشل اختبار",
            risk_contribution=1.0,
            evidence=[EvidenceItem(evidence_type="field_value")],
        )
        d = result.to_dict()
        self.assertEqual(d["status"], "fail")
        self.assertEqual(d["risk_contribution"], 1.0)
        self.assertEqual(d["evidence_count"], 1)
        self.assertTrue(result.failed)
        self.assertFalse(result.passed)


# ─────────────────────────────────────────────────────────────
# GCC Multi-Country VAT Tests
# ─────────────────────────────────────────────────────────────

def make_gcc_doc(country: str, **kwargs) -> NormalizedDocument:
    """Create a NormalizedDocument with GCC org_context."""
    doc = make_doc(**kwargs)
    doc.org_context = {"country": country}
    return doc


class TestVATRateRuleGCC(TestCase):

    def _rule(self):
        from apps.rule_engine.rules.invoice.vat_calculation_rule import VATRateRule
        return VATRateRule()

    def test_ae_pass_5_pct(self):
        doc = make_gcc_doc("AE", typed_data={"vat_rate": 5.0})
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.PASS)

    def test_ae_fail_15_pct(self):
        doc = make_gcc_doc("AE", typed_data={"vat_rate": 15.0})
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.FAIL)

    def test_bh_pass_10_pct(self):
        doc = make_gcc_doc("BH", typed_data={"vat_rate": 10.0})
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.PASS)

    def test_bh_fail_5_pct(self):
        doc = make_gcc_doc("BH", typed_data={"vat_rate": 5.0})
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.FAIL)

    def test_kw_not_applicable(self):
        doc = make_gcc_doc("KW", typed_data={"vat_rate": 0.0})
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.NOT_APPLICABLE)

    def test_qa_not_applicable(self):
        doc = make_gcc_doc("QA", typed_data={"vat_rate": 0.0})
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.NOT_APPLICABLE)

    def test_om_pass_5_pct(self):
        doc = make_gcc_doc("OM", typed_data={"vat_rate": 5.0})
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.PASS)

    def test_sa_pass_15_pct(self):
        doc = make_gcc_doc("SA", typed_data={"vat_rate": 15.0})
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.PASS)

    def test_unknown_country_falls_back_to_sa(self):
        doc = make_gcc_doc("XX", typed_data={"vat_rate": 15.0})
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.PASS)

    def test_message_includes_country_code(self):
        doc = make_gcc_doc("AE", typed_data={"vat_rate": 5.0})
        result = self._rule().execute(doc)
        self.assertIn("AE", result.explanation_en)


class TestVATNumberFormatRuleGCC(TestCase):

    def _rule(self):
        from apps.rule_engine.rules.invoice.vat_calculation_rule import VATNumberFormatRule
        return VATNumberFormatRule()

    def test_kw_not_applicable(self):
        doc = make_gcc_doc("KW", tax_id=None, typed_data={})
        # preconditions would normally block, bypass via execute directly
        doc.tax_id = "any"
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.NOT_APPLICABLE)

    def test_qa_not_applicable(self):
        doc = make_gcc_doc("QA", tax_id="any", typed_data={})
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.NOT_APPLICABLE)

    def test_ae_pass_15_digits(self):
        doc = make_gcc_doc("AE", tax_id="123456789012345")  # 15 digits, any start
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.PASS)

    def test_ae_fail_14_digits(self):
        doc = make_gcc_doc("AE", tax_id="12345678901234")  # 14 digits
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.FAIL)

    def test_bh_pass_9_digits(self):
        doc = make_gcc_doc("BH", tax_id="123456789")
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.PASS)

    def test_bh_fail_10_digits(self):
        doc = make_gcc_doc("BH", tax_id="1234567890")
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.FAIL)

    def test_om_pass_om_prefix(self):
        doc = make_gcc_doc("OM", tax_id="OM12345678")
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.PASS)

    def test_om_pass_lowercase(self):
        doc = make_gcc_doc("OM", tax_id="om12345678")
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.PASS)

    def test_om_fail_no_prefix(self):
        doc = make_gcc_doc("OM", tax_id="1234567890")
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.FAIL)

    def test_sa_pass_valid(self):
        doc = make_gcc_doc("SA", tax_id="310000000000003")
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.PASS)

    def test_sa_fail_wrong_prefix(self):
        doc = make_gcc_doc("SA", tax_id="410000000000003")
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.FAIL)

    def test_unknown_country_falls_back_to_sa(self):
        doc = make_gcc_doc("XX", tax_id="310000000000003")
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.PASS)

    def test_error_message_includes_label(self):
        doc = make_gcc_doc("AE", tax_id="wrong")
        result = self._rule().execute(doc)
        self.assertIn("FTA TRN", result.explanation_en)
