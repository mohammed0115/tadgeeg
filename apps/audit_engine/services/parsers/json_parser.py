import json
import os

from apps.audit_engine.services.parsers.base import BaseParser, ParseResult


class JSONParser(BaseParser):
    """Parse JSON and JSONL files."""

    @property
    def supported_extensions(self):
        return [".json", ".jsonl"]

    def parse(self, file_path: str) -> ParseResult:
        try:
            ext = os.path.splitext(file_path)[-1].lower()

            with open(file_path, encoding="utf-8", errors="replace") as fh:
                content = fh.read()

            if ext == ".jsonl":
                records = []
                for line in content.splitlines():
                    line = line.strip()
                    if line:
                        try:
                            records.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
                data = records
            else:
                data = json.loads(content)

            if isinstance(data, dict):
                top_level_keys = list(data.keys())
                record_count = 1
            elif isinstance(data, list):
                top_level_keys = []
                record_count = len(data)
                # Try to extract keys from first record if it's a dict
                if data and isinstance(data[0], dict):
                    top_level_keys = list(data[0].keys())
            else:
                top_level_keys = []
                record_count = 1

            text_repr = json.dumps(data, indent=2, ensure_ascii=False)

            return ParseResult(
                text=text_repr,
                page_count=1,
                row_count=record_count,
                metadata={
                    "top_level_keys": top_level_keys,
                    "record_count": record_count,
                    "format": ext.lstrip("."),
                },
                success=True,
            )
        except json.JSONDecodeError as exc:
            return ParseResult(
                success=False,
                error=f"Invalid JSON: {exc}",
            )
        except Exception as exc:
            return ParseResult(success=False, error=str(exc))
