"""Tests for generic rules: GEN-H01, GEN-H02, GEN-H05, GEN-H06, GEN-H07"""
import pytest
from datetime import date, timedelta
from apps.rule_engine.rules.base import NormalizedDocument, RuleStatus
from apps.rule_engine.rules.generic.document_number_rule import DocumentNumberRule
from apps.rule_engine.rules.generic.document_date_rule import DocumentDateRule
from apps.rule_engine.rules.generic.total_amount_rule import TotalAmountPresentRule
from apps.rule_engine.rules.generic.currency_rule import CurrencyRule
from apps.rule_engine.rules.generic.total_greater_zero_rule import TotalGreaterZeroRule


def make_doc(**kwargs) -> NormalizedDocument:
    typed = kwargs.pop("typed_data", {})
    defaults = dict(
        document_id="test-gen-001",
        document_type="sales_invoice",
        organization_id="org-001",
    )
    defaults.update(kwargs)
    return NormalizedDocument(**defaults, typed_data=typed)


# ─── GEN-H01: DocumentNumberRule ─────────────────────────────────────────────

class TestDocumentNumberRule:
    def setup_method(self):
        self.rule = DocumentNumberRule()

    def test_pass_with_number(self):
        doc = make_doc(document_number="INV-2024-001")
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.PASS

    def test_fail_missing_number(self):
        doc = make_doc(document_number=None)
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.FAIL

    def test_fail_empty_string(self):
        doc = make_doc(document_number="   ")
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.FAIL

    def test_pass_numeric_string(self):
        doc = make_doc(document_number="123456")
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.PASS

    def test_arabic_output_on_fail(self):
        doc = make_doc()
        result = self.rule.execute(doc)
        assert result.explanation_ar != ""

    def test_evidence_on_fail(self):
        doc = make_doc()
        result = self.rule.execute(doc)
        assert len(result.evidence) == 1
        assert result.evidence[0].field_name == "document_number"


# ─── GEN-H02: DocumentDateRule ───────────────────────────────────────────────

class TestDocumentDateRule:
    def setup_method(self):
        self.rule = DocumentDateRule()

    def test_pass_recent_date(self):
        doc = make_doc(document_date=date.today() - timedelta(days=30))
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.PASS

    def test_pass_future_date_present(self):
        # Rule only checks presence, not future-date logic
        doc = make_doc(document_date=date.today() + timedelta(days=5))
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.PASS

    def test_fail_missing_date(self):
        doc = make_doc(document_date=None)
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.FAIL

    def test_pass_date_as_string(self):
        past = (date.today() - timedelta(days=10)).isoformat()
        doc = make_doc(document_date=past)
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.PASS

    def test_arabic_output_on_fail(self):
        doc = make_doc(document_date=None)
        result = self.rule.execute(doc)
        assert result.explanation_ar != ""

    def test_evidence_on_fail(self):
        doc = make_doc(document_date=None)
        result = self.rule.execute(doc)
        assert len(result.evidence) == 1
        assert result.evidence[0].field_name == "document_date"


# ─── GEN-H05: TotalAmountPresentRule ─────────────────────────────────────────

class TestTotalAmountPresentRule:
    def setup_method(self):
        self.rule = TotalAmountPresentRule()

    def test_pass_with_total(self):
        doc = make_doc(total_amount=1000.0)
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.PASS

    def test_fail_missing_total(self):
        doc = make_doc(total_amount=None)
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.FAIL

    def test_pass_zero_total(self):
        # This rule only checks presence, not > 0 (that's GEN-H07)
        doc = make_doc(total_amount=0.0)
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.PASS

    def test_arabic_output_on_fail(self):
        doc = make_doc(total_amount=None)
        result = self.rule.execute(doc)
        assert result.explanation_ar != ""

    def test_evidence_on_fail(self):
        doc = make_doc(total_amount=None)
        result = self.rule.execute(doc)
        assert result.evidence[0].field_name == "total_amount"


# ─── GEN-H06: CurrencyRule ───────────────────────────────────────────────────

class TestCurrencyRule:
    def setup_method(self):
        self.rule = CurrencyRule()

    def test_pass_sar(self):
        doc = make_doc(currency="SAR")
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.PASS

    def test_pass_usd(self):
        doc = make_doc(currency="USD")
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.PASS

    def test_warning_invalid_currency(self):
        # Unknown currency gives WARNING (not hard FAIL) — rule is lenient
        doc = make_doc(currency="XYZ")
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.WARNING

    def test_fail_missing_currency(self):
        doc = make_doc(currency=None)
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.FAIL

    def test_arabic_output_on_fail(self):
        doc = make_doc(currency="ZZZ")
        result = self.rule.execute(doc)
        assert result.explanation_ar != ""


# ─── GEN-H07: TotalGreaterZeroRule ───────────────────────────────────────────

class TestTotalGreaterZeroRule:
    def setup_method(self):
        self.rule = TotalGreaterZeroRule()

    def test_pass_positive_amount(self):
        doc = make_doc(total_amount=500.0)
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.PASS

    def test_fail_zero_amount(self):
        doc = make_doc(total_amount=0.0)
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.FAIL

    def test_fail_negative_amount(self):
        doc = make_doc(total_amount=-100.0)
        result = self.rule.execute(doc)
        assert result.status == RuleStatus.FAIL

    def test_precondition_skips_tax_return(self):
        doc = make_doc(document_type="tax_return", total_amount=0.0)
        # Precondition returns False for tax_return — rule is skipped
        assert not self.rule.check_preconditions(doc)

    def test_precondition_skips_when_no_total(self):
        doc = make_doc(total_amount=None)
        assert not self.rule.check_preconditions(doc)

    def test_arabic_output_on_fail(self):
        doc = make_doc(total_amount=-50.0)
        result = self.rule.execute(doc)
        assert result.explanation_ar != ""
