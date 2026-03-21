"""
Tests for BNK-M01 Balance Reconciliation Rule.
Covers 8 required test cases.
"""
import pytest
from apps.rule_engine.rules.bank_statement.balance_reconciliation_rule import BalanceReconciliationRule
from apps.rule_engine.rules.base import NormalizedDocument, RuleStatus


def make_bank_doc(**kwargs):
    defaults = {
        "opening_balance": 100000,
        "total_credits": 50000,
        "total_debits": 80000,
        "closing_balance": 70000,  # 100k + 50k - 80k = 70k (correct)
    }
    defaults.update(kwargs)
    return NormalizedDocument(
        document_id="test-bank-001",
        document_type="bank_statement",
        organization_id="org-001",
        total_amount=70000,
        typed_data=defaults,
    )


class TestBalanceReconciliationRule:

    def test_pass_case(self):
        doc = make_bank_doc()
        rule = BalanceReconciliationRule()
        result = rule.execute(doc)
        assert result.status == RuleStatus.PASS

    def test_fail_case(self):
        doc = make_bank_doc(closing_balance=80000)  # Should be 70000
        rule = BalanceReconciliationRule()
        result = rule.execute(doc)
        assert result.status == RuleStatus.FAIL

    def test_boundary_case_within_tolerance(self):
        # Default tolerance is 0.01 — discrepancy of 0.005 should pass
        doc = make_bank_doc(closing_balance=70000.005)
        rule = BalanceReconciliationRule()
        result = rule.execute(doc)
        assert result.status == RuleStatus.PASS

    def test_boundary_case_over_tolerance(self):
        doc = make_bank_doc(closing_balance=70000.02)  # 0.02 > default tolerance 0.01
        rule = BalanceReconciliationRule()
        result = rule.execute(doc)
        assert result.status == RuleStatus.FAIL

    def test_precondition_not_met(self):
        doc = NormalizedDocument(
            document_id="test-002",
            document_type="bank_statement",
            organization_id="org-001",
            typed_data={"opening_balance": 100000},  # Missing other fields
        )
        rule = BalanceReconciliationRule()
        assert rule.check_preconditions(doc) is False

    def test_config_override_tolerance(self):
        doc = make_bank_doc(closing_balance=70100)  # 100 discrepancy
        rule = BalanceReconciliationRule(config={"tolerance": "200"})  # Override to 200
        result = rule.execute(doc)
        assert result.status == RuleStatus.PASS

    def test_arabic_output_on_fail(self):
        doc = make_bank_doc(closing_balance=80000)
        rule = BalanceReconciliationRule()
        result = rule.execute(doc)
        assert result.status == RuleStatus.FAIL
        assert len(result.explanation_ar) > 0
        assert "الرصيد" in result.explanation_ar

    def test_evidence_structure_on_fail(self):
        doc = make_bank_doc(closing_balance=80000)
        rule = BalanceReconciliationRule()
        result = rule.execute(doc)
        assert result.status == RuleStatus.FAIL
        assert len(result.evidence) == 1
        ev = result.evidence[0]
        assert ev.evidence_type == "calculation"
        assert ev.field_name == "closing_balance"
        assert ev.expected_value == 70000.0
        assert ev.actual_value == 80000.0

    def test_no_exception_on_malformed_input(self):
        doc = make_bank_doc(
            opening_balance="not_a_number",
            closing_balance=None,
        )
        rule = BalanceReconciliationRule()
        # Should not raise — either pass or fail gracefully
        try:
            result = rule.execute(doc)
            assert result.status in (RuleStatus.PASS, RuleStatus.FAIL, RuleStatus.ERROR, RuleStatus.SKIPPED)
        except Exception:
            pytest.fail("Rule raised an exception on malformed input")
