"""Regression coverage for structured invoice rows.

A CSV row is already a structured source of truth.  It must not be passed through
DocumentEngine as a synthetic JSON file, because that path can recover fragments
of keys instead of the values selected by the CSV parser.
"""


def test_structured_row_is_forwarded_as_authoritative_payload(monkeypatch):
    from apps.invoices.services import processor

    seen = []

    def _fake_process(file_obj, filename, org, user, batch, request, audit_session,
                      structured_payload=None):
        seen.append({
            "filename": filename,
            "payload": structured_payload,
            "bytes": file_obj.read(),
        })
        return {
            "success": True,
            "is_duplicate": False,
            "risk_level": "low",
            "status": "processed",
            "rules_failed": 0,
        }

    monkeypatch.setattr(processor, "process_single_file", _fake_process)
    payload = {
        "invoice_number": "INV-2026-001",
        "vendor_name": "Example Supplier",
        "total_amount": "1250.75",
        "vat_amount": "187.61",
    }

    result = processor.process_structured_rows_chunk(
        [{"row_number": 2, "payload": payload}],
        base_name="sales",
        org=None,
        user=None,
        batch=None,
    )

    assert result["success_count"] == 1
    assert seen == [{
        "filename": "sales_row2.json",
        "payload": payload,
        "bytes": b'{"invoice_number": "INV-2026-001", "vendor_name": "Example Supplier", "total_amount": "1250.75", "vat_amount": "187.61"}',
    }]


def test_single_json_object_is_forwarded_as_one_authoritative_row():
    import io
    import json

    from core.services.parsers.structured import iter_structured_records

    payload = {
        "invoice_number": "INV-JSON-SINGLE-001",
        "vendor_name": "Single JSON Supplier",
        "subtotal": 1000.0,
        "vat_amount": 150.0,
        "total_amount": 1150.0,
    }
    uploaded = io.BytesIO(json.dumps(payload).encode("utf-8"))
    uploaded.name = "single-invoice.json"

    assert list(iter_structured_records(uploaded, uploaded.name) or []) == [(
        1,
        {
            **payload,
            "subtotal": "1000.0",
            "vat_amount": "150.0",
            "total_amount": "1150.0",
        },
    )]



def test_xlsx_field_value_sheet_is_forwarded_as_one_authoritative_row(tmp_path):
    from openpyxl import Workbook

    from core.services.parsers.structured import iter_structured_records

    path = tmp_path / "key-value-invoice.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Field", "Value"])
    sheet.append(["invoice_number", "INV-XLSX-KV-001"])
    sheet.append(["vendor_name", "Key Value Supplier"])
    sheet.append(["subtotal", 1000.0])
    sheet.append(["vat_amount", 150.0])
    sheet.append(["total_amount", 1150.0])
    workbook.save(path)

    with path.open("rb") as uploaded:
        rows = list(iter_structured_records(uploaded, path.name) or [])

    assert rows == [(
        2,
        {
            "invoice_number": "INV-XLSX-KV-001",
            "vendor_name": "Key Value Supplier",
            "subtotal": "1000",
            "vat_amount": "150",
            "total_amount": "1150",
        },
    )]
