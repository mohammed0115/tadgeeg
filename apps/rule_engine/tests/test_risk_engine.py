from datetime import date
from types import SimpleNamespace

from apps.rule_engine.risk.anomaly_engine import DocumentAnomalyDetector
from apps.rule_engine.risk.risk_aggregator import RiskAggregator
from apps.rule_engine.risk.risk_engine import RiskEngine
from apps.rule_engine.rules.base import NormalizedDocument


def make_result(
    rule_code,
    status="pass",
    applied_severity="medium",
    blocks_approval=False,
    explanation="",
    explanation_ar="",
    risk_contribution=0.0,
):
    return SimpleNamespace(
        rule_code=rule_code,
        status=status,
        applied_severity=applied_severity,
        blocks_approval=blocks_approval,
        explanation=explanation,
        explanation_ar=explanation_ar,
        risk_contribution=risk_contribution,
    )


def make_context(doc, results, vendor=None, history=None):
    return SimpleNamespace(
        normalized_doc=doc,
        rule_results=results,
        rule_assignments=[],
        vendor_context=vendor or {},
        history_context=history or {},
        erp_context={},
    )


def test_tax_failures_force_minimum_high_risk():
    doc = NormalizedDocument(
        document_id="doc-tax-1",
        document_type="sales_invoice",
        organization_id="org-1",
        total_amount=12000,
        approved_by_id="approver-1",
        document_date=date(2026, 4, 1),
    )
    results = [
        make_result(
            "VAT-01",
            status="fail",
            applied_severity="high",
            explanation="VAT rate mismatch",
            explanation_ar="عدم تطابق ضريبة القيمة المضافة",
            risk_contribution=0.8,
        )
    ]

    scored = RiskEngine().compute(make_context(doc, results))

    assert scored.total_score >= 50.0
    assert scored.risk_level in ("high", "critical")
    assert "tax_issue" in scored.overrides_applied


def test_risk_aggregator_uses_document_context_for_missing_approval_high_amount():
    doc = NormalizedDocument(
        document_id="doc-appr-1",
        document_type="sales_invoice",
        organization_id="org-1",
        total_amount=250000,
        approved_by_id=None,
        status="pending",
        document_date=date(2026, 4, 1),
    )

    risk_data = RiskAggregator().compute(
        results=[],
        assignments=[],
        normalized_doc=doc,
        vendor_context={"is_approved": None, "flags": [], "counterparty_name": "Unknown Vendor"},
        history_context={"recent_run_count": 0, "high_risk_count": 0, "lookback_days": 90},
    )

    assert risk_data["risk_level"] == "critical"
    assert risk_data["blocks_approval"] is True
    assert "missing_approval_high_amount" in risk_data.get("overrides_applied", [])


def test_dynamic_breakdown_includes_contextual_components():
    doc = NormalizedDocument(
        document_id="doc-vendor-1",
        document_type="sales_invoice",
        organization_id="org-1",
        total_amount=99000,
        approved_by_id="approver-2",
        document_date=date(2026, 4, 1),
    )
    results = [
        make_result("GEN-H01", status="warning", applied_severity="medium", risk_contribution=0.3),
    ]

    risk_data = RiskAggregator().compute(
        results=results,
        assignments=[],
        normalized_doc=doc,
        vendor_context={"is_approved": False, "flags": ["dispute"], "counterparty_name": "Flagged Vendor"},
        history_context={
            "recent_run_count": 80,
            "high_risk_count": 25,
            "lookback_days": 90,
            "peer_amounts": [950, 1050, 1100, 980, 1025, 990, 1010],
        },
    )

    assert set(risk_data["score_breakdown"].keys()) >= {"violation", "amount", "approval", "vendor", "behavioral"}
    assert risk_data["risk_score"] > 0
    assert risk_data["explanations"]
    assert "anomaly_score" in risk_data
    assert "anomaly_explanation" in risk_data


def test_anomaly_detector_flags_price_duplicate_frequency_and_vendor_risk():
    doc = NormalizedDocument(
        document_id="doc-anom-1",
        document_type="sales_invoice",
        organization_id="org-1",
        document_number="INV-2026-999",
        total_amount=100000,
        approved_by_id="approver-9",
        counterparty_name="Risky Vendor",
        document_date=date(2026, 4, 1),
        typed_data={"is_duplicate": True, "duplicate_of_id": "INV-2025-888"},
    )

    analysis = DocumentAnomalyDetector().analyze(
        doc,
        vendor_context={"is_approved": False, "flags": ["watchlist", "dispute"], "counterparty_name": "Risky Vendor"},
        history_context={
            "recent_run_count": 120,
            "high_risk_count": 45,
            "lookback_days": 90,
            "peer_amounts": [900, 1100, 1000, 950, 1030, 1080, 970, 1020],
            "duplicate_documents": 2,
        },
    )

    assert analysis.anomaly_score >= 70
    assert analysis.findings
    assert "duplicate" in analysis.explanation.lower() or "frequency" in analysis.explanation.lower()
