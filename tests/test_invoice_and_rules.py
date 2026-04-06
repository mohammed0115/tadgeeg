"""
Invoice Model, Generic Rules & Audit Pipeline Tests
Uses real NormalizedDocument and correct field names.
"""
import pytest
from decimal import Decimal
from datetime import date, timedelta
from rest_framework import status
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model

User = get_user_model()


def make_doc(typed_data=None, org_context=None, **kwargs):
    from apps.rule_engine.rules.base import NormalizedDocument
    return NormalizedDocument(
        document_id="doc-1",
        document_type=kwargs.pop("document_type", "invoice"),
        organization_id="org-1",
        typed_data=typed_data or {},
        org_context=org_context or {"country": "SA"},
        **kwargs,
    )


# ─── Invoice model ────────────────────────────────────────────────────────────

@pytest.fixture
def org(db):
    from apps.authentication.models import Organization
    return Organization.objects.create(
        name="Inv Test Org", name_ar="منظمة", country="SA",
        currency="SAR", vat_number="300000000000006",
    )

@pytest.fixture
def uploader(db, org):
    return User.objects.create_user(
        email="inv_uploader@test.finai", password="InvPass1!",
        full_name="Uploader", role=User.Role.SENIOR_AUDITOR, organization=org,
    )

@pytest.fixture
def invoice(db, org, uploader):
    from apps.invoices.models import Invoice
    return Invoice.objects.create(
        organization=org, uploaded_by=uploader,
        original_filename="test.pdf", invoice_number="INV-2026-001",
        invoice_date=date(2026, 1, 15), vendor_name="Test Vendor LLC",
        vendor_vat_number="300000000000010", currency="SAR",
        subtotal=Decimal("1000.00"), vat_amount=Decimal("150.00"),
        total_amount=Decimal("1150.00"), status="pending",
    )


@pytest.mark.django_db
class TestInvoiceModel:
    def test_invoice_has_uuid_pk(self, invoice):
        import uuid
        assert isinstance(invoice.id, uuid.UUID)

    def test_invoice_defaults(self, invoice):
        assert invoice.status == "pending"
        assert invoice.discount == Decimal("0.00")
        assert invoice.line_items == []

    def test_invoice_default_vat_rate_15(self, org, uploader):
        from apps.invoices.models import Invoice
        inv = Invoice.objects.create(
            organization=org, uploaded_by=uploader,
            original_filename="v.pdf", currency="SAR",
            total_amount=Decimal("1000"), status="pending",
        )
        assert inv.vat_rate == Decimal("15")

    def test_invoice_requires_organization(self, db, uploader):
        from apps.invoices.models import Invoice
        with pytest.raises(Exception):
            Invoice.objects.create(
                organization=None, uploaded_by=uploader,
                original_filename="no_org.pdf", total_amount=Decimal("100"),
            )

    def test_invoice_arabic_vendor_name(self, org, uploader):
        from apps.invoices.models import Invoice
        inv = Invoice.objects.create(
            organization=org, uploaded_by=uploader,
            original_filename="ar.pdf", vendor_name="شركة الاختبار",
            currency="SAR", total_amount=Decimal("500"), status="pending",
        )
        assert inv.vendor_name == "شركة الاختبار"

    def test_invoice_with_line_items(self, org, uploader):
        from apps.invoices.models import Invoice
        items = [{"description": "Service A", "quantity": 2, "unit_price": 500, "total": 1000}]
        inv = Invoice.objects.create(
            organization=org, uploaded_by=uploader,
            original_filename="li.pdf", currency="SAR",
            total_amount=Decimal("1150"), subtotal=Decimal("1000"),
            vat_amount=Decimal("150"), line_items=items, status="pending",
        )
        assert len(inv.line_items) == 1

    def test_multiple_currencies(self, org, uploader):
        from apps.invoices.models import Invoice
        for i, currency in enumerate(["SAR", "AED", "USD", "EUR", "KWD"]):
            inv = Invoice.objects.create(
                organization=org, uploaded_by=uploader,
                original_filename=f"{currency}_{i}.pdf", currency=currency,
                total_amount=Decimal("100"), status="pending",
            )
            assert inv.currency == currency


# ─── GEN-H01: Document number ─────────────────────────────────────────────────

@pytest.mark.unit
class TestDocumentNumberRule:
    def _rule(self):
        from apps.rule_engine.rules.generic.document_number_rule import DocumentNumberRule
        return DocumentNumberRule()

    def test_present_passes(self):
        assert self._rule().execute(make_doc(document_number="INV-001")).passed

    def test_none_fails(self):
        assert not self._rule().execute(make_doc(document_number=None)).passed

    def test_empty_fails(self):
        assert not self._rule().execute(make_doc(document_number="")).passed

    def test_whitespace_fails(self):
        assert not self._rule().execute(make_doc(document_number="   ")).passed

    def test_arabic_number_passes(self):
        assert self._rule().execute(make_doc(document_number="فاتورة-٠٠١")).passed


# ─── GEN-H02: Document date ───────────────────────────────────────────────────

@pytest.mark.unit
class TestDocumentDateRule:
    def _rule(self):
        from apps.rule_engine.rules.generic.document_date_rule import DocumentDateRule
        return DocumentDateRule()

    def test_valid_date_passes(self):
        assert self._rule().execute(make_doc(document_date="2026-01-15")).passed

    def test_none_fails(self):
        assert not self._rule().execute(make_doc(document_date=None)).passed

    def test_date_object_passes(self):
        assert self._rule().execute(make_doc(document_date=date(2026, 1, 15))).passed

    def test_empty_string_fails(self):
        assert not self._rule().execute(make_doc(document_date="")).passed


# ─── GEN-H05: Total amount present ───────────────────────────────────────────

@pytest.mark.unit
class TestTotalAmountPresentRule:
    def _rule(self):
        from apps.rule_engine.rules.generic.total_amount_rule import TotalAmountPresentRule
        return TotalAmountPresentRule()

    def test_positive_passes(self):
        assert self._rule().execute(make_doc(total_amount=1150.0)).passed

    def test_none_fails(self):
        assert not self._rule().execute(make_doc(total_amount=None)).passed

    def test_zero_passes_presence_check(self):
        # Amount PRESENT rule checks presence not sign
        result = self._rule().execute(make_doc(total_amount=0.0))
        assert result.passed  # 0 is present


# ─── GEN-H06: Currency ────────────────────────────────────────────────────────

@pytest.mark.unit
class TestCurrencyRule:
    def _rule(self):
        from apps.rule_engine.rules.generic.currency_rule import CurrencyRule
        return CurrencyRule()

    def test_sar_passes(self):
        assert self._rule().execute(make_doc(currency="SAR")).passed

    def test_aed_passes(self):
        assert self._rule().execute(make_doc(currency="AED")).passed

    def test_usd_passes(self):
        assert self._rule().execute(make_doc(currency="USD")).passed

    def test_missing_fails(self):
        assert not self._rule().execute(make_doc(currency=None)).passed

    def test_empty_fails(self):
        assert not self._rule().execute(make_doc(currency="")).passed

    def test_unknown_code_is_warning(self):
        result = self._rule().execute(make_doc(currency="XYZ"))
        assert result.status == "warning"
        assert not result.passed


# ─── DUP-01: Duplicate invoice ────────────────────────────────────────────────

@pytest.mark.django_db
class TestDuplicateDocumentNumberRule:
    def _rule(self):
        from apps.rule_engine.rules.invoice.duplicate_invoice_rule import DuplicateDocumentNumberRule
        return DuplicateDocumentNumberRule()

    def test_unique_invoice_passes(self, org, uploader):
        import uuid
        from apps.rule_engine.rules.base import NormalizedDocument
        doc = NormalizedDocument(
            document_id=str(uuid.uuid4()),   # Real UUID required
            document_type="invoice",
            organization_id=str(org.id),
            document_number="INV-UNIQUE-XYZ-999",
            typed_data={}, org_context={},
        )
        assert self._rule().execute(doc).passed

    def test_duplicate_number_fails(self, invoice, org):
        import uuid
        from apps.rule_engine.rules.base import NormalizedDocument
        doc = NormalizedDocument(
            document_id=str(uuid.uuid4()),   # Different UUID from the fixture invoice
            document_type="invoice",
            organization_id=str(org.id),
            document_number="INV-2026-001",  # Same number as fixture
            typed_data={}, org_context={},
        )
        assert not self._rule().execute(doc).passed

    def test_same_number_different_org_passes(self, org, uploader, db):
        import uuid
        from apps.authentication.models import Organization
        from apps.rule_engine.rules.base import NormalizedDocument
        org2 = Organization.objects.create(
            name="Org2X", name_ar="م2", country="SA",
            currency="SAR", vat_number="300000000099991",
        )
        doc = NormalizedDocument(
            document_id=str(uuid.uuid4()),
            document_type="invoice",
            organization_id=str(org2.id),
            document_number="INV-2026-001",  # Same number, different org
            typed_data={}, org_context={},
        )
        assert self._rule().execute(doc).passed


# ─── Invoice vendor name rule ─────────────────────────────────────────────────

@pytest.mark.unit
class TestInvoiceVendorNameRule:
    def _rule(self):
        from apps.rule_engine.rules.invoice.invoice_mandatory_rules import InvoiceVendorNameRule
        return InvoiceVendorNameRule()

    def test_vendor_name_present_passes(self):
        doc = make_doc(counterparty_name="Test Vendor")
        assert self._rule().execute(doc).passed

    def test_vendor_in_typed_data_passes(self):
        doc = make_doc(typed_data={"vendor_name": "Vendor Ltd"})
        assert self._rule().execute(doc).passed

    def test_no_vendor_fails(self):
        doc = make_doc(counterparty_name=None, typed_data={})
        assert not self._rule().execute(doc).passed


# ─── Invoice status lifecycle ─────────────────────────────────────────────────

@pytest.mark.django_db
class TestInvoiceStatusLifecycle:
    def test_transitions_to_validated(self, invoice):
        invoice.status = "validated"
        invoice.save()
        invoice.refresh_from_db()
        assert invoice.status == "validated"

    def test_transitions_to_flagged(self, invoice):
        invoice.status = "flagged"
        invoice.save()
        invoice.refresh_from_db()
        assert invoice.status == "flagged"

    def test_transitions_to_approved(self, invoice):
        invoice.status = "approved"
        invoice.save()
        invoice.refresh_from_db()
        assert invoice.status == "approved"

    def test_transitions_to_rejected(self, invoice):
        invoice.status = "rejected"
        invoice.save()
        invoice.refresh_from_db()
        assert invoice.status == "rejected"
