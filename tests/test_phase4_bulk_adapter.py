"""
Phase-4 bulk-upload adapter tests.

Covers:
  - Field-alias resolution (English + Arabic columns)
  - Type coercion (Date, Decimal, Boolean, Integer, JSONField)
  - CSV / JSON / JSONL ingest
  - Empty / missing-column handling
  - Round-trip persistence into all 10 Phase-2 typed models
"""
from __future__ import annotations

import csv
import io
import json
import tempfile
from decimal import Decimal
from datetime import date

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.documents.bulk_adapter import (
    PHASE2_TYPES,
    extract_phase2_records,
    create_phase2_record,
    _normalize_col,
    _to_date,
    _to_decimal,
    _to_bool,
    _to_int,
    _DOC_MODEL,
)
from apps.documents.models import Document
from apps.documents.typed_models_v2 import (
    SalesOrder, Quotation, ProformaInvoice, ReceiptVoucher, CashVoucher,
    GeneralLedger, Ledger, Contract, SupplierStatement, CustomerStatement,
)


# ─── Helpers ────────────────────────────────────────────────────────────────

def _csv(path: str, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        if not rows:
            return
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def _make_base_doc(org):
    return Document.objects.create(
        organization=org,
        file=SimpleUploadedFile("test.csv", b"csv"),
        original_filename="test.csv",
        file_size=10,
        mime_type="text/csv",
        document_type=Document.DocumentType.OTHER,
    )


# ─── Pure-function tests (no DB) ────────────────────────────────────────────

class TestColumnNormalization:
    @pytest.mark.parametrize("raw,expected", [
        ("Total Amount (SAR)", "total_amount"),
        ("VAT (15%)", "vat"),
        ("po_number", "po_number"),
        ("Invoice  Number", "invoice_number"),
        ("date-issued", "date_issued"),
        ("  trim_me  ", "trim_me"),
        ("MIXED-Case", "mixed_case"),
    ])
    def test_normalises(self, raw, expected):
        assert _normalize_col(raw) == expected


class TestTypeCoercion:
    def test_date_iso(self):
        assert _to_date("2026-04-15") == date(2026, 4, 15)

    def test_date_european(self):
        assert _to_date("15/04/2026") == date(2026, 4, 15)

    @pytest.mark.parametrize("bad", [None, "", "nan", "none", "garbage", "2026-99-99"])
    def test_date_falsy(self, bad):
        assert _to_date(bad) is None

    def test_decimal_with_commas(self):
        assert _to_decimal("1,234.56") == Decimal("1234.56")

    def test_decimal_falsy(self):
        assert _to_decimal(None) == Decimal("0")
        assert _to_decimal("") == Decimal("0")
        assert _to_decimal("not-a-number") == Decimal("0")

    @pytest.mark.parametrize("raw,expected", [
        ("true", True), ("yes", True), ("1", True), ("نعم", True), ("✓", True),
        ("false", False), ("no", False), ("", False), ("0", False),
        (None, False), (True, True), (False, False),
    ])
    def test_bool(self, raw, expected):
        assert _to_bool(raw) is expected

    @pytest.mark.parametrize("raw,expected", [
        ("42", 42), ("1,000", 1000), ("3.7", 3), ("", 0), (None, 0), ("xyz", 0),
    ])
    def test_int(self, raw, expected):
        assert _to_int(raw) == expected


# ─── Adapter end-to-end ─────────────────────────────────────────────────────

class TestExtractPhase2Records:
    def test_csv_english_columns(self, tmp_path):
        path = str(tmp_path / "so.csv")
        _csv(path, [{
            "so_number": "SO-1", "so_date": "2026-04-15",
            "customer_name": "Acme", "currency": "SAR",
            "total_amount": "1500.00",
        }])
        records = extract_phase2_records(path, ".csv", "sales_order")
        assert len(records) == 1
        rec = records[0]
        assert rec["so_number"] == "SO-1"
        assert rec["so_date"] == date(2026, 4, 15)
        assert rec["customer_name"] == "Acme"
        assert rec["total_amount"] == Decimal("1500.00")

    def test_csv_arabic_columns(self, tmp_path):
        path = str(tmp_path / "pf.csv")
        _csv(path, [{
            "رقم الفاتورة المبدئية": "PF-AR-1",
            "تاريخ الفاتورة": "2026-03-10",
            "اسم العميل": "شركة المملكة",
            "العملة": "SAR",
            "إجمالي قبل الضريبة": "5000",
            "ضريبة القيمة المضافة": "750",
            "الإجمالي": "5750",
        }])
        records = extract_phase2_records(path, ".csv", "proforma_invoice")
        assert len(records) == 1
        rec = records[0]
        assert rec["proforma_number"] == "PF-AR-1"
        assert rec["customer_name"] == "شركة المملكة"
        assert rec["total_amount"] == Decimal("5750")

    def test_json_array(self, tmp_path):
        path = str(tmp_path / "gl.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump([
                {"period_from": "2026-01-01", "period_to": "2026-03-31",
                 "fiscal_year": "2026", "total_debit": "100", "total_credit": "100",
                 "is_balanced": True},
            ], f)
        records = extract_phase2_records(path, ".json", "general_ledger")
        assert len(records) == 1
        assert records[0]["fiscal_year"] == "2026"
        assert records[0]["is_balanced"] is True

    def test_json_records_envelope(self, tmp_path):
        """JSON with {records: [...]} envelope is unwrapped."""
        path = str(tmp_path / "ct.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"records": [{"contract_number": "CT-J-1", "party_b": "X"}]}, f)
        records = extract_phase2_records(path, ".json", "contract")
        assert len(records) == 1
        assert records[0]["contract_number"] == "CT-J-1"

    def test_jsonl(self, tmp_path):
        path = str(tmp_path / "rv.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"receipt_number": "RV-J-1", "amount": "100"}) + "\n")
            f.write(json.dumps({"receipt_number": "RV-J-2", "amount": "200"}) + "\n")
        records = extract_phase2_records(path, ".jsonl", "receipt_voucher")
        assert len(records) == 2
        assert records[0]["receipt_number"] == "RV-J-1"
        assert records[1]["amount"] == Decimal("200")

    def test_unknown_columns_silently_dropped(self, tmp_path):
        """Junk columns shouldn't crash; only mapped fields make it through."""
        path = str(tmp_path / "so.csv")
        _csv(path, [{"so_number": "SO-J-1", "totally_made_up": "xxx",
                     "internal_note_id": "9999"}])
        records = extract_phase2_records(path, ".csv", "sales_order")
        assert len(records) == 1
        assert records[0]["so_number"] == "SO-J-1"
        assert "totally_made_up" not in records[0]
        assert "internal_note_id" not in records[0]

    def test_unknown_doc_type_returns_empty(self, tmp_path):
        path = str(tmp_path / "x.csv")
        _csv(path, [{"a": "1"}])
        assert extract_phase2_records(path, ".csv", "not_a_real_type") == []

    def test_empty_rows_excluded(self, tmp_path):
        """Rows with all-empty values should drop out, not become empty model rows."""
        path = str(tmp_path / "empty.csv")
        _csv(path, [{"so_number": "", "customer_name": ""}])
        assert extract_phase2_records(path, ".csv", "sales_order") == []


# ─── Round-trip into typed models ───────────────────────────────────────────

@pytest.mark.django_db
class TestCreatePhase2Record:
    """Each Phase-2 doc-type gets a smoke round-trip."""

    @pytest.fixture
    def base(self, organization, admin_user):
        return _make_base_doc(organization), organization, admin_user

    def test_phase2_types_set_matches_dispatch(self):
        assert PHASE2_TYPES == frozenset(_DOC_MODEL.keys())
        # 10 Phase-2 types + GRN + PaymentVoucher + JournalEntry (late additions
        # that round out the full 20-type catalog).
        assert len(PHASE2_TYPES) == 13

    def test_sales_order_roundtrip(self, base):
        doc, org, user = base
        rec = {"so_number": "SO-T-1", "so_date": date(2026, 4, 1),
               "customer_name": "Acme", "total_amount": Decimal("1500"),
               "currency": "SAR", "status": "confirmed"}
        obj = create_phase2_record("sales_order", rec, doc, org, user)
        assert isinstance(obj, SalesOrder)
        assert obj.organization_id == org.id
        assert obj.document_id == doc.id
        assert obj.so_number == "SO-T-1"
        assert obj.total_amount == Decimal("1500")

    def test_contract_roundtrip(self, base):
        doc, org, user = base
        rec = {"contract_number": "CT-T-1", "title": "Test",
               "party_b": "VendorX", "is_signed": True,
               "start_date": date(2026, 1, 1),
               "end_date": date(2026, 12, 31),
               "contract_value": Decimal("50000")}
        obj = create_phase2_record("contract", rec, doc, org, user)
        assert obj.contract_number == "CT-T-1"
        assert obj.is_signed is True
        assert obj.contract_value == Decimal("50000")

    def test_unknown_fields_skipped(self, base):
        """Coerced data with extra keys must not raise — adapter filters."""
        doc, org, user = base
        rec = {"so_number": "SO-EXTRA", "customer_name": "Acme",
               "fake_field_x": "y", "another_fake": "z"}
        obj = create_phase2_record("sales_order", rec, doc, org, user)
        assert obj.so_number == "SO-EXTRA"

    def test_all_ten_types_create(self, base):
        """Smoke: every doc type can be instantiated empty."""
        doc, org, user = base
        for dtype in PHASE2_TYPES:
            d = _make_base_doc(org)  # fresh document (one-to-one constraint)
            obj = create_phase2_record(dtype, {}, d, org, user)
            assert obj.pk is not None, f"{dtype} failed to create"
            assert obj.organization_id == org.id


# ─── Tenant isolation: ensure adapter does not bridge orgs ──────────────────

@pytest.mark.django_db
class TestBulkAdapterTenantIsolation:
    """The adapter writes to the org passed in — never the file's source org."""

    def test_creates_under_caller_org(self, organization, admin_user):
        from apps.authentication.models import Organization
        other_org = Organization.objects.create(
            name="Other Co", country=Organization.Country.SAUDI_ARABIA,
            currency=Organization.Currency.SAR, vat_number="300000000000004",
        )
        doc = _make_base_doc(organization)

        rec = {"so_number": "SO-ISO-1", "customer_name": "X"}
        obj = create_phase2_record("sales_order", rec, doc, organization, admin_user)

        # Cannot be visible from the other org's queryset
        assert SalesOrder.objects.filter(organization=other_org, id=obj.id).count() == 0
        assert SalesOrder.objects.filter(organization=organization, id=obj.id).count() == 1
