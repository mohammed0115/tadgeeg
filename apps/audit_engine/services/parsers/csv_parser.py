import csv
import os

from apps.audit_engine.services.parsers.base import BaseParser, ParseResult


class CSVParser(BaseParser):
    """Parse CSV and TSV files."""

    @property
    def supported_extensions(self):
        return [".csv", ".tsv"]

    def parse(self, file_path: str) -> ParseResult:
        try:
            ext = os.path.splitext(file_path)[-1].lower()
            delimiter = "\t" if ext == ".tsv" else ","

            rows = []
            column_names = []

            with open(file_path, newline="", encoding="utf-8-sig", errors="replace") as fh:
                reader = csv.reader(fh, delimiter=delimiter)
                for idx, row in enumerate(reader):
                    if idx == 0:
                        column_names = row
                    rows.append(delimiter.join(row))

            # row_count excludes the header row
            data_row_count = max(0, len(rows) - 1)
            full_text = "\n".join(rows)

            return ParseResult(
                text=full_text,
                page_count=1,
                row_count=data_row_count,
                column_names=column_names,
                metadata={
                    "delimiter": delimiter,
                    "total_lines": len(rows),
                    "encoding": "utf-8-sig",
                },
                success=True,
            )
        except Exception as exc:
            return ParseResult(success=False, error=str(exc))
