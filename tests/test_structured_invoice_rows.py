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
