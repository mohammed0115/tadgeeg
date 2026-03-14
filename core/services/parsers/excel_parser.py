"""
Excel Parser — XLS / XLSX

Pipeline:
  1. Load workbook with openpyxl (xlsx) or xlrd (xls)
  2. Detect header row using heuristics / AI column mapping
  3. Normalise column names to standard financial schema
  4. Return structured records + raw serialised text

Column mapping is essential because real-world Excel files use
arbitrary headers ("Txn Date", "Amount SAR", "Vendor Name", …).
AI-assisted mapping via OpenAI is attempted when fuzzy matching fails.
"""

import json
import logging
from typing import Optional

from .base_parser import DocumentParser, ParseResult

logger = logging.getLogger("finai")

SUPPORTED_EXTENSIONS = (".xls", ".xlsx", ".xlsm", ".xlsb")
SUPPORTED_MIMES = (
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)

# Target schema fields
STANDARD_FIELDS = {
    "date": ["date", "txn date", "transaction date", "invoice date", "doc date",
             "value date", "posting date", "تاريخ"],
    "amount": ["amount", "total", "total amount", "value", "debit", "credit",
               "amount sar", "amount usd", "المبلغ", "الإجمالي"],
    "vendor": ["vendor", "vendor name", "supplier", "payee", "company",
               "merchant", "المورد", "اسم المورد"],
    "description": ["description", "details", "narration", "particular", "note",
                    "البيان", "الوصف"],
    "reference": ["reference", "ref", "invoice number", "invoice no", "doc no",
                  "المرجع", "رقم الفاتورة"],
    "currency": ["currency", "ccy", "العملة"],
    "vat": ["vat", "tax", "vat amount", "tax amount", "ضريبة", "القيمة المضافة"],
}


class ExcelParser(DocumentParser):
    """
    Parser for Excel spreadsheets (.xls/.xlsx).

    Supports multi-sheet workbooks and AI-assisted column mapping.
    """

    supported_extensions = SUPPORTED_EXTENSIONS
    supported_mimes = SUPPORTED_MIMES

    def parse(self, file_path: str, use_ai: bool = True, **kwargs) -> ParseResult:
        result = ParseResult(extraction_method="excel")

        try:
            import pandas as pd
        except ImportError:
            result.fatal_error = "pandas is not installed."
            return result

        # ── Load workbook ─────────────────────────────────────────────────────
        sheets = self._load_all_sheets(file_path, pd, result)
        if not sheets:
            result.fatal_error = "Could not read any sheets from the Excel file."
            return result

        all_records: list[dict] = []
        raw_text_parts: list[str] = []

        for sheet_name, df in sheets.items():
            if df.empty:
                continue

            # ── Column mapping ────────────────────────────────────────────────
            col_map = self._map_columns(df.columns.tolist(), use_ai)

            # ── Normalise dataframe ───────────────────────────────────────────
            renamed_df = df.rename(columns=col_map)
            records = self._df_to_records(renamed_df, sheet_name)
            all_records.extend(records)

            # Raw text representation
            raw_text_parts.append(f"=== Sheet: {sheet_name} ===")
            raw_text_parts.append(renamed_df.to_string(index=False))

        result.raw_text = "\n\n".join(raw_text_parts)
        result.structured = {
            "records": all_records,
            "sheet_count": len(sheets),
            "record_count": len(all_records),
        }
        result.metadata["sheet_names"] = list(sheets.keys())
        result.metadata["record_count"] = len(all_records)
        result.success = bool(all_records)
        if not result.success:
            result.fatal_error = "Excel file contained no parseable records."
        return result

    # ── Load helpers ──────────────────────────────────────────────────────────

    def _load_all_sheets(self, file_path: str, pd, result: ParseResult) -> dict:
        """Load all sheets from an Excel file, trying both engines."""
        try:
            sheets = pd.read_excel(
                file_path,
                sheet_name=None,
                dtype=str,   # Keep everything as string for initial load
                keep_default_na=False,
            )
            return sheets
        except Exception as exc:
            result.add_error(f"openpyxl/xlrd load failed: {exc}")

        # Fallback: try xlrd engine explicitly for .xls
        try:
            import xlrd  # noqa: F401
            sheets = pd.read_excel(
                file_path,
                sheet_name=None,
                engine="xlrd",
                dtype=str,
                keep_default_na=False,
            )
            return sheets
        except Exception as exc2:
            result.add_error(f"xlrd fallback failed: {exc2}")

        return {}

    # ── Column mapping ────────────────────────────────────────────────────────

    def _map_columns(self, columns: list[str], use_ai: bool) -> dict:
        """
        Map raw column names to standard schema field names.

        Strategy:
          1. Exact match (lowercase)
          2. Substring / fuzzy match
          3. AI-assisted mapping if enabled and fuzzy failed
        """
        col_map: dict[str, str] = {}
        unmapped: list[str] = []

        for col in columns:
            target = self._fuzzy_match(col)
            if target:
                col_map[col] = target
            else:
                unmapped.append(col)

        if unmapped and use_ai:
            ai_map = self._ai_map_columns(unmapped)
            col_map.update(ai_map)

        return col_map

    def _fuzzy_match(self, column: str) -> Optional[str]:
        """Return the standard field name for a raw column, or None."""
        normalised = column.lower().strip()
        for target_field, aliases in STANDARD_FIELDS.items():
            for alias in aliases:
                if alias in normalised or normalised in alias:
                    return target_field
        return None

    def _ai_map_columns(self, columns: list[str]) -> dict:
        """Use OpenAI to map remaining unmapped columns."""
        try:
            from core.services.ai.openai_extractor import map_excel_columns

            return map_excel_columns(columns, list(STANDARD_FIELDS.keys()))
        except Exception as exc:
            logger.warning("[ExcelParser] AI column mapping failed: %s", exc)
            return {}

    # ── Record normalisation ──────────────────────────────────────────────────

    def _df_to_records(self, df, sheet_name: str) -> list[dict]:
        """Convert a normalised DataFrame to a list of record dicts."""
        records = []
        for _, row in df.iterrows():
            record = {k: v for k, v in row.items() if v and str(v).strip()}
            if record:
                record["_sheet"] = sheet_name
                records.append(record)
        return records
