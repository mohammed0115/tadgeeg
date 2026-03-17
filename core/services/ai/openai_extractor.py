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
BASE_RETRY_DELAY = 2   # seconds (used only outside Celery context)

# When running inside a Celery task, set this flag to True so the retry
# logic raises immediately instead of blocking with time.sleep().
# The Celery task's own retry mechanism handles the backoff.
_IN_CELERY_CONTEXT = False


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

    Wraps each attempt with the OpenAI circuit breaker so persistent
    failures automatically stop reaching the upstream API.

    Returns the raw content string, or None on hard failure.
    """
    import openai
    from core.services.ai.circuit_breaker import (
        get_openai_circuit_breaker,
        CircuitBreakerOpen,
    )

    cb = get_openai_circuit_breaker()

    # Fast-path: circuit is OPEN — no point even trying
    if cb.is_open:
        logger.warning("[OpenAI] Circuit breaker is OPEN — skipping API call")
        return None

    def _do_call() -> str:
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

    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return cb.call(_do_call)
        except CircuitBreakerOpen as exc:
            logger.warning("[OpenAI] Circuit OPEN (retry_after=%.0fs) — aborting", exc.retry_after)
            return None
        except (
            openai.RateLimitError,
            openai.APIConnectionError,
            openai.APITimeoutError,   # covers httpx.TimeoutException too
        ) as exc:
            last_exc = exc
            logger.warning(
                "[OpenAI] Transient error (attempt %d/%d): %s",
                attempt, MAX_RETRIES, exc,
            )
            if _IN_CELERY_CONTEXT:
                # Do NOT sleep — let Celery's own retry countdown handle backoff.
                # Re-raise so the task's except block can call self.retry().
                raise
            wait = BASE_RETRY_DELAY * (2 ** (attempt - 1))
            logger.debug("[OpenAI] Sleeping %ds before retry", wait)
            time.sleep(wait)
        except openai.AuthenticationError as exc:
            logger.error("[OpenAI] Authentication failed — no retry: %s", exc)
            return None
        except openai.BadRequestError as exc:
            # Permanent: malformed request / unsupported content — don't retry
            logger.error("[OpenAI] Bad request (permanent): %s", exc)
            return None
        except Exception as exc:
            logger.error("[OpenAI] Unexpected error on attempt %d: %s", attempt, exc)
            last_exc = exc
            if attempt < MAX_RETRIES:
                time.sleep(BASE_RETRY_DELAY)
                continue
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

    # Layer 1 — sanitize document text before sending (prompt injection defence)
    from core.services.ai.prompt_sanitizer import PromptSanitizer
    safe_text = PromptSanitizer.sanitize_input(raw_text)

    # Truncate to token budget (~6000 chars ≈ 1500 tokens for the document text)
    truncated = safe_text[:6000]

    hint = f"\nDocument type hint: {document_type}" if document_type else ""
    # Layer 2 — harden system prompt against role-override attacks
    system_prompt = PromptSanitizer.build_hardened_system_prompt(TEXT_EXTRACTION_PROMPT + hint)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Document text:\n\n{truncated}"},
    ]

    raw = _chat_with_retry(messages, json_mode=True)
    result = _parse_json_response(raw)

    # Layer 3 — validate output schema (rejects non-financial injection responses)
    result = PromptSanitizer.validate_output(result)

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


def classify_document(raw_text: str) -> dict:
    """
    Classify a document type from raw text.

    Returns:
        {document_type: str, confidence: float}
    """
    if not raw_text:
        return {"document_type": "other", "confidence": 0.0}

    messages = [
        {
            "role": "system",
            "content": (
                "You are a financial document classifier. "
                "Classify the document type from the text provided.\n"
                "Possible types: invoice, purchase_order, bank_statement, "
                "receipt, expense_report, payroll, vat_return, other.\n"
                'Return JSON: {"document_type": "...", "confidence": 0.0-1.0, '
                '"classification_reason": "..."}'
            ),
        },
        {"role": "user", "content": f"Document text (first 3000 chars):\n\n{raw_text[:3000]}"},
    ]

    raw = _chat_with_retry(messages, json_mode=True)
    result = _parse_json_response(raw)

    return {
        "document_type": result.get("document_type", "other"),
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
