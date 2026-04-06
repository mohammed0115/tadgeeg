from datetime import date
from types import SimpleNamespace

import pytest

from apps.authentication.models import Organization
from apps.invoices.models import VendorProfile
from apps.invoices.services.vendor_intelligence import VendorIntelligenceService
from apps.rule_engine.pipeline.stages.context_builder import VendorContextLoader
from apps.rule_engine.risk.risk_engine import RiskEngine
from apps.rule_engine.rules.base import NormalizedDocument


@pytest.mark.django_db
def test_vendor_intelligence_service_updates_profile_and_preserves_tenant_isolation():
    org_primary = Organization.objects.create(name="Primary Org")
    org_other = Organization.objects.create(name="Other Org")

    VendorProfile.objects.create(
        organization=org_other,
        vendor_name="ACME Supplies",
        risk_score=12.5,
        risk_tier=VendorProfile.RiskTier.LOW,
    )

    doc = NormalizedDocument(
        document_id="audit-doc-1",
        document_type="sales_invoice",
        organization_id=str(org_primary.id),
        document_number="INV-2026-001",
        document_date=date(2026, 4, 3),
        total_amount=50000,
        counterparty_name="ACME Supplies",
        tax_id="300123456789012",
        typed_data={"is_duplicate": True, "duplicate_of_id": "INV-OLD-9"},
        org_context={"blocked_vendor_ids": ["ACME Supplies"]},
    )
    risk_data = {
        "risk_score": 82.0,
        "risk_level": "high",
        "anomaly_score": 65.0,
        "anomaly_findings": [{"code": "duplicate_pattern"}],
        "top_failed_rules": [
            {"rule_code": "VAT-01"},
            {"rule_code": "SEC-M01"},
        ],
    }

    profile = VendorIntelligenceService().update_after_audit(doc, risk_data)

    assert profile is not None
    assert profile.organization_id == org_primary.id
    assert profile.vendor_name == "ACME Supplies"
    assert profile.risk_score >= 40.0
    assert profile.transaction_frequency_30d >= 1.0
    assert profile.compliance_issue_count >= 2
    assert profile.transaction_history["document_counts"]["sales_invoice"] >= 1

    other = VendorProfile.objects.get(organization=org_other, vendor_name="ACME Supplies")
    assert other.risk_score == 12.5
    assert other.compliance_issue_count == 0


@pytest.mark.django_db
def test_vendor_context_loader_returns_vendor_risk_score_from_profile():
    org = Organization.objects.create(name="Vendor Org")
    VendorProfile.objects.create(
        organization=org,
        vendor_name="Risky Vendor",
        vendor_vat_number="300999999999999",
        risk_score=88.0,
        risk_tier=VendorProfile.RiskTier.HIGH,
        is_approved=False,
        tags=["watchlist"],
        transaction_frequency_30d=7.0,
        compliance_issue_count=4,
        high_risk_audit_count=3,
    )

    doc = NormalizedDocument(
        document_id="po-1",
        document_type="purchase_order",
        organization_id=str(org.id),
        counterparty_name="Risky Vendor",
        tax_id="300999999999999",
    )
    context = SimpleNamespace(normalized_doc=doc)

    vendor_context = VendorContextLoader.load(context)

    assert vendor_context["risk_score"] == 88.0
    assert vendor_context["vendor_risk_score"] == 88.0
    assert vendor_context["is_approved"] is False
    assert "watchlist" in vendor_context["flags"]
    assert vendor_context["frequency_30d"] == 7.0


def test_risk_engine_uses_vendor_risk_score_in_vendor_component():
    doc = NormalizedDocument(
        document_id="doc-vendor-risk",
        document_type="sales_invoice",
        organization_id="org-1",
        total_amount=5000,
        approved_by_id="approver-1",
        counterparty_name="Risky Vendor",
        document_date=date(2026, 4, 3),
    )
    context = SimpleNamespace(
        normalized_doc=doc,
        rule_results=[],
        rule_assignments=[],
        vendor_context={
            "counterparty_name": "Risky Vendor",
            "risk_score": 90.0,
            "vendor_risk_score": 90.0,
            "is_approved": True,
            "flags": [],
        },
        history_context={},
        erp_context={},
    )

    result = RiskEngine().compute(context)

    assert result.components["vendor"].raw_score >= 0.9
    assert result.score_breakdown["vendor"] > 0
