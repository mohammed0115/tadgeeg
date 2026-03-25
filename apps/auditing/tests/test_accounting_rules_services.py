from types import SimpleNamespace

from apps.auditing.accounting_rules.enums import AccountingStandard
from apps.auditing.accounting_rules import services


def test_tenant_isolation_in_invoice_service(monkeypatch):
    captured = {}

    def fake_fetch_invoice(invoice_id, organization_id):
        captured["invoice_id"] = invoice_id
        captured["organization_id"] = organization_id
        return None

    monkeypatch.setattr(services, "_fetch_invoice", fake_fetch_invoice)

    payload = services.evaluate_gaap_rules_for_invoice("inv-1", "org-123")
    assert captured["organization_id"] == "org-123"
    assert payload["summary"]["total_rules"] == 0


def test_evaluate_rules_for_report_is_tenant_scoped(monkeypatch):
    captured = {}

    def fake_fetch_report(report_id, organization_id):
        captured["report_id"] = report_id
        captured["organization_id"] = organization_id
        return None

    monkeypatch.setattr(services, "_fetch_report", fake_fetch_report)

    payload = services.evaluate_rules_for_report("rep-1", AccountingStandard.GAAP, "org-xyz")
    assert captured["organization_id"] == "org-xyz"
    assert payload["summary"]["total_rules"] == 0
