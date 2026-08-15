"""Request-level regression guards for FI-01 upload duplication.

These tests deliberately use the public auditor upload endpoint, the real router,
and real organization/billing fixtures. They do not mock the upload pipeline.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.invoices.models import Invoice


pytestmark = pytest.mark.django_db(transaction=True)


def _invoice_file(invoice_number: str) -> SimpleUploadedFile:
    payload = {
        "invoice_number": invoice_number,
        "vendor_name": "FI-01 Request Guard Supplier",
        "invoice_date": "2026-08-15",
        "subtotal": 1000.0,
        "vat_amount": 150.0,
        "total_amount": 1150.0,
        "currency": "SAR",
    }
    return SimpleUploadedFile(
        f"{invoice_number}.json",
        json.dumps(payload).encode("utf-8"),
        content_type="application/json",
    )


def _upload_once(client, invoice_number: str):
    return client.post(
        reverse("auditor:upload"),
        {
            "file": _invoice_file(invoice_number),
            "selected_doc_type": "invoice",
            "doc_language": "auto",
        },
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )


def _org_invoices(organization, invoice_number: str):
    return Invoice.objects.filter(
        organization=organization,
        invoice_number=invoice_number,
    ).order_by("created_at", "id")


def test_one_upload_creates_one_invoice(
    web_client, organization, auditor_user, active_subscription,
):
    """One official upload request must persist exactly one invoice."""
    web_client.force_login(auditor_user)
    invoice_number = f"FI01-ONE-{uuid4().hex[:12]}"

    response = _upload_once(web_client, invoice_number)

    assert response.status_code in (301, 302)
    invoices = _org_invoices(organization, invoice_number)
    assert invoices.count() == 1
    assert invoices.get().is_duplicate is False


def test_the_same_file_twice_is_flagged_not_silently_stored(
    web_client, organization, auditor_user, active_subscription,
):
    """Two intentional requests preserve the duplicate signal instead of hiding it."""
    web_client.force_login(auditor_user)
    invoice_number = f"FI01-DUP-{uuid4().hex[:12]}"

    first = _upload_once(web_client, invoice_number)
    second = _upload_once(web_client, invoice_number)

    assert first.status_code in (301, 302)
    assert second.status_code in (301, 302)
    invoices = list(_org_invoices(organization, invoice_number))
    assert len(invoices) == 2
    assert any(invoice.is_duplicate for invoice in invoices)


def test_this_guard_can_fail(
    web_client, organization, auditor_user, active_subscription,
):
    """A deliberately repeated official request makes the one-upload contract fail."""
    web_client.force_login(auditor_user)
    invoice_number = f"FI01-CAN-FAIL-{uuid4().hex[:12]}"

    _upload_once(web_client, invoice_number)
    _upload_once(web_client, invoice_number)

    invoices = _org_invoices(organization, invoice_number)
    with pytest.raises(AssertionError):
        assert invoices.count() == 1
    assert invoices.count() == 2
    assert any(invoice.is_duplicate for invoice in invoices)


def test_upload_templates_defer_to_the_single_base_alpine_runtime():
    """Both upload pages must use the Alpine runtime supplied by dashboard_base."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    dashboard_base = (root / "templates/layouts/dashboard_base.html").read_text(
        encoding="utf-8"
    )
    invoice_upload = (root / "templates/invoices/upload.html").read_text(
        encoding="utf-8"
    )
    document_upload = (root / "templates/documents/upload.html").read_text(
        encoding="utf-8"
    )

    assert dashboard_base.count("vendor/alpine.min.js") == 1
    assert "vendor/alpine.min.js" not in invoice_upload
    assert "vendor/alpine.min.js" not in document_upload
    assert "Alpine is loaded exactly once here." in dashboard_base
