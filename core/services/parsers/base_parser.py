"""
Base Document Parser Interface

All parsers must implement this contract.
"""

import abc
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("finai")


@dataclass
class ParseResult:
    """
    Unified result returned by every parser.

    Attributes:
        success:        Whether extraction produced usable data.
        raw_text:       Full extracted text (OCR or parsed).
        structured:     Dict of key financial fields if available.
        page_texts:     Per-page text for multi-page documents.
        metadata:       Source-specific metadata (page count, sheet names, …).
        errors:         Non-fatal error messages collected during parsing.
        fatal_error:    Terminal error message if success is False.
        extraction_method: Which strategy succeeded first.
    """

    success: bool = False
    raw_text: str = ""
    structured: dict = field(default_factory=dict)
    page_texts: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    fatal_error: Optional[str] = None
    extraction_method: str = "unknown"

    def add_error(self, msg: str) -> None:
        logger.warning("[Parser] %s", msg)
        self.errors.append(msg)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "raw_text": self.raw_text,
            "structured": self.structured,
            "page_texts": self.page_texts,
            "metadata": self.metadata,
            "errors": self.errors,
            "fatal_error": self.fatal_error,
            "extraction_method": self.extraction_method,
        }


class DocumentParser(abc.ABC):
    """
    Abstract base class for all document parsers.

    Subclasses must implement parse().
    """

    #: File extensions this parser handles (lowercase, with dot).
    supported_extensions: tuple[str, ...] = ()

    #: MIME types this parser handles.
    supported_mimes: tuple[str, ...] = ()

    @abc.abstractmethod
    def parse(self, file_path: str, **kwargs) -> ParseResult:
        """
        Parse a document and return a ParseResult.

        Args:
            file_path: Absolute path to the file on disk.
            **kwargs:  Parser-specific options.

        Returns:
            ParseResult instance.
        """

    def _safe_read_bytes(self, file_path: str) -> Optional[bytes]:
        """Read raw bytes safely, returning None on failure."""
        try:
            with open(file_path, "rb") as fh:
                return fh.read()
        except OSError as exc:
            logger.error("[Parser] Cannot read file %s: %s", file_path, exc)
            return None
