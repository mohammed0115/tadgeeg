import io

from apps.audit_engine.services.parsers.base import BaseParser, ParseResult


class ExcelParser(BaseParser):
    """Parse Excel files (.xlsx, .xls, .xlsm) using openpyxl or pandas."""

    @property
    def supported_extensions(self):
        return [".xlsx", ".xls", ".xlsm"]

    def parse(self, file_path: str) -> ParseResult:
        try:
            import pandas as pd

            xl = pd.ExcelFile(file_path)
            sheet_names = xl.sheet_names

            all_text_parts = []
            total_row_count = 0
            all_column_names = []
            sheets_meta = {}

            for sheet in sheet_names:
                df = xl.parse(sheet)
                rows = len(df)
                cols = list(df.columns.astype(str))
                total_row_count += rows
                if not all_column_names:
                    all_column_names = cols
                sheets_meta[sheet] = {"rows": rows, "columns": cols}
                # Convert sheet to CSV-like text
                text_buf = io.StringIO()
                df.to_csv(text_buf, index=False)
                all_text_parts.append(f"=== Sheet: {sheet} ===\n{text_buf.getvalue()}")

            full_text = "\n\n".join(all_text_parts)

            return ParseResult(
                text=full_text,
                page_count=len(sheet_names),
                row_count=total_row_count,
                column_names=all_column_names,
                sheet_names=sheet_names,
                metadata={"sheets": sheets_meta},
                success=True,
            )
        except ImportError:
            return ParseResult(
                success=False,
                error="pandas and/or openpyxl is not installed. Run: pip install pandas openpyxl",
            )
        except Exception as exc:
            return ParseResult(success=False, error=str(exc))
