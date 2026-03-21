"""Tests for tax return rules: TAX-M01, TAX-M02, TAX-M08"""
import pytest
from datetime import date, timedelta
from apps.rule_engine.rules.base import NormalizedDocument, RuleStatus
from apps.rule_engine.rules.tax_return.tax_return_rules import (
    NetVATArithmeticRule,
    LateFilingRule,
    ZATCAReferenceRule,
)


def make_doc(**kwargs) -> NormalizedDocument:
    typed = kwargs.pop("typed_data", {})
    defaults = dict(
        document_id="test-tax-001",
        document_type="tax_return",
        organization_id="org-001",
    )
    defaults.update(kwargs)
    return NormalizedDocument(**defaults, typed_data=typed)


# ─── TAX-M01: NetVATArithmeticRule ───────────────────────────────────────────

class TestNetVATArithmeticRule:
    def setup_method(self):
        self.rule = NetVATArithmeticRule()

    def test_pass_correct_arithmetic(self):
        # output_vat - input_vat = net_vat_payable
        doc = make_doc(typed_data={"output_vat": 10000, "input_vat": 3000, "net_vat_payable": 7000})
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.PASS

    def test_fail_wrong_net(self):
        doc = make_doc(typed_data={"output_vat": 10000, "input_vat": 3000, "net_vat_payable": 8000})
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.FAIL

    def test_pass_within_tolerance(self):
        # Discrepancy of 0.50 — within SAR 1 tolerance
        doc = make_doc(typed_data={"output_vat": 10000, "input_vat": 3000, "net_vat_payable": 7000.50})
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.PASS

    def test_fail_just_over_tolerance(self):
        # Discrepancy of 1.01
        doc = make_doc(typed_data={"output_vat": 10000, "input_vat": 3000, "net_vat_payable": 7001.01})
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.FAIL

    def test_precondition_requires_all_fields(self):
        assert not self.rule.check_preconditions(make_doc(typed_data={"output_vat": 1000, "input_vat": 300}))
        assert not self.rule.check_preconditions(make_doc(typed_data={"output_vat": 1000, "net_vat_payable": 700}))
        assert not self.rule.check_preconditions(make_doc(typed_data={"input_vat": 300, "net_vat_payable": 700}))
        assert self.rule.check_preconditions(make_doc(typed_data={"output_vat": 1000, "input_vat": 300, "net_vat_payable": 700}))

    def test_evidence_on_fail(self):
        doc = make_doc(typed_data={"output_vat": 1000, "input_vat": 300, "net_vat_payable": 800})
        result = self.rule.execute(doc)
        assert result.evidence[0].field_name == "net_vat_payable"

    def test_arabic_on_fail(self):
        doc = make_doc(typed_data={"output_vat": 1000, "input_vat": 300, "net_vat_payable": 800})
        result = self.rule.execute(doc)
        assert result.explanation_ar != ""


# ─── TAX-M02: LateFilingRule ─────────────────────────────────────────────────

class TestLateFilingRule:
    def setup_method(self):
        self.rule = LateFilingRule()

    def test_pass_on_time(self):
        due = date.today() - timedelta(days=10)
        filed = due - timedelta(days=2)
        doc = make_doc(typed_data={"filing_date": filed.isoformat(), "due_date": due.isoformat()})
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.PASS

    def test_fail_late_filing(self):
        due = date.today() - timedelta(days=30)
        filed = due + timedelta(days=5)
        doc = make_doc(typed_data={"filing_date": filed.isoformat(), "due_date": due.isoformat()})
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.FAIL
        assert "5 days" in result.explanation_en

    def test_precondition_requires_both_dates(self):
        assert not self.rule.check_preconditions(make_doc(typed_data={"filing_date": "2024-01-15"}))
        assert not self.rule.check_preconditions(make_doc(typed_data={"due_date": "2024-01-10"}))
        assert self.rule.check_preconditions(make_doc(typed_data={"filing_date": "2024-01-15", "due_date": "2024-01-10"}))

    def test_uses_precomputed_is_late(self):
        # is_late_filing=True overrides date comparison
        doc = make_doc(typed_data={
            "filing_date": "2024-01-08",
            "due_date": "2024-01-10",
            "is_late_filing": True,
        })
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.FAIL

    def test_arabic_on_fail(self):
        due = date.today() - timedelta(days=20)
        filed = due + timedelta(days=3)
        doc = make_doc(typed_data={"filing_date": filed.isoformat(), "due_date": due.isoformat()})
        result = self.rule.execute(doc)
        assert result.explanation_ar != ""


# ─── TAX-M08: ZATCAReferenceRule ─────────────────────────────────────────────

class TestZATCAReferenceRule:
    def setup_method(self):
        self.rule = ZATCAReferenceRule()

    def test_pass_accepted_with_reference(self):
        doc = make_doc(typed_data={"filing_status": "accepted", "zatca_reference": "ZATCA-2024-001234"})
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.PASS

    def test_fail_accepted_missing_reference(self):
        doc = make_doc(typed_data={"filing_status": "accepted", "zatca_reference": ""})
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.FAIL

    def test_not_applicable_for_pending(self):
        doc = make_doc(typed_data={"filing_status": "pending"})
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.NOT_APPLICABLE

    def test_not_applicable_for_draft(self):
        doc = make_doc(typed_data={"filing_status": "draft"})
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.NOT_APPLICABLE

    def test_pass_submitted_with_reference(self):
        doc = make_doc(typed_data={"filing_status": "submitted", "zatca_reference": "REF-001"})
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.PASS

    def test_fail_accepted_none_reference(self):
        doc = make_doc(typed_data={"filing_status": "ACCEPTED", "zatca_reference": None})
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.FAIL

    def test_arabic_on_fail(self):
        doc = make_doc(typed_data={"filing_status": "accepted"})
        result = self.rule.execute(doc)
        assert result.explanation_ar != ""
