from datetime import date

from apps.rule_engine.rules.base import NormalizedDocument
from apps.rule_engine.rules.gaap.engine import GAAPRuleEngine
from apps.rule_engine.rules.gaap.registry import get_definition_map, get_rule_definitions


def _doc(**typed_data):
    return NormalizedDocument(
        document_id="gaap-doc-1",
        document_type="sales_invoice",
        organization_id="org-1",
        document_number="INV-1",
        document_date=date(2026, 1, 15),
        total_amount=12000,
        currency="SAR",
        counterparty_name="Vendor A",
        account_code="4001",
        typed_data=typed_data,
        org_context={"period_start": "2026-01-01", "period_end": "2026-01-31"},
    )


def test_registry_contains_required_gaap_codes():
    defs = get_definition_map()
    for code in [
        "GAAP-COMP-001",
        "GAAP-CUT-001",
        "GAAP-DOC-001",
        "GAAP-CLS-001",
        "GAAP-REV-001",
        "GAAP-EXP-001",
        "GAAP-CONS-001",
        "GAAP-ANO-001",
    ]:
        assert code in defs


def test_engine_runs_and_builds_summary():
    engine = GAAPRuleEngine(get_rule_definitions())
    results = engine.evaluate(
        _doc(
            invoice_date="2026-01-15",
            delivery_date="2026-01-10",
            posting_date="2026-01-16",
            expected_account_code="4001",
            category="opex",
            has_attachment=True,
        )
    )

    assert len(results) >= 8
    summary = engine.build_summary(results)
    assert summary["total_rules"] == len(results)
    assert summary["gaap_score"] <= 100
