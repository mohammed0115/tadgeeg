"""Tests for expense rules: EXP-M01, EXP-M02, EXP-M07, EXP-M09"""
import pytest
from apps.rule_engine.rules.base import NormalizedDocument, RuleStatus
from apps.rule_engine.rules.expense.expense_rules import (
    MissingReceiptRule,
    ExpensePolicyLimitRule,
    SelfApprovalRule,
    ExpenseTotalMatchRule,
)


def make_doc(**kwargs) -> NormalizedDocument:
    typed = kwargs.pop("typed_data", {})
    defaults = dict(
        document_id="test-exp-001",
        document_type="expense",
        organization_id="org-001",
    )
    defaults.update(kwargs)
    return NormalizedDocument(**defaults, typed_data=typed)


# ─── EXP-M01: MissingReceiptRule ─────────────────────────────────────────────

class TestMissingReceiptRule:
    def setup_method(self):
        self.rule = MissingReceiptRule()

    def test_pass_all_receipts_attached(self):
        doc = make_doc(typed_data={"expense_lines": [
            {"amount": 100, "receipt_attached": True},
            {"amount": 200, "receipt_attached": True},
        ]})
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.PASS

    def test_fail_missing_receipt(self):
        doc = make_doc(typed_data={"expense_lines": [
            {"amount": 100, "receipt_attached": True},
            {"amount": 200, "receipt_attached": False},
        ]})
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.FAIL

    def test_fail_uses_precomputed_count(self):
        doc = make_doc(typed_data={
            "expense_lines": [],
            "missing_receipts_count": 3,
        })
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.FAIL
        assert "3" in result.explanation_en

    def test_precondition_requires_lines(self):
        doc = make_doc(typed_data={"expense_lines": []})
        assert not self.rule.check_preconditions(doc)

    def test_precondition_met_with_lines(self):
        doc = make_doc(typed_data={"expense_lines": [{"amount": 100}]})
        assert self.rule.check_preconditions(doc)

    def test_arabic_on_fail(self):
        doc = make_doc(typed_data={"expense_lines": [{"amount": 100, "receipt_attached": False}]})
        result = self.rule.execute(doc)
        assert result.explanation_ar != ""

    def test_zero_amount_line_ignored(self):
        # Lines with 0 amount don't need receipts
        doc = make_doc(typed_data={"expense_lines": [
            {"amount": 0, "receipt_attached": False},
        ]})
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.PASS


# ─── EXP-M02: ExpensePolicyLimitRule ─────────────────────────────────────────

class TestExpensePolicyLimitRule:
    def setup_method(self):
        self.rule = ExpensePolicyLimitRule()

    def test_pass_within_limits(self):
        doc = make_doc(typed_data={"expense_lines": [
            {"category": "meals", "amount": 100},  # limit 150
        ]})
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.PASS

    def test_fail_over_limit(self):
        doc = make_doc(typed_data={"expense_lines": [
            {"category": "meals", "amount": 300},  # limit 150
        ]})
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.FAIL

    def test_fail_uses_precomputed_count(self):
        doc = make_doc(typed_data={
            "expense_lines": [],
            "over_policy_limit_count": 2,
        })
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.FAIL

    def test_uses_other_category_for_unknown(self):
        doc = make_doc(typed_data={"expense_lines": [
            {"category": "unknown_type", "amount": 999},  # other limit = 1000
        ]})
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.PASS

    def test_arabic_on_fail(self):
        doc = make_doc(typed_data={"expense_lines": [
            {"category": "meals", "amount": 500},
        ]})
        result = self.rule.execute(doc)
        assert result.explanation_ar != ""


# ─── EXP-M07: SelfApprovalRule ───────────────────────────────────────────────

class TestSelfApprovalRule:
    def setup_method(self):
        self.rule = SelfApprovalRule()

    def test_fail_self_approval(self):
        doc = make_doc(
            approved_by_id="emp-123",
            typed_data={"employee_id": "emp-123"},
        )
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.FAIL

    def test_pass_different_approver(self):
        doc = make_doc(
            approved_by_id="mgr-456",
            typed_data={"employee_id": "emp-123"},
        )
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.PASS

    def test_precondition_requires_both_ids(self):
        doc_no_approver = make_doc(typed_data={"employee_id": "emp-123"})
        assert not self.rule.check_preconditions(doc_no_approver)

        doc_no_employee = make_doc(approved_by_id="mgr-456")
        assert not self.rule.check_preconditions(doc_no_employee)

    def test_precondition_met_with_both(self):
        doc = make_doc(approved_by_id="mgr-456", typed_data={"employee_id": "emp-123"})
        assert self.rule.check_preconditions(doc)

    def test_arabic_on_fail(self):
        doc = make_doc(approved_by_id="emp-123", typed_data={"employee_id": "emp-123"})
        result = self.rule.execute(doc)
        assert result.explanation_ar != ""


# ─── EXP-M09: ExpenseTotalMatchRule ──────────────────────────────────────────

class TestExpenseTotalMatchRule:
    def setup_method(self):
        self.rule = ExpenseTotalMatchRule()

    def test_pass_total_matches(self):
        doc = make_doc(typed_data={
            "expense_lines": [{"amount": 100}, {"amount": 200}],
            "total_claimed": 300,
        })
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.PASS

    def test_fail_total_mismatch(self):
        doc = make_doc(typed_data={
            "expense_lines": [{"amount": 100}, {"amount": 200}],
            "total_claimed": 350,  # discrepancy = 50
        })
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.FAIL

    def test_pass_within_penny_tolerance(self):
        doc = make_doc(typed_data={
            "expense_lines": [{"amount": "100.005"}],
            "total_claimed": "100.00",
        })
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.PASS

    def test_precondition_requires_total_claimed(self):
        doc = make_doc(typed_data={"expense_lines": [{"amount": 100}]})
        assert not self.rule.check_preconditions(doc)

    def test_precondition_requires_lines(self):
        doc = make_doc(typed_data={"expense_lines": [], "total_claimed": 100})
        assert not self.rule.check_preconditions(doc)

    def test_evidence_on_fail(self):
        doc = make_doc(typed_data={
            "expense_lines": [{"amount": 100}],
            "total_claimed": 200,
        })
        result = self.rule.execute(doc)
        assert len(result.evidence) == 1
        assert result.evidence[0].field_name == "total_claimed"

    def test_arabic_on_fail(self):
        doc = make_doc(typed_data={
            "expense_lines": [{"amount": 100}],
            "total_claimed": 200,
        })
        result = self.rule.execute(doc)
        assert result.explanation_ar != ""
