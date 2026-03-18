"""
Universal Financial Document Ingestion Engine.

Pipeline:
  Upload file
  -> validate size/path
  -> detect MIME type
  -> use ordered extraction strategies for supported formats
  -> normalize into a unified schema
  -> return IngestionResult

ZIP archives keep using the dedicated archive parser because they are batch
containers rather than single-document extraction targets.
"""

from __future__ import annotations

import logging
import mimetypes
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .extraction_manager import ExtractionManager
from .normalization import NormalizationService
from .parsers.base_parser import ParseResult

logger = logging.getLogger("finai")


EXTENSION_TO_MIME: dict[str, str] = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
    ".bmp": "image/bmp",
    ".webp": "image/webp",
    ".zip": "application/zip",
    ".json": "application/json",
    ".jsonl": "application/json",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".txt": "text/plain",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xlsm": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

MAX_FILE_SIZE = 50 * 1024 * 1024
MAX_ZIP_FILE_SIZE = 200 * 1024 * 1024
ALLOWED_MIMES = set(EXTENSION_TO_MIME.values()) | {"application/x-jsonlines"}


@dataclass
class IngestionResult:
    """Unified output from the document engine."""

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
            "raw_text": self.raw_text[:5000],
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
    """Universal document ingestion engine."""

    def __init__(self, use_ai: bool = True):
        self.use_ai = use_ai
        self.normalizer = NormalizationService()
        self.extraction_manager = ExtractionManager()

    def ingest(self, file_path: str, use_ai: bool = None) -> IngestionResult:
        t_start = time.monotonic()
        use_ai = self.use_ai if use_ai is None else use_ai

        result = IngestionResult(
            file_path=file_path,
            file_name=Path(file_path).name,
        )

        if not self._validate_file(file_path, result):
            return self._finalise(result, t_start)

        mime = self._detect_mime(file_path)
        result.mime_type = mime
        if mime not in ALLOWED_MIMES:
            result.fatal_error = f"Unsupported file type: {mime}"
            return self._finalise(result, t_start)

        parse_result = self._parse_file(file_path=file_path, mime=mime, use_ai=use_ai)
        result.raw_text = parse_result.raw_text
        result.structured = parse_result.structured
        result.page_texts = parse_result.page_texts
        result.metadata = parse_result.metadata
        result.errors = parse_result.errors
        result.extraction_method = parse_result.extraction_method

        if not parse_result.success:
            result.fatal_error = parse_result.fatal_error
            return self._finalise(result, t_start)

        result.normalized = self._normalize(parse_result, result.file_name)
        result.document_type = result.normalized.get("document_type", "other")
        result.success = True
        return self._finalise(result, t_start)

    def _validate_file(self, file_path: str, result: IngestionResult) -> bool:
        if not os.path.exists(file_path):
            result.fatal_error = f"File not found: {file_path}"
            return False
        if not os.path.isfile(file_path):
            result.fatal_error = f"Path is not a file: {file_path}"
            return False

        size = os.path.getsize(file_path)
        max_size = MAX_ZIP_FILE_SIZE if file_path.lower().endswith(".zip") else MAX_FILE_SIZE
        if size > max_size:
            result.fatal_error = f"File size {size:,} bytes exceeds limit {max_size:,} bytes."
            return False
        if size == 0:
            result.fatal_error = "File is empty."
            return False
        return True

    def _detect_mime(self, file_path: str) -> str:
        try:
            import magic

            detected = magic.from_file(file_path, mime=True)
            if detected and detected != "application/octet-stream":
                return self._normalise_mime(detected)
        except (ImportError, Exception):
            pass

        guessed, _ = mimetypes.guess_type(file_path)
        if guessed:
            return self._normalise_mime(guessed)

        return EXTENSION_TO_MIME.get(Path(file_path).suffix.lower(), "application/octet-stream")

    @staticmethod
    def _normalise_mime(mime: str) -> str:
        aliases = {
            "application/x-zip-compressed": "application/zip",
            "application/x-zip": "application/zip",
            "application/x-jsonlines": "application/x-jsonlines",
            "image/jpg": "image/jpeg",
            "text/x-csv": "text/csv",
        }
        return aliases.get(mime, mime)

    def _parse_file(self, *, file_path: str, mime: str, use_ai: bool) -> ParseResult:
        if mime == "application/zip":
            parser = self._get_parser(mime)
            if parser is None:
                return ParseResult(success=False, fatal_error=f"No parser available for MIME type: {mime}")
            logger.info(
                "[DocumentEngine] Ingesting %s | mime=%s | parser=%s",
                Path(file_path).name,
                mime,
                type(parser).__name__,
            )
            try:
                return parser.parse(file_path, use_ai=use_ai)
            except Exception as exc:
                logger.exception("[DocumentEngine] Parser error for %s", file_path)
                return ParseResult(success=False, fatal_error=f"Parser raised an unexpected error: {exc}")

        logger.info(
            "[DocumentEngine] Ingesting %s | mime=%s | manager=%s",
            Path(file_path).name,
            mime,
            type(self.extraction_manager).__name__,
        )
        return self.extraction_manager.extract(
            file_path=file_path,
            mime_type=mime,
            use_ai=use_ai,
        )

    def _get_parser(self, mime: str):
        from .parsers.csv_parser import CSVParser
        from .parsers.excel_parser import ExcelParser
        from .parsers.image_parser import ImageParser
        from .parsers.json_parser import JSONParser
        from .parsers.pdf_parser import PDFParser
        from .parsers.zip_parser import ZIPParser

        parser_map = {
            "application/pdf": PDFParser,
            "image/png": ImageParser,
            "image/jpeg": ImageParser,
            "image/tiff": ImageParser,
            "image/bmp": ImageParser,
            "image/webp": ImageParser,
            "application/zip": ZIPParser,
            "application/json": JSONParser,
            "application/x-jsonlines": JSONParser,
            "text/csv": CSVParser,
            "text/tab-separated-values": CSVParser,
            "text/plain": CSVParser,
            "application/vnd.ms-excel": ExcelParser,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ExcelParser,
        }
        parser_class = parser_map.get(mime)
        return parser_class() if parser_class else None

    def _normalize(self, parse_result: ParseResult, source_file: str) -> dict:
        structured = parse_result.structured or {}
        primary_record = structured.get("records", [structured])[0] if structured.get("records") else structured

        payload = {
            **structured,
            **primary_record,
            "raw_text": parse_result.raw_text[:10000],
            "source_file": source_file,
            "extraction_method": parse_result.extraction_method,
            "metadata": parse_result.metadata,
        }
        normalized = self.normalizer.normalize(payload).to_serializable_dict()
        normalized["document_number"] = (
            normalized.get("invoice_number")
            or self._coerce_str(primary_record.get("document_number") or primary_record.get("reference"))
        )
        normalized["date"] = normalized.get("invoice_date")
        normalized["tax_amount"] = normalized.get("vat_amount")
        normalized["metadata"] = parse_result.metadata
        normalized["source_file"] = source_file
        return normalized

    @staticmethod
    def _coerce_str(value, default: str = "") -> str:
        if value is None:
            return default
        return str(value).strip() or default

    @staticmethod
    def _finalise(result: IngestionResult, t_start: float) -> IngestionResult:
        result.processing_time_ms = int((time.monotonic() - t_start) * 1000)
        if result.fatal_error:
            logger.error("[DocumentEngine] FAILED %s: %s", result.file_name, result.fatal_error)
        else:
            logger.info(
                "[DocumentEngine] SUCCESS %s | method=%s | %dms",
                result.file_name,
                result.extraction_method,
                result.processing_time_ms,
            )
        return result
