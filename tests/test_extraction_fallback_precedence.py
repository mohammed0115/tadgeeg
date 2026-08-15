"""Regression guards for parser-authoritative invoice extraction."""
from __future__ import annotations

import io
import json

from openpyxl import Workbook

from apps.invoices.services.processor import _merge_extraction_payloads
from core.services.document_engine import DocumentEngine
from core.services.invoice_ai_service import _fallback_extraction
from core.services.normalization import NormalizationService
from core.services.parsers.structured import iter_structured_records


def test_parser_value_is_not_overwritten_and_fallback_only_fills_a_gap():
    parser = {
        "invoice_number": "INV-PARSER-001",
        "vendor_name": "Authoritative Supplier",
        "total_amount": 1150.0,
        "has_qr_code": False,
    }
    failed_fallback = {
        "invoice_number": "oice",
        "vendor_name": "broken fragment",
        "total_amount": 0.0,
        "vat_amount": 150.0,
        "has_qr_code": True,
        "customer_name": "Filled only because parser omitted it",
    }

    merged = _merge_extraction_payloads(parser, failed_fallback)

    assert merged["invoice_number"] == "INV-PARSER-001"
    assert merged["vendor_name"] == "Authoritative Supplier"
    assert merged["total_amount"] == 1150.0
    assert merged["has_qr_code"] is False
    assert merged["vat_amount"] == 150.0
    assert merged["customer_name"] == "Filled only because parser omitted it"
    assert "due_date" not in merged


def test_json_parser_values_survive_a_failed_text_fallback(tmp_path):
    payload = {
        "invoice_number": "INV-JSON-001",
        "vendor_name": "JSON Supplier",
        "vendor_vat_number": "310123456700003",
        "invoice_date": "2026-08-15",
        "currency": "SAR",
        "subtotal": 1000.0,
        "vat_amount": 150.0,
        "total_amount": 1150.0,
    }
    path = tmp_path / "invoice.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    ingestion = DocumentEngine(use_ai=False).ingest(str(path))
    assert ingestion.success is True
    fallback = _fallback_extraction(ingestion.raw_text)
    normalized = NormalizationService().normalize(
        _merge_extraction_payloads(ingestion.structured, ingestion.normalized, fallback)
    ).normalized_data

    assert normalized["invoice_number"] == "INV-JSON-001"
    assert normalized["vendor_name"] == "JSON Supplier"
    assert normalized["subtotal"] == 1000.0
    assert normalized["vat_amount"] == 150.0
    assert normalized["total_amount"] == 1150.0


def test_xlsx_row_values_survive_a_failed_text_fallback(tmp_path):
    path = tmp_path / "invoice.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["invoice_number", "vendor_name", "invoice_date", "currency", "subtotal", "vat_amount", "total_amount"])
    sheet.append(["INV-XLSX-001", "XLSX Supplier", "2026-08-15", "SAR", "1000.00", "150.00", "1150.00"])
    workbook.save(path)

    uploaded = io.BytesIO(path.read_bytes())
    uploaded.name = path.name
    rows = list(iter_structured_records(uploaded, path.name) or [])
    assert len(rows) == 1
    _, parser_payload = rows[0]
    fallback = _fallback_extraction(json.dumps(parser_payload))
    normalized = NormalizationService().normalize(
        _merge_extraction_payloads(parser_payload, fallback)
    ).normalized_data

    assert normalized["invoice_number"] == "INV-XLSX-001"
    assert normalized["vendor_name"] == "XLSX Supplier"
    assert normalized["subtotal"] == 1000.0
    assert normalized["vat_amount"] == 150.0
    assert normalized["total_amount"] == 1150.0
