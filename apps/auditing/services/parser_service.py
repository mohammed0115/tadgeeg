"""Parser Service — parse Excel/CSV/JSON into text for AI."""

import json
import logging
import os

logger = logging.getLogger(__name__)


class ParserService:
    """Parse Excel/CSV/JSON into a text representation for AI processing."""

    def parse_excel(self, file_path: str) -> str:
        """Read all sheets from an Excel file and return as formatted text table."""
        try:
            import pandas as pd

            results = []
            xl = pd.ExcelFile(file_path)
            for sheet_name in xl.sheet_names:
                try:
                    df = pd.read_excel(file_path, sheet_name=sheet_name, dtype=str)
                    df = df.fillna("")
                    if df.empty:
                        continue
                    results.append(f"=== ورقة العمل: {sheet_name} ===")
                    results.append(df.to_string(index=False, max_rows=500, max_cols=30))
                except Exception as exc:
                    logger.warning("Failed to parse sheet '%s': %s", sheet_name, exc)
                    results.append(f"=== ورقة العمل: {sheet_name} (فشل التحليل: {exc}) ===")

            return "\n\n".join(results) if results else ""
        except ImportError:
            logger.error("pandas is not installed. Cannot parse Excel.")
            return ""
        except Exception as exc:
            logger.exception("Excel parsing failed for %s: %s", file_path, exc)
            return ""

    def parse_csv(self, file_path: str) -> str:
        """Read a CSV file and return as formatted text table."""
        try:
            import pandas as pd

            # Try multiple encodings
            for encoding in ("utf-8", "utf-8-sig", "cp1256", "iso-8859-1"):
                try:
                    df = pd.read_csv(file_path, dtype=str, encoding=encoding)
                    df = df.fillna("")
                    if df.empty:
                        return ""
                    return df.to_string(index=False, max_rows=500, max_cols=30)
                except UnicodeDecodeError:
                    continue
            logger.warning("Could not decode CSV with any known encoding: %s", file_path)
            return ""
        except ImportError:
            logger.error("pandas is not installed. Cannot parse CSV.")
            return ""
        except Exception as exc:
            logger.exception("CSV parsing failed for %s: %s", file_path, exc)
            return ""

    def parse_json(self, file_path: str) -> str:
        """Load JSON or JSONL file and return a pretty-printed string."""
        try:
            ext = os.path.splitext(file_path)[1].lower()
            with open(file_path, "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read().strip()

            if ext == ".jsonl":
                # JSONL: one JSON object per line
                lines = [line.strip() for line in content.splitlines() if line.strip()]
                records = []
                for line in lines:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
                return json.dumps(records, ensure_ascii=False, indent=2)
            else:
                data = json.loads(content)
                return json.dumps(data, ensure_ascii=False, indent=2)
        except json.JSONDecodeError as exc:
            logger.warning("JSON decode error for %s: %s", file_path, exc)
            # Return raw content as fallback
            try:
                with open(file_path, "r", encoding="utf-8", errors="replace") as fh:
                    return fh.read()
            except Exception:
                return ""
        except Exception as exc:
            logger.exception("JSON parsing failed for %s: %s", file_path, exc)
            return ""
