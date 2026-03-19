"""OCR Service — thin wrapper delegating to core services."""
from __future__ import annotations
import logging
import os

logger = logging.getLogger(__name__)


class OCRService:
    """Delegates text extraction to the canonical core OCR and parser stack."""

    def extract_from_file(self, file_path: str, language_hint: str = "auto") -> str:
        """Route to extract_pdf or extract_image based on extension."""
        if not file_path or not os.path.exists(file_path):
            logger.warning("OCRService: file not found: %s", file_path)
            return ""

        ext = os.path.splitext(file_path)[1].lstrip(".").lower()
        if ext == "pdf":
            return self.extract_pdf(file_path)
        else:
            return self.extract_image(file_path)

    def extract_pdf(self, file_path: str) -> str:
        try:
            from core.services.parsers.pdf_parser import PdfParser
            parser = PdfParser()
            result = parser.parse(file_path)
            return result.text if hasattr(result, "text") else str(result)
        except Exception as exc:
            logger.warning("PDF extraction via core failed for %s: %s", file_path, exc)
            return self._fallback_pdf(file_path)

    def _fallback_pdf(self, file_path: str) -> str:
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(file_path)
            return "\n".join(page.get_text() for page in doc)
        except Exception as exc:
            logger.warning("PDF fallback failed: %s", exc)
            return ""

    def extract_image(self, file_path: str) -> str:
        try:
            from core.services.parsers.image_parser import ImageParser
            parser = ImageParser()
            result = parser.parse(file_path)
            return result.text if hasattr(result, "text") else str(result)
        except Exception as exc:
            logger.warning("Image extraction via core failed for %s: %s", file_path, exc)
            return self._fallback_image(file_path)

    def _fallback_image(self, file_path: str) -> str:
        try:
            import pytesseract
            from PIL import Image
            return pytesseract.image_to_string(Image.open(file_path), lang="ara+eng")
        except Exception as exc:
            logger.warning("Image fallback failed: %s", exc)
            return ""
