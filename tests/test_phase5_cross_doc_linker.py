"""
Phase-5 cross-document linker tests.

Covers:
  - Match strategies in priority order (id-link > number > vendor+amount > vendor+date)
  - 3-way match (Invoice ↔ PO ↔ GRN) clean and broken cases
  - Each Phase-2 doc-type linker (Contract → invoices, Statement → invoices, …)
  - Tenant isolation (linker never returns docs from another org)
  - Empty / missing fields don't crash
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.documents.models import Document
from apps.documents.typed_models import (
    PurchaseOrder, GoodsReceiptNote, PaymentVoucher,
)
from apps.documents.typed_models_v2 import (
    SalesOrder, Quotation, Contract, ReceiptVoucher,
    SupplierStatement, CustomerStatement,
)
from apps.invoices.models import Invoice
from core.services.cross_doc_linker import (
    find_links, link_summary_counts, AMOUNT_TOLERANCE, DATE_PROXIMITY_DAYS,
)


# ─── Helpers ────────────────────────────────────────────────────────────────

def _doc(org, name="x.pdf"):
    return Document.objects.create(
        organization=org, file=SimpleUploadedFile(name, b"pdf"),
        original_filename=name, file_size=10, mime_type="application/pdf",
        document_type=Document.DocumentType.OTHER,
    )


@pytest.fixture
def chain(organization, admin_user):
    """Build a clean PO→GRN→Invoice→Payment audit trail (5000 SAR, VendorX)."""
    inv_date = date(2026, 4, 1)
    po = PurchaseOrder.objects.create(
        organization=organization, document=_doc(organization, "po.pdf"),
        uploaded_by=admin_user, po_number="PO-T-1",
        po_date=inv_date - timedelta(days=10),
        vendor_name="VendorX", total_amount=Decimal("5000"),
    )
    grn = GoodsReceiptNote.objects.create(
        organization=organization, document=_doc(organization, "grn.pdf"),
        uploaded_by=admin_user, grn_number="GRN-T-1",
        grn_date=inv_date - timedelta(days=3),
        po_number="PO-T-1", po_id=po.id,
        invoice_number="INV-T-1", vendor_name="VendorX",
        total_amount=Decimal("5000"),
    )
    inv = Invoice.objects.create(
        organization=organization, invoice_number="INV-T-1",
        invoice_date=inv_date, vendor_name="VendorX",
        total_amount=Decimal("5000"), currency="SAR",
    )
    pay = PaymentVoucher.objects.create(
        organization=organization, document=_doc(organization, "pay.pdf"),
        uploaded_by=admin_user, payment_number="PV-T-1",
        payment_date=inv_date + timedelta(days=14),
        payee_name="VendorX", total_amount=Decimal("5000"),
        linked_invoice_id=inv.id, linked_invoice_number="INV-T-1",
        linked_po_number="PO-T-1",
    )
    return {"po": po, "grn": grn, "inv": inv, "pay": pay}


# ─── Invoice-side links ─────────────────────────────────────────────────────

@pytest.mark.django_db
class TestInvoiceLinks:
    def test_finds_full_chain(self, organization, chain):
        links = find_links("invoice", chain["inv"], organization)
        assert links["purchase_order"]["display_id"] == "PO-T-1"
        assert links["goods_receipt_note"]["display_id"] == "GRN-T-1"
        assert links["payment_voucher"]["display_id"] == "PV-T-1"

    def test_three_way_match_clean(self, organization, chain):
        links = find_links("invoice", chain["inv"], organization)
        twm = links["three_way_match"]
        assert twm["applicable"] is True
        assert twm["is_clean"] is True
        assert twm["issues"] == []
        assert twm["invoice_amount"] == twm["po_amount"] == twm["grn_amount"] == 5000.0

    def test_grn_match_via_invoice_number(self, organization, chain):
        link = find_links("invoice", chain["inv"], organization)["goods_receipt_note"]
        assert link["match_type"] == "invoice_number"
        assert link["match_score"] == 1.0

    def test_payment_match_via_id(self, organization, chain):
        link = find_links("invoice", chain["inv"], organization)["payment_voucher"]
        assert link["match_type"] == "linked_invoice_id"
        assert link["amount_diff"] == 0.0


@pytest.mark.django_db
class TestInvoicePoMatchStrategies:
    """Verify the priority order: via_grn > vendor_amount > vendor_date."""

    def test_via_grn(self, organization, chain):
        # GRN exists with po_id pointer → linker prefers via_grn
        link = find_links("invoice", chain["inv"], organization)["purchase_order"]
        assert link["match_type"] == "via_grn"
        assert link["match_score"] == 1.0

    def test_vendor_amount_when_no_grn(self, organization, admin_user):
        po = PurchaseOrder.objects.create(
            organization=organization, document=_doc(organization, "po2.pdf"),
            uploaded_by=admin_user, po_number="PO-VA",
            po_date=date(2026, 3, 1),
            vendor_name="V2", total_amount=Decimal("999"),
        )
        inv = Invoice.objects.create(
            organization=organization, invoice_number="INV-VA",
            invoice_date=date(2026, 3, 15), vendor_name="V2",
            total_amount=Decimal("999"), currency="SAR",
        )
        link = find_links("invoice", inv, organization)["purchase_order"]
        assert link["match_type"] == "vendor_amount"
        assert link["display_id"] == "PO-VA"

    def test_vendor_date_with_amount_mismatch_flag(self, organization, admin_user):
        po = PurchaseOrder.objects.create(
            organization=organization, document=_doc(organization, "po3.pdf"),
            uploaded_by=admin_user, po_number="PO-VD",
            po_date=date(2026, 3, 1),
            vendor_name="V3", total_amount=Decimal("100"),
        )
        inv = Invoice.objects.create(
            organization=organization, invoice_number="INV-VD",
            invoice_date=date(2026, 3, 15), vendor_name="V3",
            total_amount=Decimal("999"), currency="SAR",
        )
        link = find_links("invoice", inv, organization)["purchase_order"]
        assert link["match_type"] == "vendor_date"
        assert "amount_mismatch" in link["issues"]
        # amount_diff = po.total_amount - invoice.total_amount = 100 - 999
        assert link["amount_diff"] == -899.0

    def test_no_po_returns_none(self, organization):
        inv = Invoice.objects.create(
            organization=organization, invoice_number="INV-NONE",
            invoice_date=date(2026, 1, 1), vendor_name="No-Such-Vendor",
            total_amount=Decimal("100"), currency="SAR",
        )
        assert find_links("invoice", inv, organization)["purchase_order"] is None


@pytest.mark.django_db
class TestThreeWayMatch:
    def test_missing_grn_flagged(self, organization, admin_user):
        po = PurchaseOrder.objects.create(
            organization=organization, document=_doc(organization),
            uploaded_by=admin_user, po_number="PO-NOGRN",
            po_date=date(2026, 3, 1),
            vendor_name="V4", total_amount=Decimal("500"),
        )
        inv = Invoice.objects.create(
            organization=organization, invoice_number="INV-NOGRN",
            invoice_date=date(2026, 3, 15), vendor_name="V4",
            total_amount=Decimal("500"), currency="SAR",
        )
        twm = find_links("invoice", inv, organization)["three_way_match"]
        assert twm["applicable"] is True
        assert twm["is_clean"] is False
        assert "missing_grn" in twm["issues"]
        assert twm["po_amount"] == 500.0

    def test_amount_mismatch_invoice_vs_po_flagged(self, organization, admin_user):
        po = PurchaseOrder.objects.create(
            organization=organization, document=_doc(organization),
            uploaded_by=admin_user, po_number="PO-MISMATCH",
            po_date=date(2026, 3, 1),
            vendor_name="V5", total_amount=Decimal("100"),
        )
        inv = Invoice.objects.create(
            organization=organization, invoice_number="INV-MISMATCH",
            invoice_date=date(2026, 3, 15), vendor_name="V5",
            total_amount=Decimal("999"), currency="SAR",
        )
        twm = find_links("invoice", inv, organization)["three_way_match"]
        assert "amount_mismatch_invoice_vs_po" in twm["issues"]

    def test_no_po_no_grn_not_applicable(self, organization):
        inv = Invoice.objects.create(
            organization=organization, invoice_number="INV-FREE",
            invoice_date=date(2026, 3, 15), vendor_name="Standalone",
            total_amount=Decimal("100"), currency="SAR",
        )
        twm = find_links("invoice", inv, organization)["three_way_match"]
        assert twm["applicable"] is False

    def test_amount_within_tolerance(self, organization, admin_user):
        """Sub-tolerance differences must not raise issues."""
        po = PurchaseOrder.objects.create(
            organization=organization, document=_doc(organization),
            uploaded_by=admin_user, po_number="PO-TOL",
            po_date=date(2026, 3, 1),
            vendor_name="V6",
            total_amount=Decimal("100.50"),
        )
        inv = Invoice.objects.create(
            organization=organization, invoice_number="INV-TOL",
            invoice_date=date(2026, 3, 15), vendor_name="V6",
            total_amount=Decimal("100.50") + AMOUNT_TOLERANCE / 2,
            currency="SAR",
        )
        twm = find_links("invoice", inv, organization)["three_way_match"]
        # Within tolerance — no amount_mismatch issue (missing_grn still expected)
        assert "amount_mismatch_invoice_vs_po" not in twm["issues"]


# ─── Phase-2 doc-type linkers ───────────────────────────────────────────────

@pytest.mark.django_db
class TestPhase2Linkers:
    def test_contract_to_invoices_within_period(self, organization, admin_user):
        ct = Contract.objects.create(
            organization=organization, document=_doc(organization),
            uploaded_by=admin_user, contract_number="CT-1",
            party_b="VendorY",
            start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
            contract_value=Decimal("100000"),
        )
        # Two invoices in-period, one outside
        Invoice.objects.create(
            organization=organization, invoice_number="IN-IN-1",
            invoice_date=date(2026, 6, 1), vendor_name="VendorY",
            total_amount=Decimal("1000"), currency="SAR",
        )
        Invoice.objects.create(
            organization=organization, invoice_number="IN-IN-2",
            invoice_date=date(2026, 9, 1), vendor_name="VendorY",
            total_amount=Decimal("1500"), currency="SAR",
        )
        Invoice.objects.create(
            organization=organization, invoice_number="IN-OUT",
            invoice_date=date(2025, 6, 1), vendor_name="VendorY",
            total_amount=Decimal("9999"), currency="SAR",
        )
        links = find_links("contract", ct, organization)
        assert len(links["invoices"]) == 2
        nums = {i["display_id"] for i in links["invoices"]}
        assert nums == {"IN-IN-1", "IN-IN-2"}

    def test_supplier_statement_to_invoices_and_payments(self, organization, admin_user):
        stmt = SupplierStatement.objects.create(
            organization=organization, document=_doc(organization),
            uploaded_by=admin_user, supplier_name="VendorZ",
            period_from=date(2026, 1, 1), period_to=date(2026, 3, 31),
        )
        Invoice.objects.create(
            organization=organization, invoice_number="SS-INV-1",
            invoice_date=date(2026, 2, 15), vendor_name="VendorZ",
            total_amount=Decimal("100"), currency="SAR",
        )
        PaymentVoucher.objects.create(
            organization=organization, document=_doc(organization),
            uploaded_by=admin_user, payment_number="SS-PAY-1",
            payment_date=date(2026, 3, 1), payee_name="VendorZ",
            total_amount=Decimal("100"),
        )
        links = find_links("supplier_statement", stmt, organization)
        assert len(links["invoices"]) == 1
        assert len(links["payments"]) == 1

    def test_customer_statement_to_invoices_and_receipts(self, organization, admin_user):
        stmt = CustomerStatement.objects.create(
            organization=organization, document=_doc(organization),
            uploaded_by=admin_user, customer_name="CustA",
            period_from=date(2026, 1, 1), period_to=date(2026, 3, 31),
        )
        Invoice.objects.create(
            organization=organization, invoice_number="CS-INV-1",
            invoice_date=date(2026, 2, 15), customer_name="CustA",
            total_amount=Decimal("200"), currency="SAR",
        )
        ReceiptVoucher.objects.create(
            organization=organization, document=_doc(organization),
            uploaded_by=admin_user, receipt_number="CS-REC-1",
            receipt_date=date(2026, 3, 10), payer_name="CustA",
            amount=Decimal("200"),
        )
        links = find_links("customer_statement", stmt, organization)
        assert len(links["invoices"]) == 1
        assert len(links["receipts"]) == 1


@pytest.mark.django_db
class TestUnknownDocType:
    def test_returns_empty(self, organization):
        assert find_links("totally_unknown", object(), organization) == {}

    def test_none_doc_returns_empty(self, organization):
        assert find_links("invoice", None, organization) == {}

    def test_none_org_returns_empty(self):
        assert find_links("invoice", object(), None) == {}


# ─── Tenant isolation ───────────────────────────────────────────────────────

@pytest.mark.django_db
class TestLinkerTenantIsolation:
    """Linker must never reach across organisations even when names match exactly."""

    def test_other_orgs_po_not_linked(self, organization, admin_user):
        from apps.authentication.models import Organization
        other = Organization.objects.create(
            name="Other Co", country=Organization.Country.SAUDI_ARABIA,
            currency=Organization.Currency.SAR, vat_number="300000000000005",
        )
        # Create a PO under the OTHER org with same vendor + amount.
        PurchaseOrder.objects.create(
            organization=other, document=_doc(other),
            uploaded_by=admin_user, po_number="PO-OTHER",
            po_date=date(2026, 3, 1), vendor_name="ShinyVendor",
            total_amount=Decimal("100"),
        )
        # Invoice belongs to the original org.
        inv = Invoice.objects.create(
            organization=organization, invoice_number="INV-OTHER",
            invoice_date=date(2026, 3, 15), vendor_name="ShinyVendor",
            total_amount=Decimal("100"), currency="SAR",
        )
        links = find_links("invoice", inv, organization)
        assert links["purchase_order"] is None, "Linker leaked across orgs"

    def test_link_summary_counts_clean_org(self, organization, chain):
        counts = link_summary_counts("invoice", chain["inv"], organization)
        assert counts == {
            "purchase_order": 1, "goods_receipt_note": 1,
            "payment_voucher": 1, "contract": 0,  # no contract for VendorX in this fixture
        }


# ─── Robustness: missing fields / partial data ──────────────────────────────

@pytest.mark.django_db
class TestRobustness:
    def test_invoice_with_no_vendor_no_number(self, organization):
        """Invoice with no vendor_name and no invoice_number should not crash."""
        inv = Invoice.objects.create(
            organization=organization, invoice_number="",
            vendor_name="", total_amount=Decimal("0"), currency="SAR",
        )
        links = find_links("invoice", inv, organization)
        # All slots are None/missing — nothing crashes
        assert links["purchase_order"] is None
        assert links["goods_receipt_note"] is None
        assert links["payment_voucher"] is None

    def test_link_summary_counts_handles_unknown_type(self, organization):
        assert link_summary_counts("not_real", object(), organization) == {}
