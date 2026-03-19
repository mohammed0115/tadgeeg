"""Parser Service — thin wrapper delegating to core parser stack."""
from __future__ import annotations
import json
import logging

logger = logging.getLogger(__name__)


class ParserService:
    """Delegates structured file parsing to the canonical core parser stack."""

    def parse_excel(self, file_path: str) -> str:
        try:
            from core.services.parsers.excel_parser import ExcelParser
            parser = ExcelParser()
            result = parser.parse(file_path)
            return result.text if hasattr(result, "text") else str(result)
        except Exception as exc:
            logger.warning("Excel parse via core failed, falling back to pandas: %s", exc)
            return self._pandas_excel_fallback(file_path)

    def _pandas_excel_fallback(self, file_path: str) -> str:
        try:
            import pandas as pd
            df = pd.read_excel(file_path, nrows=500)
            return df.to_string(index=False, max_rows=300)
        except Exception as exc:
            logger.warning("Pandas Excel fallback failed: %s", exc)
            return ""

    def parse_csv(self, file_path: str) -> str:
        try:
            from core.services.parsers.csv_parser import CsvParser
            parser = CsvParser()
            result = parser.parse(file_path)
            return result.text if hasattr(result, "text") else str(result)
        except Exception as exc:
            logger.warning("CSV parse via core failed, falling back to pandas: %s", exc)
            return self._pandas_csv_fallback(file_path)

    def _pandas_csv_fallback(self, file_path: str) -> str:
        try:
            import pandas as pd
            df = pd.read_csv(file_path, nrows=500)
            return df.to_string(index=False, max_rows=300)
        except Exception as exc:
            logger.warning("Pandas CSV fallback failed: %s", exc)
            return ""

    def parse_json(self, file_path: str) -> str:
        try:
            from core.services.parsers.json_parser import JsonParser
            parser = JsonParser()
            result = parser.parse(file_path)
            return result.text if hasattr(result, "text") else str(result)
        except Exception as exc:
            logger.warning("JSON parse via core failed, falling back to stdlib: %s", exc)
            return self._json_fallback(file_path)

    def _json_fallback(self, file_path: str) -> str:
        try:
            with open(file_path, encoding="utf-8", errors="replace") as f:
                data = json.load(f)
            return json.dumps(data, ensure_ascii=False, indent=2)[:8000]
        except Exception as exc:
            logger.warning("JSON stdlib fallback failed: %s", exc)
            return ""
