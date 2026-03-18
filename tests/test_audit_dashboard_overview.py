import pytest

from apps.invoices.models import InvoiceValidationResult


@pytest.mark.django_db
def test_dashboard_overview_returns_rule_group_metrics(authenticated_client, invoice):
    InvoiceValidationResult.objects.create(
        invoice=invoice,
        rules_passed=2,
        rules_failed=1,
        validation_score=66.7,
        failed_rule_codes=["INV-002"],
        validation_details={
            "INV-001": {"passed": True, "message": "ok"},
            "INV-002": {"passed": False, "message": "missing date"},
            "VAT-001": {"passed": True, "message": "ok"},
        },
    )

    response = authenticated_client.get("/audit/dashboard/overview/")

    assert response.status_code == 200
    payload = response.json()
    inv_group = next(group for group in payload["rule_groups"] if group["code"] == "INV")
    vat_group = next(group for group in payload["rule_groups"] if group["code"] == "VAT")

    assert inv_group["total"] == 2
    assert inv_group["passed"] == 1
    assert inv_group["failed"] == 1
    assert inv_group["pct"] == 50.0
    assert vat_group["total"] == 1
    assert vat_group["passed"] == 1
    assert vat_group["pct"] == 100.0


@pytest.mark.django_db
def test_dashboard_data_endpoints_support_session_auth(web_client, auditor_user, invoice):
    web_client.force_login(auditor_user)

    overview = web_client.get("/api/v1/audit/dashboard/overview/")
    invoice_list = web_client.get("/api/v1/invoices/?status=pending")
    spend_report = web_client.get("/api/v1/invoices/reports/spend/")

    assert overview.status_code == 200
    assert invoice_list.status_code == 200
    assert spend_report.status_code == 200
