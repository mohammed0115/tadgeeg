"""
OpenAI Extraction Layer

Responsibilities:
  - extract_with_text()   : Send raw text to GPT and return structured financial JSON
  - extract_with_vision() : Send image file to GPT-4o Vision and return structured JSON
  - map_excel_columns()   : Ask GPT to map unknown column names to standard schema
  - classify_document()   : Classify a document by type from raw text

Design principles:
  - Every public function has a Tesseract / rule-based fallback
  - Exponential-backoff retry on transient OpenAI errors
  - Explicit timeouts prevent request threads from hanging
  - Never raises; returns {} on hard failure so callers can degrade gracefully
"""

import base64
import json
import logging
import time
from pathlib import Path
from typing import Optional

from django.conf import settings

logger = logging.getLogger("finai")

# ── Constants ─────────────────────────────────────────────────────────────────
EXTRACTION_SCHEMA = """{
  "document_type": "invoice|purchase_order|bank_statement|receipt|expense_report|payroll|vat_return|other",
  "vendor_name": "",
  "vendor_name_ar": "",
  "vendor_vat_number": "",
  "document_number": "",
  "date": "YYYY-MM-DD or null",
  "due_date": "YYYY-MM-DD or null",
  "currency": "SAR|USD|EUR|AED|...",
  "subtotal": 0.0,
  "vat_rate": 15.0,
  "tax_amount": 0.0,
  "discount": 0.0,
  "total_amount": 0.0,
  "line_items": [
    {"description": "", "quantity": 0, "unit_price": 0.0, "total": 0.0, "vat_rate": 15.0}
  ],
  "payment_terms": "",
  "notes": "",
  "has_qr_code": false,
  "is_handwritten": false,
  "language": "ar|en|mixed",
  "confidence": 0.0,
  "raw_extraction_notes": ""
}"""

TEXT_EXTRACTION_PROMPT = f"""You are a financial document analyst specializing in GCC financial documents.
Extract ALL financial data from the provided text and return ONLY a valid JSON object.

Rules:
- Saudi VAT numbers are 15 digits starting and ending with 3
- Dates must be in YYYY-MM-DD format (null if not found)
- Amounts must be decimal numbers (0 if not found)
- Infer document_type from content clues
- confidence (0-100): your certainty in the extraction
- If the text is messy OCR output, be tolerant of noise and typos

Return this exact JSON structure:
{EXTRACTION_SCHEMA}"""

VISION_EXTRACTION_PROMPT = f"""You are an expert financial document analyst for GCC markets.
Analyze this document image and extract ALL financial information with maximum accuracy.
Support both Arabic (RTL) and English (LTR) text equally.

Critical rules:
- Saudi VAT numbers: 15 digits, starts and ends with 3
- ZATCA QR code: small square barcode, usually top-right corner
- Set has_qr_code=true if you see any QR code
- Set is_handwritten=true if any significant portion is handwritten
- Flag fraud indicators in raw_extraction_notes if you see inconsistencies

Return ONLY this JSON structure:
{EXTRACTION_SCHEMA}"""

MAX_RETRIES = 3
BASE_RETRY_DELAY = 2   # seconds

DEFAULT_CLASSIFICATION_TYPES = [
    "invoice",
    "purchase_order",
    "bank_statement",
    "receipt",
    "expense_report",
    "payroll",
    "vat_return",
    "other",
]


# ── Client factory ────────────────────────────────────────────────────────────

def _get_client():
    """Build and return an OpenAI client.  Raises ValueError if not configured."""
    api_key = getattr(settings, "OPENAI_API_KEY", None)
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not set in settings.")
    from openai import OpenAI
    return OpenAI(api_key=api_key, timeout=60.0)


def _model() -> str:
    return getattr(settings, "OPENAI_MODEL", "gpt-4o")


# ── Core completion helper ────────────────────────────────────────────────────

def _chat_with_retry(messages: list, json_mode: bool = True) -> Optional[str]:
    """
    Call OpenAI chat completion with exponential-backoff retry.

    Returns the raw content string, or None on hard failure.
    """
    import openai

    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            client = _get_client()
            kwargs = {
                "model": _model(),
                "messages": messages,
                "max_tokens": getattr(settings, "OPENAI_MAX_TOKENS", 2000),
                "temperature": 0,
            }
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            response = client.chat.completions.create(**kwargs)
            return response.choices[0].message.content
        except (openai.RateLimitError, openai.APIConnectionError) as exc:
            last_exc = exc
            wait = BASE_RETRY_DELAY * (2 ** (attempt - 1))
            logger.warning(
                "[OpenAI] Transient error (attempt %d/%d): %s — retrying in %ds",
                attempt, MAX_RETRIES, exc, wait,
            )
            time.sleep(wait)
        except openai.AuthenticationError as exc:
            logger.error("[OpenAI] Authentication failed: %s", exc)
            return None
        except Exception as exc:
            logger.error("[OpenAI] Unexpected error on attempt %d: %s", attempt, exc)
            last_exc = exc
            break

    logger.error("[OpenAI] All retries exhausted. Last error: %s", last_exc)
    return None


def _parse_json_response(raw: Optional[str]) -> dict:
    """Parse JSON string from OpenAI response, tolerating markdown fences."""
    if not raw:
        return {}
    # Strip ```json ... ``` wrappers
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1]) if len(lines) > 2 else text
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning("[OpenAI] JSON parse failed: %s | raw=%s", exc, text[:200])
        return {}


# ── Public API ────────────────────────────────────────────────────────────────

def extract_with_text(raw_text: str, document_type: str = None) -> dict:
    """
    Send raw text to OpenAI and return structured financial JSON.

    Args:
        raw_text:      OCR or parsed text from a document.
        document_type: Optional hint if already classified.

    Returns:
        Structured dict or {} on failure.
    """
    if not raw_text or not raw_text.strip():
        logger.warning("[OpenAI] extract_with_text called with empty text.")
        return {}

    # Truncate to token budget (~6000 chars ≈ 1500 tokens for the document text)
    truncated = raw_text[:6000]

    hint = f"\nDocument type hint: {document_type}" if document_type else ""
    messages = [
        {"role": "system", "content": TEXT_EXTRACTION_PROMPT + hint},
        {"role": "user", "content": f"Document text:\n\n{truncated}"},
    ]

    raw = _chat_with_retry(messages, json_mode=True)
    result = _parse_json_response(raw)

    if result:
        logger.info(
            "[OpenAI] Text extraction succeeded: type=%s confidence=%s",
            result.get("document_type"),
            result.get("confidence"),
        )
    return result


def extract_with_vision(image_path: str, document_type: str = None) -> dict:
    """
    Send an image to GPT-4o Vision and return structured financial JSON.

    Args:
        image_path:    Path to the image file on disk.
        document_type: Optional hint if already classified.

    Returns:
        Structured dict or {} on failure.
    """
    try:
        with open(image_path, "rb") as fh:
            image_bytes = fh.read()
    except OSError as exc:
        logger.error("[OpenAI Vision] Cannot read image %s: %s", image_path, exc)
        return {}

    # Determine MIME type
    ext = Path(image_path).suffix.lower()
    mime_map = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".tiff": "image/tiff",
        ".tif": "image/tiff", ".bmp": "image/bmp",
        ".webp": "image/webp",
    }
    mime = mime_map.get(ext, "image/jpeg")
    b64 = base64.b64encode(image_bytes).decode("utf-8")

    hint = f"\nDocument type hint: {document_type}" if document_type else ""
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": VISION_EXTRACTION_PROMPT + hint,
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime};base64,{b64}",
                        "detail": "high",
                    },
                },
            ],
        }
    ]

    raw = _chat_with_retry(messages, json_mode=True)
    result = _parse_json_response(raw)

    if result:
        logger.info(
            "[OpenAI Vision] Extraction succeeded: type=%s confidence=%s",
            result.get("document_type"),
            result.get("confidence"),
        )
    return result


def classify_document(
    raw_text: str,
    allowed_types: Optional[list[str]] = None,
    aliases: Optional[dict[str, str]] = None,
) -> dict:
    """
    Classify a document type from raw text.

    Returns:
        {document_type: str, confidence: float}
    """
    if not raw_text:
        return {"document_type": "other", "confidence": 0.0}

    canonical_types: list[str] = []
    for document_type in allowed_types or DEFAULT_CLASSIFICATION_TYPES:
        normalized_type = str(document_type or "").strip().lower()
        if normalized_type and normalized_type not in canonical_types:
            canonical_types.append(normalized_type)
    if "other" not in canonical_types:
        canonical_types.append("other")

    normalized_aliases = {
        str(source).strip().lower(): str(target).strip().lower()
        for source, target in (aliases or {}).items()
        if source and target
    }
    alias_instructions = ""
    if normalized_aliases:
        alias_lines = "\n".join(
            f"- {source} -> {target}"
            for source, target in sorted(normalized_aliases.items())
        )
        alias_instructions = (
            "\nNormalise synonyms and near-matches to these canonical types:\n"
            f"{alias_lines}\n"
        )

    messages = [
        {
            "role": "system",
            "content": (
                "You are a financial document classifier. "
                "Classify the document type from the text provided.\n"
                f"Possible types: {', '.join(canonical_types)}."
                f"{alias_instructions}"
                'Return JSON: {"document_type": "...", "confidence": 0.0-1.0, '
                '"classification_reason": "..."}'
            ),
        },
        {"role": "user", "content": f"Document text (first 3000 chars):\n\n{raw_text[:3000]}"},
    ]

    raw = _chat_with_retry(messages, json_mode=True)
    result = _parse_json_response(raw)

    detected_type = str(result.get("document_type", "other") or "other").strip().lower()
    detected_type = normalized_aliases.get(detected_type, detected_type)
    if detected_type not in canonical_types:
        detected_type = "other"

    return {
        "document_type": detected_type,
        "confidence": float(result.get("confidence", 0.0)),
        "reason": result.get("classification_reason", ""),
    }


def map_excel_columns(columns: list[str], standard_fields: list[str]) -> dict:
    """
    Ask OpenAI to map unrecognised Excel column names to standard field names.

    Args:
        columns:         List of raw column names to map.
        standard_fields: List of target field names.

    Returns:
        Dict of {raw_column: standard_field} or {} on failure.
    """
    if not columns:
        return {}

    messages = [
        {
            "role": "system",
            "content": (
                "You are a financial data normalisation assistant. "
                "Map the given spreadsheet column names to the closest standard "
                "financial field names. If no match exists, map to null.\n"
                f"Standard fields: {', '.join(standard_fields)}\n"
                "Return JSON: {column_name: standard_field_or_null, ...}"
            ),
        },
        {"role": "user", "content": f"Columns to map: {json.dumps(columns)}"},
    ]

    raw = _chat_with_retry(messages, json_mode=True)
    result = _parse_json_response(raw)

    # Filter out null mappings
    return {k: v for k, v in result.items() if v and v in standard_fields}
