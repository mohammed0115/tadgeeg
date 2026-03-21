"""
ZIP Parser

Pipeline:
  1. Validate ZIP integrity and check for path-traversal attacks
  2. Extract to a secure temp directory
  3. For each contained file, dispatch to the appropriate parser
     via the document engine
  4. Aggregate all individual parse results
  5. Clean up temp directory

Security: path-traversal check is mandatory before extraction.
"""

import logging
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Optional

from .base_parser import DocumentParser, ParseResult
from core.services.zip_validator import validate_zip_bomb, ZipValidationError

logger = logging.getLogger("finai")

SUPPORTED_EXTENSIONS = (".zip",)
SUPPORTED_MIMES = ("application/zip", "application/x-zip-compressed")

# Hard limits to prevent resource exhaustion
MAX_UNCOMPRESSED_BYTES = 500 * 1024 * 1024   # 500 MB
MAX_FILE_COUNT = 500
MAX_NESTING_DEPTH = 2                         # ZIP-within-ZIP max depth


class ZIPParser(DocumentParser):
    """
    Parser for ZIP archives containing multiple financial documents.

    Each contained file is dispatched to the correct parser.
    Results are aggregated into a single ParseResult.
    """

    supported_extensions = SUPPORTED_EXTENSIONS
    supported_mimes = SUPPORTED_MIMES

    def parse(
        self,
        file_path: str,
        use_ai: bool = True,
        _depth: int = 0,
        **kwargs,
    ) -> ParseResult:
        result = ParseResult(extraction_method="zip")

        if _depth > MAX_NESTING_DEPTH:
            result.fatal_error = "Maximum ZIP nesting depth exceeded."
            return result

        # ── Security: validate archive ────────────────────────────────────────
        if not self._is_safe_zip(file_path, result):
            result.fatal_error = "ZIP archive failed security validation."
            return result

        # ── Extract to temp dir ───────────────────────────────────────────────
        tmp_dir = tempfile.mkdtemp(prefix="finai_zip_")
        try:
            with zipfile.ZipFile(file_path, "r") as zf:
                zf.extractall(tmp_dir)

            # ── Process each file ─────────────────────────────────────────────
            child_results = self._process_directory(
                tmp_dir, use_ai=use_ai, depth=_depth
            )
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        # ── Aggregate ─────────────────────────────────────────────────────────
        all_texts: list[str] = []
        all_records: list[dict] = []
        all_errors: list[str] = []
        success_count = 0

        for filename, child in child_results.items():
            if child.success:
                success_count += 1
                if child.raw_text:
                    all_texts.append(f"=== {filename} ===\n{child.raw_text}")
                records = child.structured.get("records", [])
                if not records and child.structured:
                    records = [child.structured]
                for r in records:
                    r["_source_file"] = filename
                    all_records.append(r)
            else:
                all_errors.append(f"{filename}: {child.fatal_error or 'parse failed'}")

        result.raw_text = "\n\n".join(all_texts)
        result.structured = {
            "records": all_records,
            "record_count": len(all_records),
            "file_results": {
                fn: {"success": r.success, "method": r.extraction_method}
                for fn, r in child_results.items()
            },
        }
        result.errors = all_errors
        result.metadata["total_files"] = len(child_results)
        result.metadata["success_count"] = success_count
        result.success = success_count > 0
        if not result.success:
            result.fatal_error = "No files in ZIP could be parsed."
        return result

    # ── Security ──────────────────────────────────────────────────────────────

    def _is_safe_zip(self, file_path: str, result: ParseResult) -> bool:
        """Validate ZIP using comprehensive bomb detection."""
        try:
            validate_zip_bomb(
                file_path,
                max_file_size=MAX_UNCOMPRESSED_BYTES,
                max_total_size=MAX_UNCOMPRESSED_BYTES,
                max_files=MAX_FILE_COUNT,
            )
            return True
        except ZipValidationError as exc:
            result.add_error(str(exc))
            return False
        except zipfile.BadZipFile as exc:
            result.add_error(f"Bad ZIP file: {exc}")
            return False
        except Exception as exc:
            result.add_error(f"ZIP validation error: {exc}")
            return False

    # ── Directory processing ──────────────────────────────────────────────────

    def _process_directory(
        self, directory: str, use_ai: bool, depth: int
    ) -> dict:
        """Walk extracted directory and parse each file."""
        # Import here to avoid circular imports; document_engine imports parsers.
        from core.services.document_engine import DocumentEngine

        engine = DocumentEngine()
        results: dict[str, ParseResult] = {}

        for root, _dirs, files in os.walk(directory):
            for filename in files:
                full_path = os.path.join(root, filename)
                relative_name = os.path.relpath(full_path, directory)

                try:
                    if filename.lower().endswith(".zip"):
                        # Recurse into nested ZIP
                        child_result = self.parse(
                            full_path, use_ai=use_ai, _depth=depth + 1
                        )
                    else:
                        child_result = engine.ingest(full_path, use_ai=use_ai)
                    results[relative_name] = child_result
                except Exception as exc:
                    err_result = ParseResult()
                    err_result.fatal_error = str(exc)
                    results[relative_name] = err_result
                    logger.error(
                        "[ZIPParser] Error processing %s: %s", relative_name, exc
                    )

        return results
