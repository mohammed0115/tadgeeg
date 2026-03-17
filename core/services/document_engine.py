"""
Universal Financial Document Ingestion Engine

Entry point for ALL document processing in FinAI.

Pipeline:
  Upload File
  → Detect File Type (MIME + magic bytes, NOT just extension)
  → Route to Parser
  → Extract Raw Text / Structured Data
  → AI-Assisted Field Extraction
  → Normalize to Unified Schema
  → Return IngestionResult

Supports: PDF, PNG, JPG, JPEG, ZIP, JSON, CSV, XLS, XLSX

Design decisions:
  - MIME detection uses python-magic (libmagic) with extension fallback
  - Each parser is fully independent (clean interfaces)
  - Failure of any step degrades gracefully; the engine never raises
  - All processing decisions are logged with structured context
"""

import logging
import mimetypes
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .parsers.base_parser import ParseResult

logger = logging.getLogger("finai")


# ── Supported MIME → parser mapping ──────────────────────────────────────────

EXTENSION_TO_MIME: dict[str, str] = {
    ".pdf":  "application/pdf",
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tiff": "image/tiff",
    ".tif":  "image/tiff",
    ".bmp":  "image/bmp",
    ".webp": "image/webp",
    ".zip":  "application/zip",
    ".json": "application/json",
    ".jsonl":"application/json",
    ".csv":  "text/csv",
    ".tsv":  "text/tab-separated-values",
    ".xls":  "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xlsm": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

# File size limits (bytes)
MAX_FILE_SIZE = 50 * 1024 * 1024        # 50 MB global
MAX_ZIP_FILE_SIZE = 200 * 1024 * 1024   # 200 MB for ZIP

# Allowed MIME categories
ALLOWED_MIMES = set(EXTENSION_TO_MIME.values())


@dataclass
class IngestionResult:
    """
    Unified output from the document engine.

    This is the contract between the ingestion layer and downstream
    financial AI / audit engines.
    """

    success: bool = False
    file_path: str = ""
    file_name: str = ""
    mime_type: str = ""
    document_type: str = "other"
    raw_text: str = ""
    structured: dict = field(default_factory=dict)
    normalized: dict = field(default_factory=dict)
    page_texts: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    fatal_error: Optional[str] = None
    extraction_method: str = "unknown"
    processing_time_ms: int = 0

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "file_name": self.file_name,
            "mime_type": self.mime_type,
            "document_type": self.document_type,
            "raw_text": self.raw_text[:5000],   # Truncate for storage
            "structured": self.structured,
            "normalized": self.normalized,
            "page_count": len(self.page_texts),
            "metadata": self.metadata,
            "errors": self.errors,
            "fatal_error": self.fatal_error,
            "extraction_method": self.extraction_method,
            "processing_time_ms": self.processing_time_ms,
        }


class DocumentEngine:
    """
    Universal document ingestion engine.

    Usage:
        engine = DocumentEngine()
        result = engine.ingest("/path/to/file.pdf")
        if result.success:
            print(result.normalized)
    """

    def __init__(self, use_ai: bool = True):
        self.use_ai = use_ai

    def ingest(self, file_path: str, use_ai: bool = None) -> IngestionResult:
        """
        Ingest a document file through the full parsing pipeline.

        Args:
            file_path: Absolute path to the uploaded file.
            use_ai:    Override instance-level use_ai flag.

        Returns:
            IngestionResult (never raises).
        """
        t_start = time.monotonic()
        _use_ai = use_ai if use_ai is not None else self.use_ai

        result = IngestionResult(
            file_path=file_path,
            file_name=Path(file_path).name,
        )

        # ── 1. Security: validate file ────────────────────────────────────────
        if not self._validate_file(file_path, result):
            return self._finalise(result, t_start)

        # ── 2a. Compute file hash (before any extraction for idempotency) ───────
        result.metadata["file_hash"] = self._compute_hash(file_path)

        # ── 2. Detect MIME type ───────────────────────────────────────────────
        mime = self._detect_mime(file_path, result)
        result.mime_type = mime

        if mime not in ALLOWED_MIMES:
            result.fatal_error = f"Unsupported file type: {mime}"
            return self._finalise(result, t_start)

        # ── 3. Route to parser ────────────────────────────────────────────────
        parser = self._get_parser(mime)
        if parser is None:
            result.fatal_error = f"No parser available for MIME type: {mime}"
            return self._finalise(result, t_start)

        logger.info(
            "[DocumentEngine] Ingesting %s | mime=%s | parser=%s",
            result.file_name, mime, type(parser).__name__,
        )

        # ── 4. Parse ──────────────────────────────────────────────────────────
        try:
            parse_result: ParseResult = parser.parse(file_path, use_ai=_use_ai)
        except Exception as exc:
            result.fatal_error = f"Parser raised an unexpected error: {exc}"
            logger.exception("[DocumentEngine] Parser error for %s", file_path)
            return self._finalise(result, t_start)

        # ── 5. Copy parse result into ingestion result ────────────────────────
        result.raw_text = parse_result.raw_text
        result.structured = parse_result.structured
        result.page_texts = parse_result.page_texts
        result.metadata = parse_result.metadata
        result.errors = parse_result.errors
        result.extraction_method = parse_result.extraction_method

        if not parse_result.success:
            result.fatal_error = parse_result.fatal_error
            return self._finalise(result, t_start)

        # ── 6. Normalise to unified schema ────────────────────────────────────
        result.normalized = self._normalize(parse_result, result.file_name)
        result.document_type = result.normalized.get("document_type", "other")

        result.success = True
        return self._finalise(result, t_start)

    # ── Validation ────────────────────────────────────────────────────────────

    def _validate_file(self, file_path: str, result: IngestionResult) -> bool:
        """Validate existence, permissions, and size."""
        if not os.path.exists(file_path):
            result.fatal_error = f"File not found: {file_path}"
            return False

        if not os.path.isfile(file_path):
            result.fatal_error = f"Path is not a file: {file_path}"
            return False

        size = os.path.getsize(file_path)
        max_size = MAX_ZIP_FILE_SIZE if file_path.lower().endswith(".zip") else MAX_FILE_SIZE
        if size > max_size:
            result.fatal_error = (
                f"File size {size:,} bytes exceeds limit {max_size:,} bytes."
            )
            return False

        if size == 0:
            result.fatal_error = "File is empty."
            return False

        return True

    # ── MIME detection ────────────────────────────────────────────────────────

    def _detect_mime(self, file_path: str, result: IngestionResult) -> str:
        """
        Detect MIME type using multiple strategies:
        1. python-magic (magic bytes) — most reliable
        2. mimetypes stdlib (extension-based) — fallback
        3. Manual extension lookup — last resort
        """
        # Strategy 1: libmagic
        try:
            import magic
            mime = magic.from_file(file_path, mime=True)
            if mime and mime != "application/octet-stream":
                return self._normalise_mime(mime)
        except (ImportError, Exception):
            pass

        # Strategy 2: stdlib mimetypes
        mime, _ = mimetypes.guess_type(file_path)
        if mime:
            return self._normalise_mime(mime)

        # Strategy 3: manual extension map
        ext = Path(file_path).suffix.lower()
        return EXTENSION_TO_MIME.get(ext, "application/octet-stream")

    def _normalise_mime(self, mime: str) -> str:
        """Normalise MIME aliases to canonical forms we recognise."""
        aliases: dict[str, str] = {
            "application/x-zip-compressed": "application/zip",
            "application/x-zip": "application/zip",
            "image/jpg": "image/jpeg",
            "text/x-csv": "text/csv",
        }
        return aliases.get(mime, mime)

    # ── Parser routing ────────────────────────────────────────────────────────

    def _get_parser(self, mime: str):
        """Return the correct parser instance for the given MIME type."""
        from .parsers.pdf_parser import PDFParser
        from .parsers.image_parser import ImageParser
        from .parsers.zip_parser import ZIPParser
        from .parsers.json_parser import JSONParser
        from .parsers.csv_parser import CSVParser
        from .parsers.excel_parser import ExcelParser

        parser_map = {
            "application/pdf": PDFParser,
            "image/png":   ImageParser,
            "image/jpeg":  ImageParser,
            "image/tiff":  ImageParser,
            "image/bmp":   ImageParser,
            "image/webp":  ImageParser,
            "application/zip": ZIPParser,
            "application/json": JSONParser,
            "text/csv": CSVParser,
            "text/tab-separated-values": CSVParser,
            "text/plain": CSVParser,
            "application/vnd.ms-excel": ExcelParser,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ExcelParser,
        }

        parser_class = parser_map.get(mime)
        return parser_class() if parser_class else None

    # ── Normalisation ─────────────────────────────────────────────────────────

    def _normalize(self, parse_result: ParseResult, source_file: str) -> dict:
        """
        Merge structured fields from parse_result into the unified schema.

        Priority: structured (AI/parser) > raw text regex fallback
        """
        s = parse_result.structured or {}

        # If the parser returned a records list (CSV/Excel/JSON), use first record
        if "records" in s and s["records"]:
            primary = s["records"][0]
        else:
            primary = s

        normalized = {
            "document_type":   self._coerce_str(primary.get("document_type") or s.get("document_type"), "other"),
            "vendor_name":     self._coerce_str(primary.get("vendor_name") or primary.get("vendor")),
            "document_number": self._coerce_str(primary.get("document_number") or primary.get("reference") or primary.get("invoice_number")),
            "date":            self._coerce_date(primary.get("date") or primary.get("invoice_date")),
            "due_date":        self._coerce_date(primary.get("due_date")),
            "currency":        self._coerce_str(primary.get("currency"), "SAR"),
            "total_amount":    self._coerce_decimal(primary.get("total_amount") or primary.get("amount")),
            "tax_amount":      self._coerce_decimal(primary.get("tax_amount") or primary.get("vat")),
            "subtotal":        self._coerce_decimal(primary.get("subtotal")),
            "vat_rate":        self._coerce_decimal(primary.get("vat_rate"), 15.0),
            "line_items":      primary.get("line_items", []),
            "raw_text":        parse_result.raw_text[:10000],
            "source_file":     source_file,
            "extraction_method": parse_result.extraction_method,
            "metadata":        parse_result.metadata,
        }

        # Copy any additional fields the AI returned
        extra_keys = {
            "vendor_vat_number", "vendor_name_ar", "language",
            "has_qr_code", "is_handwritten", "confidence",
            "payment_terms", "notes", "discount",
        }
        for key in extra_keys:
            val = primary.get(key) or s.get(key)
            if val is not None:
                normalized[key] = val

        return normalized

    # ── Type coercions ────────────────────────────────────────────────────────

    @staticmethod
    def _coerce_str(value, default: str = "") -> str:
        if value is None:
            return default
        return str(value).strip() or default

    @staticmethod
    def _coerce_decimal(value, default: float = 0.0) -> float:
        if value is None:
            return default
        try:
            cleaned = str(value).replace(",", "").strip()
            return float(cleaned)
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _coerce_date(value) -> Optional[str]:
        if not value:
            return None
        import re
        s = str(value).strip()
        # Already ISO
        if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
            return s
        # Try common formats
        from datetime import datetime
        for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d",
                    "%d %b %Y", "%d %B %Y", "%B %d, %Y"):
            try:
                return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
        return s  # Return as-is if unparseable

    # ── Utility ───────────────────────────────────────────────────────────────

    @staticmethod
    def _compute_hash(file_path: str) -> str:
        """Compute SHA-256 of the file in 64 KB chunks (memory-safe)."""
        import hashlib
        sha = hashlib.sha256()
        try:
            with open(file_path, "rb") as fh:
                for chunk in iter(lambda: fh.read(65536), b""):
                    sha.update(chunk)
            return sha.hexdigest()
        except OSError:
            return ""

    def _finalise(self, result: IngestionResult, t_start: float) -> IngestionResult:
        result.processing_time_ms = int((time.monotonic() - t_start) * 1000)
        if result.fatal_error:
            logger.error(
                "[DocumentEngine] FAILED %s: %s", result.file_name, result.fatal_error
            )
        else:
            logger.info(
                "[DocumentEngine] SUCCESS %s | method=%s | %dms",
                result.file_name, result.extraction_method, result.processing_time_ms,
            )
        return result
