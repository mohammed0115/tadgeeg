from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.invoices.models import InvoiceAuditEvent


@pytest.mark.django_db
def test_invoice_detail_includes_review_payload(authenticated_client, invoice):
    invoice.raw_text = "Vendor Tadgeeg\nInvoice INV-001\nTotal 1150"
    invoice.extracted_data = {
        "vendor_name": "AI Vendor",
        "invoice_number": "AI-001",
        "normalized": {
            "vendor_name": "Normalized Vendor",
            "invoice_number": "INV-001",
            "total_amount": "1150.00",
        },
    }
    invoice.save(update_fields=["raw_text", "extracted_data", "updated_at"])

    response = authenticated_client.get(f"/invoices/{invoice.id}/")

    assert response.status_code == 200
    payload = response.json()
    assert "review" in payload
    assert payload["review"]["raw_text"].startswith("Vendor Tadgeeg")
    assert any(field["field"] == "vendor_name" for field in payload["review"]["fields"])


@pytest.mark.django_db
def test_manual_review_saves_corrections_and_audit_event(authenticated_client, invoice):
    invoice.extracted_data = {
        "normalized": {"vendor_name": "Old Vendor", "total_amount": "1150.00"},
    }
    invoice.save(update_fields=["extracted_data", "updated_at"])

    response = authenticated_client.post(
        f"/invoices/{invoice.id}/review/",
        {
            "corrections": {
                "vendor_name": "Reviewed Vendor",
                "total_amount": "1200.00",
                "invoice_date": "2026-03-16",
            },
            "note": "Adjusted values after reviewer check",
            "revalidate": False,
        },
        format="json",
    )

    assert response.status_code == 200
    invoice.refresh_from_db()
    assert invoice.vendor_name == "Reviewed Vendor"
    assert invoice.total_amount == Decimal("1200.00")
    assert invoice.extracted_data["review"]["corrections"]["vendor_name"] == "Reviewed Vendor"
    assert InvoiceAuditEvent.objects.filter(
        invoice=invoice,
        event_type=InvoiceAuditEvent.EventType.EDITED,
        description="Manual review corrections applied",
    ).exists()


@pytest.mark.django_db
def test_manual_review_can_trigger_revalidation(authenticated_client, invoice):
    with patch("apps.invoices.views._run_invoice_revalidation", return_value={"validation_score": 90.0}) as mocked:
        response = authenticated_client.post(
            f"/invoices/{invoice.id}/review/",
            {
                "corrections": {"vendor_name": "Reviewed Vendor"},
                "note": "Revalidate after manual review",
                "revalidate": True,
            },
            format="json",
        )

    assert response.status_code == 200
    assert response.json()["validation"]["validation_score"] == 90.0
    mocked.assert_called_once()


@pytest.mark.django_db
def test_invoice_detail_page_renders_manual_review_panel(web_client, auditor_user, invoice):
    web_client.force_login(auditor_user)
    response = web_client.get(f"/invoices/{invoice.id}/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "مقارنة المصادر وتصحيح الحقول" in content
