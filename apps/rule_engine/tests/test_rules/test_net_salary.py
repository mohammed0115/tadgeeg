"""Tests for PAY-M04 Net Salary Arithmetic Rule."""
import pytest
from apps.rule_engine.rules.payroll.net_salary_arithmetic_rule import NetSalaryArithmeticRule
from apps.rule_engine.rules.base import NormalizedDocument, RuleStatus


def make_payroll_doc(employees=None, total_net=None):
    if employees is None:
        employees = [
            {"id": "E001", "name": "Ahmed Ali", "gross": 10000, "allowances": 2000, "deductions": 1000, "net": 11000},
            {"id": "E002", "name": "Sara Khan", "gross": 8000, "allowances": 1500, "deductions": 800, "net": 8700},
        ]
    if total_net is None:
        total_net = sum(e["net"] for e in employees)

    return NormalizedDocument(
        document_id="payroll-001",
        document_type="payroll",
        organization_id="org-001",
        typed_data={
            "employees": employees,
            "total_net_salary": total_net,
        },
    )


class TestNetSalaryArithmeticRule:

    def test_pass_case(self):
        doc = make_payroll_doc()
        rule = NetSalaryArithmeticRule()
        result = rule.execute(doc)
        assert result.status == RuleStatus.PASS

    def test_fail_case_wrong_individual_net(self):
        employees = [
            {"id": "E001", "name": "Ahmed Ali", "gross": 10000, "allowances": 2000, "deductions": 1000, "net": 9000},  # Should be 11000
        ]
        doc = make_payroll_doc(employees=employees, total_net=9000)
        rule = NetSalaryArithmeticRule()
        result = rule.execute(doc)
        assert result.status == RuleStatus.FAIL
        assert "Ahmed Ali" in result.explanation_en

    def test_fail_case_wrong_total(self):
        employees = [
            {"id": "E001", "name": "Ahmed Ali", "gross": 10000, "allowances": 2000, "deductions": 1000, "net": 11000},
        ]
        doc = make_payroll_doc(employees=employees, total_net=9999)  # Wrong total
        rule = NetSalaryArithmeticRule()
        result = rule.execute(doc)
        assert result.status == RuleStatus.FAIL

    def test_boundary_case(self):
        employees = [
            {"id": "E001", "name": "Ahmed", "gross": 10000, "allowances": 2000, "deductions": 1000, "net": 11000.005},  # 0.005 tolerance
        ]
        doc = make_payroll_doc(employees=employees, total_net=11000.005)
        rule = NetSalaryArithmeticRule()
        result = rule.execute(doc)
        assert result.status == RuleStatus.PASS

    def test_precondition_not_met(self):
        doc = NormalizedDocument(
            document_id="payroll-002",
            document_type="payroll",
            organization_id="org-001",
            typed_data={"employees": []},
        )
        rule = NetSalaryArithmeticRule()
        assert rule.check_preconditions(doc) is False

    def test_arabic_output_on_fail(self):
        employees = [
            {"id": "E001", "name": "Test", "gross": 5000, "allowances": 0, "deductions": 0, "net": 9999},
        ]
        doc = make_payroll_doc(employees=employees, total_net=9999)
        rule = NetSalaryArithmeticRule()
        result = rule.execute(doc)
        assert result.status == RuleStatus.FAIL
        assert len(result.explanation_ar) > 0

    def test_evidence_structure(self):
        employees = [
            {"id": "E001", "name": "Ahmed Ali", "gross": 10000, "allowances": 2000, "deductions": 1000, "net": 9000},
        ]
        doc = make_payroll_doc(employees=employees, total_net=9000)
        rule = NetSalaryArithmeticRule()
        result = rule.execute(doc)
        assert result.status == RuleStatus.FAIL
        assert any(e.field_name == "net_salary" for e in result.evidence)

    def test_no_exception_on_malformed_input(self):
        employees = [{"id": "E001", "name": None, "gross": "bad", "net": None}]
        doc = make_payroll_doc(employees=employees, total_net=0)
        rule = NetSalaryArithmeticRule()
        try:
            result = rule.execute(doc)
            assert result.status in (RuleStatus.PASS, RuleStatus.FAIL, RuleStatus.ERROR)
        except Exception:
            pytest.fail("Rule raised exception on malformed input")
