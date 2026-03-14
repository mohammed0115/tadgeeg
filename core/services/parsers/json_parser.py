"""
JSON Parser

Pipeline:
  1. Parse JSON bytes (handles BOM, trailing commas via lenient parser)
  2. Flatten nested structures to financial records
  3. Map known keys to standard schema
  4. Return structured data + raw text

Handles both single-object and array-of-objects formats.
"""

import json
import logging
from typing import Any

from .base_parser import DocumentParser, ParseResult

logger = logging.getLogger("finai")

SUPPORTED_EXTENSIONS = (".json", ".jsonl")
SUPPORTED_MIMES = ("application/json", "application/x-jsonlines")

# Standard financial keys this parser tries to detect
FINANCIAL_KEY_MAP = {
    "invoice_number": ["invoice_number", "invoice_no", "inv_no", "invoiceid",
                       "doc_number", "document_number"],
    "vendor_name": ["vendor_name", "vendor", "supplier", "supplier_name",
                    "merchant", "company_name"],
    "date": ["date", "invoice_date", "txn_date", "transaction_date",
             "doc_date", "value_date"],
    "total_amount": ["total_amount", "total", "amount", "grand_total",
                     "invoice_total", "net_total"],
    "tax_amount": ["tax_amount", "vat_amount", "tax", "vat"],
    "currency": ["currency", "ccy"],
    "line_items": ["line_items", "items", "lines", "details"],
}


class JSONParser(DocumentParser):
    """
    Parser for JSON financial documents.

    Handles both single-object invoices/transactions and
    arrays of financial records.
    """

    supported_extensions = SUPPORTED_EXTENSIONS
    supported_mimes = SUPPORTED_MIMES

    def parse(self, file_path: str, **kwargs) -> ParseResult:
        result = ParseResult(extraction_method="json")

        raw_bytes = self._safe_read_bytes(file_path)
        if raw_bytes is None:
            result.fatal_error = "Cannot read file."
            return result

        # ── Parse ─────────────────────────────────────────────────────────────
        data = self._parse_json(raw_bytes, result)
        if data is None:
            result.fatal_error = "File could not be parsed as valid JSON."
            return result

        # ── Serialise raw text ────────────────────────────────────────────────
        result.raw_text = json.dumps(data, ensure_ascii=False, indent=2)

        # ── Normalise to records ──────────────────────────────────────────────
        if isinstance(data, list):
            records = [self._normalise_record(item) for item in data if isinstance(item, dict)]
            result.structured = {
                "records": records,
                "record_count": len(records),
                "format": "array",
            }
        elif isinstance(data, dict):
            normalised = self._normalise_record(data)
            result.structured = {
                "records": [normalised],
                "record_count": 1,
                "format": "single_object",
                **normalised,
            }
        else:
            result.add_error(f"Unexpected top-level JSON type: {type(data).__name__}")
            result.structured = {"raw": data}

        result.metadata["json_type"] = "array" if isinstance(data, list) else "object"
        result.success = True
        return result

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _parse_json(self, raw: bytes, result: ParseResult) -> Any:
        # Strip BOM
        raw = raw.lstrip(b"\xef\xbb\xbf")

        # Attempt standard parse
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            pass

        # Try with different encodings
        for enc in ("utf-16", "cp1256", "latin-1"):
            try:
                return json.loads(raw.decode(enc))
            except Exception:
                continue

        # Try lenient JSON parsing (strip trailing commas, comments)
        try:
            import re
            text = raw.decode("utf-8", errors="replace")
            # Remove single-line comments
            text = re.sub(r"//[^\n]*", "", text)
            # Remove trailing commas before ] or }
            text = re.sub(r",(\s*[}\]])", r"\1", text)
            return json.loads(text)
        except Exception as exc:
            result.add_error(f"Lenient JSON parse failed: {exc}")

        return None

    def _normalise_record(self, raw: dict) -> dict:
        """Map arbitrary JSON keys to standard financial schema."""
        normalised: dict = {}

        for target_field, source_keys in FINANCIAL_KEY_MAP.items():
            for key in source_keys:
                # Case-insensitive key lookup
                for raw_key, value in raw.items():
                    if raw_key.lower() == key.lower():
                        normalised[target_field] = value
                        break
                if target_field in normalised:
                    break

        # Keep all unmapped fields as-is
        for k, v in raw.items():
            if k not in normalised:
                normalised[f"_raw_{k}"] = v

        return normalised
