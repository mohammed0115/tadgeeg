import pytest

from apps.authentication.models import Organization, User
from apps.invoices.models import VendorProfile


@pytest.mark.django_db
def test_vendor_report_exposes_intelligence_metrics(authenticated_client, organization):
    VendorProfile.objects.create(
        organization=organization,
        vendor_name="Alpha Supplies",
        vendor_vat_number="300111111111111",
        risk_score=82.5,
        risk_tier=VendorProfile.RiskTier.HIGH,
        invoice_count=12,
        compliance_issue_count=4,
        transaction_frequency_30d=6.0,
        tags=["watchlist", "duplicate_pattern"],
    )
    VendorProfile.objects.create(
        organization=organization,
        vendor_name="Safe Vendor",
        risk_score=12.0,
        risk_tier=VendorProfile.RiskTier.LOW,
        invoice_count=3,
        compliance_issue_count=0,
        transaction_frequency_30d=1.0,
    )

    response = authenticated_client.get("/api/v1/invoices/reports/vendors/?risk_tier=high")

    assert response.status_code == 200
    payload = response.json()
    assert payload["report_type"] == "vendor_risk_report"
    assert payload["summary"]["high_risk_vendors"] >= 1
    assert payload["vendors"][0]["risk_score"] >= 80
    assert "transaction_frequency_30d" in payload["vendors"][0]
    assert "compliance_issue_count" in payload["vendors"][0]


@pytest.mark.django_db
def test_vendor_detail_endpoint_respects_tenant_isolation(authenticated_client, organization):
    own_vendor = VendorProfile.objects.create(
        organization=organization,
        vendor_name="Tenant Vendor",
        risk_score=75.0,
        risk_tier=VendorProfile.RiskTier.HIGH,
        transaction_history={"recent_documents": [{"document_number": "INV-1"}]},
        compliance_history={"total_issues": 2},
    )

    other_org = Organization.objects.create(name="Other Tenant")
    other_vendor = VendorProfile.objects.create(
        organization=other_org,
        vendor_name="Other Vendor",
        risk_score=91.0,
        risk_tier=VendorProfile.RiskTier.BLOCKED,
    )

    ok_response = authenticated_client.get(f"/api/v1/invoices/vendors/{own_vendor.id}/")
    denied_response = authenticated_client.get(f"/api/v1/invoices/vendors/{other_vendor.id}/")

    assert ok_response.status_code == 200
    assert ok_response.json()["vendor_name"] == "Tenant Vendor"
    assert denied_response.status_code == 404


@pytest.mark.django_db
def test_vendor_dashboard_page_renders_new_intelligence_columns(web_client, auditor_user, organization):
    VendorProfile.objects.create(
        organization=organization,
        vendor_name="Dashboard Vendor",
        risk_score=66.0,
        risk_tier=VendorProfile.RiskTier.MEDIUM,
        compliance_issue_count=3,
        transaction_frequency_30d=4.0,
    )

    web_client.force_login(auditor_user)
    response = web_client.get("/vendors/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "Risk Score" in content or "درجة المخاطر" in content
    assert "Frequency" in content or "التكرار" in content
    assert "Compliance" in content or "الامتثال" in content
