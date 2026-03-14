"""
AI Field Extractor

Converts raw text or structured parser output into normalised
financial fields using a three-tier fallback strategy:

  Tier 1 — OpenAI GPT-4o (highest accuracy)
  Tier 2 — Rule-based regex extraction (deterministic fallback)
  Tier 3 — Heuristic / best-effort parsing (last resort)

The extractor returns a NormalisedDocument dict that matches the
unified schema expected by the Financial AI Engine.
"""

import logging
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

logger = logging.getLogger("finai")

# ── Normalised schema ─────────────────────────────────────────────────────────

EMPTY_DOCUMENT: dict = {
    "document_type": "other",
    "vendor_name": "",
    "vendor_name_ar": "",
    "vendor_vat_number": "",
    "document_number": "",
    "date": None,
    "due_date": None,
    "currency": "SAR",
    "subtotal": 0.0,
    "vat_rate": 15.0,
    "tax_amount": 0.0,
    "discount": 0.0,
    "total_amount": 0.0,
    "line_items": [],
    "payment_terms": "",
    "notes": "",
    "language": "unknown",
    "confidence": 0.0,
    "extraction_tier": "none",
}

# ── Regex patterns ────────────────────────────────────────────────────────────

RE_INVOICE_NUM = re.compile(
    r"(?:invoice|فاتورة|inv|no\.?|number|رقم)[:\s#]*([A-Za-z0-9\-_/]+)",
    re.IGNORECASE,
)
RE_DATE = re.compile(
    r"\b(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}|\d{4}[/\-\.]\d{2}[/\-\.]\d{2})\b"
)
RE_AMOUNT = re.compile(
    r"(?:total|amount|إجمالي|مبلغ)[:\s]*([0-9,]+(?:\.[0-9]{1,2})?)",
    re.IGNORECASE,
)
RE_VAT = re.compile(
    r"(?:vat|tax|ضريبة)[:\s]*([0-9,]+(?:\.[0-9]{1,2})?)",
    re.IGNORECASE,
)
RE_CURRENCY = re.compile(
    r"\b(SAR|USD|EUR|AED|QAR|KWD|BHD|OMR|EGP|GBP)\b",
    re.IGNORECASE,
)
RE_VAT_NUMBER = re.compile(r"\b3\d{13}3\b")   # Saudi VAT: 15 digits, starts+ends with 3
RE_VENDOR = re.compile(
    r"(?:from|vendor|supplier|issued by|بائع|مورد|المورد)[:\s]+([^\n\r]{3,60})",
    re.IGNORECASE,
)


class AIExtractor:
    """
    Three-tier document field extractor.

    Usage:
        extractor = AIExtractor()
        doc = extractor.extract(raw_text=text, document_type="invoice")
    """

    def extract(
        self,
        raw_text: str = "",
        structured: dict = None,
        document_type: str = None,
        image_path: str = None,
    ) -> dict:
        """
        Extract and normalise financial fields from document content.

        Tries Tier 1 → 2 → 3 until confidence meets threshold.

        Returns:
            Normalised document dict.
        """
        structured = structured or {}
        result = EMPTY_DOCUMENT.copy()

        # If parser already produced high-quality structured data, use it
        if structured and self._is_high_quality(structured):
            merged = self._merge_structured(result, structured)
            merged["extraction_tier"] = "parser_structured"
            return merged

        # ── Tier 1: OpenAI ────────────────────────────────────────────────────
        if raw_text or image_path:
            ai_result = self._extract_ai(raw_text, image_path, document_type)
            if ai_result and float(ai_result.get("confidence", 0)) >= 50:
                merged = self._merge_structured(result, ai_result)
                merged["extraction_tier"] = "openai"
                logger.info("[AIExtractor] Tier 1 (OpenAI) success, confidence=%.0f%%",
                            float(ai_result.get("confidence", 0)))
                return merged

        # ── Tier 2: Rule-based regex ──────────────────────────────────────────
        regex_result = self._extract_regex(raw_text)
        if regex_result and regex_result.get("total_amount", 0) > 0:
            merged = self._merge_structured(result, regex_result)
            # Supplement with structured parser output
            merged = self._merge_structured(merged, structured)
            merged["extraction_tier"] = "regex"
            logger.info("[AIExtractor] Tier 2 (regex) success")
            return merged

        # ── Tier 3: Best-effort from structured parser output ─────────────────
        if structured:
            merged = self._merge_structured(result, structured)
            merged["extraction_tier"] = "parser_fallback"
            logger.warning("[AIExtractor] Tier 3 (parser fallback)")
            return merged

        logger.error("[AIExtractor] All extraction tiers failed.")
        return result

    # ── Tier 1: AI extraction ─────────────────────────────────────────────────

    def _extract_ai(
        self,
        raw_text: str,
        image_path: Optional[str],
        document_type: Optional[str],
    ) -> dict:
        try:
            from core.services.ai.openai_extractor import extract_with_text, extract_with_vision

            # Vision extraction (image path provided and text is sparse)
            if image_path and len(raw_text or "") < 200:
                return extract_with_vision(image_path, document_type=document_type)

            # Text extraction
            if raw_text:
                return extract_with_text(raw_text, document_type=document_type)

        except Exception as exc:
            logger.warning("[AIExtractor] OpenAI call failed: %s", exc)
        return {}

    # ── Tier 2: Regex extraction ──────────────────────────────────────────────

    def _extract_regex(self, text: str) -> dict:
        if not text:
            return {}

        result: dict = {}

        # Invoice / document number
        m = RE_INVOICE_NUM.search(text)
        if m:
            result["document_number"] = m.group(1).strip()

        # Date (take first match)
        m = RE_DATE.search(text)
        if m:
            result["date"] = self._parse_date(m.group(1))

        # Total amount (take last match to get the grand total)
        matches = RE_AMOUNT.findall(text)
        if matches:
            result["total_amount"] = self._parse_amount(matches[-1])

        # VAT/tax amount
        m = RE_VAT.search(text)
        if m:
            result["tax_amount"] = self._parse_amount(m.group(1))

        # Currency
        m = RE_CURRENCY.search(text)
        if m:
            result["currency"] = m.group(1).upper()

        # VAT number
        m = RE_VAT_NUMBER.search(text)
        if m:
            result["vendor_vat_number"] = m.group(0)

        # Vendor name
        m = RE_VENDOR.search(text)
        if m:
            result["vendor_name"] = m.group(1).strip()

        return result

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _is_high_quality(self, structured: dict) -> bool:
        """Consider parser output high-quality if key financial fields are present."""
        required = ["total_amount", "date"]
        return all(structured.get(k) for k in required) and float(
            structured.get("confidence", 0) or 0
        ) >= 70

    def _merge_structured(self, base: dict, override: dict) -> dict:
        """Overlay override values onto base dict, ignoring None/empty/zero for amounts."""
        result = base.copy()
        for key, value in override.items():
            if value is None or value == "" or value == []:
                continue
            # Don't overwrite non-zero amounts with zero
            if key in ("total_amount", "tax_amount", "subtotal") and value == 0:
                continue
            result[key] = value
        return result

    def _parse_amount(self, s: str) -> float:
        try:
            return float(str(s).replace(",", "").strip())
        except (ValueError, TypeError):
            return 0.0

    def _parse_date(self, s: str) -> Optional[str]:
        s = s.strip()
        for sep in ("/", "-", "."):
            parts = s.split(sep)
            if len(parts) == 3:
                try:
                    if len(parts[0]) == 4:
                        return f"{parts[0]}-{parts[1].zfill(2)}-{parts[2].zfill(2)}"
                    elif len(parts[2]) == 4:
                        return f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
                    elif int(parts[0]) <= 12:   # MM/DD/YY
                        year = 2000 + int(parts[2]) if int(parts[2]) < 100 else int(parts[2])
                        return f"{year}-{parts[0].zfill(2)}-{parts[1].zfill(2)}"
                except (ValueError, IndexError):
                    continue
        return s
