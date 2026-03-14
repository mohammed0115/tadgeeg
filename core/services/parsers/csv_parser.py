"""
CSV Parser

Pipeline:
  1. Detect encoding (UTF-8, UTF-16, CP1256 for Arabic)
  2. Detect delimiter (comma, semicolon, pipe, tab)
  3. Load with pandas
  4. Map columns to standard financial schema
  5. Return structured records

Handles common real-world issues: BOM markers, mixed encodings,
inconsistent delimiters, and Arabic column headers.
"""

import logging
from io import BytesIO
from typing import Optional

from .base_parser import DocumentParser, ParseResult

logger = logging.getLogger("finai")

SUPPORTED_EXTENSIONS = (".csv", ".tsv", ".txt")
SUPPORTED_MIMES = ("text/csv", "text/tab-separated-values", "text/plain")

CANDIDATE_ENCODINGS = ["utf-8-sig", "utf-8", "utf-16", "cp1256", "iso-8859-1", "latin-1"]
CANDIDATE_DELIMITERS = [",", ";", "\t", "|"]

# Mirror the standard fields from excel_parser
STANDARD_FIELDS = {
    "date": ["date", "txn date", "transaction date", "invoice date", "value date",
             "posting date", "تاريخ"],
    "amount": ["amount", "total", "total amount", "debit", "credit", "value",
               "amount sar", "المبلغ"],
    "vendor": ["vendor", "supplier", "payee", "merchant", "company", "المورد"],
    "description": ["description", "details", "narration", "البيان"],
    "reference": ["reference", "ref", "invoice no", "invoice number", "المرجع"],
    "currency": ["currency", "ccy", "العملة"],
    "vat": ["vat", "tax", "vat amount", "ضريبة"],
}


class CSVParser(DocumentParser):
    """Parser for CSV and TSV financial data files."""

    supported_extensions = SUPPORTED_EXTENSIONS
    supported_mimes = SUPPORTED_MIMES

    def parse(self, file_path: str, **kwargs) -> ParseResult:
        result = ParseResult(extraction_method="csv")

        try:
            import pandas as pd
        except ImportError:
            result.fatal_error = "pandas is not installed."
            return result

        raw_bytes = self._safe_read_bytes(file_path)
        if raw_bytes is None:
            result.fatal_error = "Cannot read file."
            return result

        # ── Detect encoding ───────────────────────────────────────────────────
        encoding = self._detect_encoding(raw_bytes, result)

        # ── Detect delimiter ──────────────────────────────────────────────────
        try:
            sample = raw_bytes[:4096].decode(encoding, errors="replace")
        except Exception:
            sample = raw_bytes[:4096].decode("utf-8", errors="replace")

        delimiter = self._detect_delimiter(sample)
        result.metadata["encoding"] = encoding
        result.metadata["delimiter"] = delimiter

        # ── Load DataFrame ────────────────────────────────────────────────────
        df = self._load_dataframe(BytesIO(raw_bytes), encoding, delimiter, pd, result)
        if df is None or df.empty:
            result.fatal_error = "CSV produced an empty DataFrame."
            return result

        result.metadata["row_count"] = len(df)
        result.metadata["column_count"] = len(df.columns)

        # ── Map columns ───────────────────────────────────────────────────────
        col_map = self._map_columns(df.columns.tolist())
        renamed = df.rename(columns=col_map)

        # ── Build records ─────────────────────────────────────────────────────
        records = []
        for _, row in renamed.iterrows():
            record = {k: str(v).strip() for k, v in row.items() if str(v).strip()}
            if record:
                records.append(record)

        result.raw_text = renamed.to_string(index=False)
        result.structured = {
            "records": records,
            "record_count": len(records),
            "columns": renamed.columns.tolist(),
        }
        result.success = bool(records)
        if not result.success:
            result.fatal_error = "No records found in CSV."
        return result

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _detect_encoding(self, raw: bytes, result: ParseResult) -> str:
        # Try chardet first
        try:
            import chardet
            detected = chardet.detect(raw[:8192])
            enc = detected.get("encoding") or "utf-8"
            confidence = detected.get("confidence", 0)
            if confidence > 0.6:
                return enc
        except ImportError:
            pass

        # Brute-force candidate encodings
        for enc in CANDIDATE_ENCODINGS:
            try:
                raw.decode(enc)
                return enc
            except (UnicodeDecodeError, LookupError):
                continue

        result.add_error("Could not detect encoding; defaulting to utf-8.")
        return "utf-8"

    def _detect_delimiter(self, sample: str) -> str:
        counts = {d: sample.count(d) for d in CANDIDATE_DELIMITERS}
        return max(counts, key=counts.get, default=",")

    def _load_dataframe(self, source, encoding: str, delimiter: str, pd, result: ParseResult):
        try:
            return pd.read_csv(
                source,
                sep=delimiter,
                encoding=encoding,
                dtype=str,
                keep_default_na=False,
                on_bad_lines="skip",
            )
        except Exception as exc:
            result.add_error(f"pandas CSV load failed: {exc}")
            return None

    def _map_columns(self, columns: list[str]) -> dict:
        col_map: dict[str, str] = {}
        for col in columns:
            norm = col.lower().strip()
            for target, aliases in STANDARD_FIELDS.items():
                for alias in aliases:
                    if alias in norm or norm in alias:
                        col_map[col] = target
                        break
                if col in col_map:
                    break
        return col_map
