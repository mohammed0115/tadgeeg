"""
Phase-4 list/detail views — tenant-isolation + smoke render coverage.

For every one of the 10 new typed-document pages we verify:
  - GET /documents/<type>/         → 200, lists ONLY caller-org rows
  - GET /documents/<type>/<pk>/    → 200 for owner, 404 for cross-org access
  - Localised header strings render in EN and AR
"""
from __future__ import annotations

from datetime import date

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from apps.documents.models import Document
from apps.documents.typed_models_v2 import (
    SalesOrder, Quotation, ProformaInvoice, ReceiptVoucher, CashVoucher,
    GeneralLedger, Ledger, Contract, SupplierStatement, CustomerStatement,
)


# Each entry: (model, list_url, detail_prefix, en_label, ar_label,
#              minimal_kwargs_for_create)
TYPED_PAGES = [
    (SalesOrder, "/documents/sales-orders/", "/documents/sales-orders/",
     "Sales Orders", "أوامر البيع",
     {"so_number": "ISO-1", "customer_name": "Owner Co"}),
    (Quotation, "/documents/quotations/", "/documents/quotations/",
     "Quotations", "عروض الأسعار",
     {"quotation_number": "ISO-Q1", "party_name": "Owner Co"}),
    (ProformaInvoice, "/documents/proforma-invoices/", "/documents/proforma-invoices/",
     "Proforma Invoices", "الفواتير المبدئية",
     {"proforma_number": "ISO-PF1", "customer_name": "Owner Co"}),
    (ReceiptVoucher, "/documents/receipt-vouchers/", "/documents/receipt-vouchers/",
     "Receipt Vouchers", "سندات القبض",
     {"receipt_number": "ISO-RV1", "payer_name": "Owner Co"}),
    (CashVoucher, "/documents/cash-vouchers/", "/documents/cash-vouchers/",
     "Cash Vouchers", "سندات نقدية",
     {"voucher_number": "ISO-CV1", "counterparty_name": "Owner Co"}),
    (GeneralLedger, "/documents/general-ledgers/", "/documents/general-ledgers/",
     "General Ledgers", "دفاتر الأستاذ العام",
     {"fiscal_year": "2026"}),
    (Ledger, "/documents/ledgers/", "/documents/ledgers/",
     "Ledgers", "دفاتر الأستاذ",
     {"account_number": "1100", "account_name": "Cash"}),
    (Contract, "/documents/contracts/", "/documents/contracts/",
     "Contracts", "العقود",
     {"contract_number": "ISO-CT1", "party_b": "Owner Co"}),
    (SupplierStatement, "/documents/supplier-statements/", "/documents/supplier-statements/",
     "Supplier Statements", "كشوف الموردين",
     {"supplier_name": "Owner Vendor"}),
    (CustomerStatement, "/documents/customer-statements/", "/documents/customer-statements/",
     "Customer Statements", "كشوف العملاء",
     {"customer_name": "Owner Customer"}),
]


def _doc(org, name="x.pdf"):
    return Document.objects.create(
        organization=org, file=SimpleUploadedFile(name, b"pdf"),
        original_filename=name, file_size=10, mime_type="application/pdf",
        document_type=Document.DocumentType.OTHER,
    )


@pytest.fixture
def two_orgs(db, admin_user):
    """Caller-org user + a second org/user created independently."""
    from apps.authentication.models import Organization
    from django.contrib.auth import get_user_model
    User = get_user_model()

    other_org = Organization.objects.create(
        name="Other Co", country=Organization.Country.SAUDI_ARABIA,
        currency=Organization.Currency.SAR, vat_number="300000000000099",
    )
    other_user = User.objects.create_user(
        email="other@test.finai", password="OtherPass123!",
        full_name="Other Admin", organization=other_org, is_staff=True,
    )
    return admin_user, other_user


@pytest.fixture
def web_client():
    return Client()


# ─── Render & isolation per typed page ──────────────────────────────────────

@pytest.mark.django_db
@pytest.mark.parametrize("Model,list_url,detail_prefix,en_label,ar_label,kwargs", TYPED_PAGES)
class TestTypedPageRenderingAndIsolation:
    """Each Phase-4 page renders for the owner and isolates from other orgs."""

    def test_list_renders_with_localised_label(self, two_orgs, web_client,
                                               Model, list_url, detail_prefix,
                                               en_label, ar_label, kwargs):
        owner, _ = two_orgs
        web_client.force_login(owner)

        r_en = web_client.get(list_url, HTTP_ACCEPT_LANGUAGE="en")
        assert r_en.status_code == 200
        assert en_label.encode() in r_en.content

        r_ar = web_client.get(list_url, HTTP_ACCEPT_LANGUAGE="ar")
        assert r_ar.status_code == 200
        assert ar_label.encode() in r_ar.content

    def test_detail_renders_for_owner(self, two_orgs, web_client,
                                      Model, list_url, detail_prefix,
                                      en_label, ar_label, kwargs):
        owner, _ = two_orgs
        obj = Model.objects.create(
            organization=owner.organization, document=_doc(owner.organization),
            uploaded_by=owner, **kwargs,
        )
        web_client.force_login(owner)
        r = web_client.get(f"{detail_prefix}{obj.pk}/")
        assert r.status_code == 200

    def test_detail_404_for_cross_org_user(self, two_orgs, web_client,
                                           Model, list_url, detail_prefix,
                                           en_label, ar_label, kwargs):
        """User in org_b must NOT be able to read org_a's typed-doc detail."""
        owner, other = two_orgs
        obj = Model.objects.create(
            organization=owner.organization, document=_doc(owner.organization),
            uploaded_by=owner, **kwargs,
        )
        web_client.force_login(other)
        r = web_client.get(f"{detail_prefix}{obj.pk}/")
        assert r.status_code == 404, (
            f"{Model.__name__} detail page leaked across orgs: status={r.status_code}"
        )

    def test_list_only_shows_owner_rows(self, two_orgs, web_client,
                                        Model, list_url, detail_prefix,
                                        en_label, ar_label, kwargs):
        """Other-org rows must not appear in caller-org's list."""
        owner, other = two_orgs
        # Owner row
        owner_obj = Model.objects.create(
            organization=owner.organization, document=_doc(owner.organization),
            uploaded_by=owner, **kwargs,
        )
        # Other-org row, same identifying fields
        other_kwargs = {**kwargs}
        if "so_number" in other_kwargs:
            other_kwargs["so_number"] = "OTHER-" + other_kwargs["so_number"]
        other_obj = Model.objects.create(
            organization=other.organization, document=_doc(other.organization),
            uploaded_by=other, **other_kwargs,
        )

        web_client.force_login(owner)
        r = web_client.get(list_url)
        assert r.status_code == 200

        # The OTHER row's pk must not appear in the owner's list page
        body = r.content.decode("utf-8", "replace")
        assert str(other_obj.pk) not in body, (
            f"{Model.__name__} list leaked other-org row {other_obj.pk}"
        )
        # The owner's own row should appear
        assert str(owner_obj.pk) in body, (
            f"{Model.__name__} list missing owner row {owner_obj.pk}"
        )


# ─── Anonymous access should be rejected for these pages ────────────────────

@pytest.mark.django_db
@pytest.mark.parametrize("list_url", [t[1] for t in TYPED_PAGES])
def test_unauthenticated_redirects_to_login(web_client, list_url):
    r = web_client.get(list_url)
    # Either redirect to login (302) or forbidden (403); never 200 with data.
    assert r.status_code in (302, 401, 403), (
        f"{list_url} returned {r.status_code} for anonymous user"
    )
