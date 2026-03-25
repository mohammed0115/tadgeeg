from datetime import date

from apps.auditing.accounting_rules.engine import AccountingRulesEngine
from apps.auditing.accounting_rules.enums import AccountingStandard
from apps.auditing.accounting_rules.registry import AccountingRuleRegistry
from apps.auditing.accounting_rules.scoring import RuleScoringEngine


def _base_record(**kwargs):
    record = {
        "record_type": "invoice",
        "record_id": "INV-1",
        "date": "2026-03-10",
        "posting_date": "2026-03-10",
        "amount": 15000,
        "account": "4001",
        "counterparty": "Vendor A",
        "reference": "INV-1",
        "supporting_document": True,
        "delivery_date": "2026-03-09",
        "service_date": "2026-03-09",
        "description": "equipment maintenance",
        "category": "expense",
    }
    record.update(kwargs)
    return record


def test_rule_registry_loading_contains_gaap_and_ifrs_rules():
    AccountingRuleRegistry.ensure_loaded()
    gaap_rules = AccountingRuleRegistry.get_rules(standard=AccountingStandard.GAAP)
    ifrs_rules = AccountingRuleRegistry.get_rules(standard=AccountingStandard.IFRS)
    assert any(rule.code == "GAAP-COMP-001" for rule in gaap_rules)
    assert any(rule.code == "IFRS-DOC-001" for rule in ifrs_rules)


def test_engine_execution_returns_structured_summary_for_gaap():
    result = AccountingRulesEngine().evaluate(
        record=_base_record(),
        standard=AccountingStandard.GAAP,
        context={"period_start": "2026-03-01", "period_end": "2026-03-31"},
    )
    payload = result.to_dict()
    assert payload["standard"] == "GAAP"
    assert payload["summary"]["total_rules"] >= 8
    assert "results" in payload


def test_gaap_comp_001_insufficient_data_when_core_fields_missing():
    payload = AccountingRulesEngine().evaluate(
        record=_base_record(account=None, reference=None),
        standard=AccountingStandard.GAAP,
        context={},
    ).to_dict()
    target = next(row for row in payload["results"] if row["rule_code"] == "GAAP-COMP-001")
    assert target["status"] == "insufficient_data"


def test_gaap_cut_001_fails_when_outside_period():
    payload = AccountingRulesEngine().evaluate(
        record=_base_record(date="2026-04-03"),
        standard=AccountingStandard.GAAP,
        context={"period_start": "2026-03-01", "period_end": "2026-03-31"},
    ).to_dict()
    target = next(row for row in payload["results"] if row["rule_code"] == "GAAP-CUT-001")
    assert target["status"] == "failed"


def test_ifrs_doc_001_fails_when_material_without_support():
    payload = AccountingRulesEngine().evaluate(
        record=_base_record(amount=20000, supporting_document=False, reference=None),
        standard=AccountingStandard.IFRS,
        context={},
    ).to_dict()
    target = next(row for row in payload["results"] if row["rule_code"] == "IFRS-DOC-001")
    assert target["status"] in {"failed", "insufficient_data"}


def test_ifrs_cls_001_warns_on_account_mismatch():
    payload = AccountingRulesEngine().evaluate(
        record=_base_record(expected_account_code="7000", account="4001"),
        standard=AccountingStandard.IFRS,
        context={},
    ).to_dict()
    target = next(row for row in payload["results"] if row["rule_code"] == "IFRS-CLS-001")
    assert target["status"] == "warning"


def test_scoring_aggregation_counts_statuses_and_score():
    payload = AccountingRulesEngine().evaluate(
        record=_base_record(expected_account_code="7000", account="4001", supporting_document=False),
        standard=AccountingStandard.IFRS,
        context={},
    ).to_dict()
    summary = payload["summary"]
    assert summary["total_rules"] >= 9
    assert 0 <= summary["compliance_score"] <= 100
    assert summary["failed"] + summary["warning"] + summary["passed"] + summary["not_applicable"] + summary["insufficient_data"] == summary["total_rules"]
