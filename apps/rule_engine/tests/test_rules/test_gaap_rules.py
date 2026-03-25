from datetime import date

from apps.rule_engine.rules.base import NormalizedDocument, RuleStatus
from apps.rule_engine.rules.gaap.categories.anomaly import GAAPAnomalyPatternRule
from apps.rule_engine.rules.gaap.categories.completeness import GAAPCompletenessCoreFieldsRule
from apps.rule_engine.rules.gaap.categories.cutoff import GAAPCutoffPeriodRule
from apps.rule_engine.rules.gaap.categories.documentation import GAAPDocumentationSupportRule
from apps.rule_engine.rules.gaap.categories.recognition import GAAPRevenueRecognitionRule


def make_doc(**kwargs):
    defaults = dict(
        document_id="gaap-rule-doc",
        document_type="sales_invoice",
        organization_id="org-1",
        document_number="INV-22",
        document_date=date(2026, 2, 10),
        total_amount=15000,
        currency="SAR",
        counterparty_name="Acme",
        account_code="4000",
        typed_data={},
        org_context={"period_start": "2026-02-01", "period_end": "2026-02-28"},
    )
    defaults.update(kwargs)
    return NormalizedDocument(**defaults)


def test_gaap_completeness_passes_with_required_fields():
    rule = GAAPCompletenessCoreFieldsRule()
    doc = make_doc(typed_data={"invoice_date": "2026-02-10", "invoice_number": "INV-22"})
    result = rule.execute(doc)
    assert result.status == RuleStatus.PASS


def test_gaap_completeness_fails_when_account_missing():
    rule = GAAPCompletenessCoreFieldsRule()
    doc = make_doc(account_code="")
    result = rule.execute(doc)
    assert result.status == RuleStatus.FAIL


def test_gaap_cutoff_fails_outside_period():
    rule = GAAPCutoffPeriodRule(config={"period_start": "2026-02-01", "period_end": "2026-02-28"})
    doc = make_doc(document_date=date(2026, 3, 2))
    result = rule.execute(doc)
    assert result.status == RuleStatus.FAIL


def test_gaap_documentation_not_applicable_under_threshold():
    rule = GAAPDocumentationSupportRule(config={"materiality_amount": "20000"})
    doc = make_doc(total_amount=5000)
    result = rule.execute(doc)
    assert result.status == RuleStatus.NOT_APPLICABLE


def test_gaap_revenue_recognition_flags_premature_recognition():
    rule = GAAPRevenueRecognitionRule()
    doc = make_doc(typed_data={"invoice_date": "2026-02-05", "delivery_date": "2026-02-12"})
    result = rule.execute(doc)
    assert result.status == RuleStatus.FAIL


def test_gaap_anomaly_warns_on_material_and_duplicate_pattern():
    rule = GAAPAnomalyPatternRule(config={"materiality_amount": "10000", "rounded_step": "1000"})
    doc = make_doc(
        total_amount=50000,
        typed_data={"duplicate_invoice_number": True},
    )
    result = rule.execute(doc)
    assert result.status == RuleStatus.WARNING
