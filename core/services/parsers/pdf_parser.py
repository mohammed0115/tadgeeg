"""
PDF Parser

Pipeline:
  1. Try direct text extraction (pdfplumber → PyMuPDF → PyPDF fallback)
  2. If text layer is absent / sparse → convert pages to images → OCR each page
  3. Concatenate per-page texts
  4. Optionally pass full text to OpenAI for structured extraction

Multiple fallback libraries guarantee maximum read coverage.
"""

import logging
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Optional

from .base_parser import DocumentParser, ParseResult

logger = logging.getLogger("finai")

SUPPORTED_EXTENSIONS = (".pdf",)
SUPPORTED_MIMES = ("application/pdf",)

# Minimum characters per page to consider a text layer "present"
TEXT_LAYER_MIN_CHARS = 30


class PDFParser(DocumentParser):
    """
    Parser for PDF documents.

    Attempts text extraction first; falls back to image-based OCR for
    scanned PDFs that have no embedded text layer.
    """

    supported_extensions = SUPPORTED_EXTENSIONS
    supported_mimes = SUPPORTED_MIMES

    def parse(self, file_path: str, use_ai: bool = True, **kwargs) -> ParseResult:
        result = ParseResult(extraction_method="pdf_text")
        page_texts: list[str] = []

        # ── 1. Direct text extraction ─────────────────────────────────────────
        page_texts = self._extract_text_layer(file_path, result)

        total_chars = sum(len(t) for t in page_texts)
        has_text_layer = total_chars >= TEXT_LAYER_MIN_CHARS * max(len(page_texts), 1)

        if has_text_layer:
            result.raw_text = "\n\n".join(page_texts).strip()
            result.page_texts = page_texts
            result.metadata["extraction_method"] = "text_layer"
            logger.info(
                "[PDFParser] Text layer found: %d chars across %d pages",
                total_chars,
                len(page_texts),
            )
        else:
            # ── 2. Image-based OCR ────────────────────────────────────────────
            logger.info("[PDFParser] No text layer — switching to OCR pipeline")
            page_texts = self._ocr_pages(file_path, result)
            result.raw_text = "\n\n".join(page_texts).strip()
            result.page_texts = page_texts
            result.extraction_method = "pdf_ocr"

        result.metadata["page_count"] = len(page_texts)
        result.metadata["total_chars"] = len(result.raw_text)

        # ── 3. AI Structured extraction (with regex fallback) ────────────────
        if use_ai and result.raw_text:
            t_ai = time.monotonic()
            try:
                from core.services.ai.openai_extractor import extract_with_text

                ai_structured = extract_with_text(result.raw_text)
                if ai_structured:
                    result.structured = ai_structured
                    result.extraction_method = "pdf_ai_text"
                    result.metadata["ai_enhanced"] = True
                    logger.info(
                        "[PDFParser] OpenAI extraction OK in %.0fms",
                        (time.monotonic() - t_ai) * 1000,
                    )
            except Exception as exc:
                logger.warning(
                    "[PDFParser] OpenAI extraction failed in %.0fms (%s) — falling back to regex",
                    (time.monotonic() - t_ai) * 1000, exc,
                )
                result.add_error(f"OpenAI text extraction failed (regex fallback used): {exc}")
                # Regex fallback: extract key financial fields from raw text
                result.structured = _regex_extract(result.raw_text)
                if result.structured:
                    result.extraction_method = "pdf_regex_fallback"
                    result.metadata["ai_enhanced"] = False

        result.success = bool(result.raw_text or result.structured)
        if not result.success:
            result.fatal_error = "No content could be extracted from this PDF."
        return result

    # ── Text extraction helpers ──────────────────────────────────────────────

    def _extract_text_layer(self, file_path: str, result: ParseResult) -> list[str]:
        """Try pdfplumber → PyMuPDF → PyPDF in order."""
        texts = self._try_pdfplumber(file_path, result)
        if not texts:
            texts = self._try_pymupdf(file_path, result)
        if not texts:
            texts = self._try_pypdf(file_path, result)
        return texts

    def _try_pdfplumber(self, file_path: str, result: ParseResult) -> list[str]:
        try:
            import pdfplumber

            texts = []
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    text = page.extract_text() or ""
                    texts.append(text)
            return texts
        except ImportError:
            result.add_error("pdfplumber not installed; skipping.")
        except Exception as exc:
            result.add_error(f"pdfplumber failed: {exc}")
        return []

    def _try_pymupdf(self, file_path: str, result: ParseResult) -> list[str]:
        try:
            import fitz  # PyMuPDF

            texts = []
            with fitz.open(file_path) as doc:
                for page in doc:
                    texts.append(page.get_text("text"))
            return texts
        except ImportError:
            result.add_error("PyMuPDF not installed; skipping.")
        except Exception as exc:
            result.add_error(f"PyMuPDF text extraction failed: {exc}")
        return []

    def _try_pypdf(self, file_path: str, result: ParseResult) -> list[str]:
        try:
            from PyPDF2 import PdfReader

            texts = []
            reader = PdfReader(file_path)
            for page in reader.pages:
                texts.append(page.extract_text() or "")
            return texts
        except ImportError:
            result.add_error("PyPDF2 not installed; skipping.")
        except Exception as exc:
            result.add_error(f"PyPDF2 extraction failed: {exc}")
        return []

    # ── OCR helpers ───────────────────────────────────────────────────────────

    def _ocr_pages(self, file_path: str, result: ParseResult) -> list[str]:
        """Convert each PDF page to an image, then OCR it."""
        try:
            from core.services.ocr_service import pdf_to_images, extract_text_tesseract

            image_paths = pdf_to_images(file_path)
        except Exception as exc:
            result.add_error(f"PDF→image conversion failed: {exc}")
            return []

        page_texts: list[str] = []
        for img_path in image_paths:
            try:
                ocr_result = extract_text_tesseract(img_path)
                page_texts.append(ocr_result.get("text", ""))
            except Exception as exc:
                result.add_error(f"OCR failed for page image {img_path}: {exc}")
                page_texts.append("")
            finally:
                # Clean up temp page images
                try:
                    os.unlink(img_path)
                except OSError:
                    pass

        return page_texts


# ── Module-level regex fallback ───────────────────────────────────────────────

def _regex_extract(text: str) -> dict:
    """
    Last-resort structured extraction using regex patterns.
    Covers the most critical financial fields for GCC invoices.
    Returns {} if nothing useful is found.
    """
    if not text:
        return {}

    result: dict = {}

    # Saudi VAT number (15 digits, starts and ends with 3)
    vat_match = re.search(r"\b3\d{13}3\b", text)
    if vat_match:
        result["vendor_vat_number"] = vat_match.group()

    # Invoice number (common Arabic/English labels)
    inv_match = re.search(
        r"(?:invoice\s*(?:no|number|#|رقم الفاتورة)[:\s#]*)"
        r"([\w\-\/]+)",
        text, re.IGNORECASE,
    )
    if inv_match:
        result["invoice_number"] = inv_match.group(1).strip()

    # Date patterns (YYYY-MM-DD, DD/MM/YYYY, DD-MM-YYYY)
    date_match = re.search(
        r"\b(\d{4}-\d{2}-\d{2}|\d{2}[\/\-]\d{2}[\/\-]\d{4})\b", text
    )
    if date_match:
        result["date"] = date_match.group(1)

    # Total / grand total amount
    total_match = re.search(
        r"(?:total|grand\s*total|المبلغ الإجمالي|الإجمالي)[:\s]+"
        r"([\d,]+\.?\d{0,2})",
        text, re.IGNORECASE,
    )
    if total_match:
        result["total_amount"] = total_match.group(1).replace(",", "")

    # VAT amount
    vat_amount_match = re.search(
        r"(?:vat|tax|ضريبة القيمة المضافة)[:\s]+"
        r"([\d,]+\.?\d{0,2})",
        text, re.IGNORECASE,
    )
    if vat_amount_match:
        result["tax_amount"] = vat_amount_match.group(1).replace(",", "")

    # Currency
    currency_match = re.search(r"\b(SAR|AED|USD|EUR|GBP|ريال)\b", text)
    if currency_match:
        raw_curr = currency_match.group(1)
        result["currency"] = "SAR" if raw_curr == "ريال" else raw_curr

    return result
