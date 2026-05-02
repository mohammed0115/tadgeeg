"""AI Auditor Service — send normalized text or images to OpenAI and return audit JSON."""

import base64
import hashlib
import json
import logging
import os
import re

from django.conf import settings
from django.core.cache import cache

from apps.auditing.prompts.financial_auditor_prompt import (
    SYSTEM_PROMPT,
    build_user_message,
)

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "gpt-4o"
_MAX_TOKENS = 4096
_TEMPERATURE = 0.1
_CACHE_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 days

# Canonical document_type values (must match apps.auditing.models.AuditDocument.DocumentType)
_CANONICAL_DOC_TYPES = {
    "invoice", "purchase_order", "bank_statement", "payroll",
    "expense_report", "tax_declaration", "fixed_asset", "sales_receipt", "other",
}

# Aliases the AI sometimes returns or that frontend uses — map to the canonical value.
_DOC_TYPE_ALIASES = {
    "vat_return": "tax_declaration",
    "vat_returns": "tax_declaration",
    "vat-return": "tax_declaration",
    "tax_return": "tax_declaration",
    "tax-declaration": "tax_declaration",
    "po": "purchase_order",
    "purchase-order": "purchase_order",
    "purchase_orders": "purchase_order",
    "bank-statement": "bank_statement",
    "bankstatement": "bank_statement",
    "bank_statements": "bank_statement",
    "expense": "expense_report",
    "expense-report": "expense_report",
    "expense_reports": "expense_report",
    "receipt": "sales_receipt",
    "sales-receipt": "sales_receipt",
    "sales_receipts": "sales_receipt",
    "asset": "fixed_asset",
    "fixed-asset": "fixed_asset",
    "fixed_assets": "fixed_asset",
    "salary": "payroll",
    "salaries": "payroll",
    "payslip": "payroll",
    "bill": "invoice",
    "invoices": "invoice",
    "tax_invoice": "invoice",
    "simplified_tax_invoice": "invoice",
}


def normalize_document_type(value: str) -> str:
    """Map any AI-returned or user-provided doc type to a canonical snake_case value."""
    if not value:
        return "other"
    v = str(value).strip().lower().replace(" ", "_")
    if v in _CANONICAL_DOC_TYPES:
        return v
    return _DOC_TYPE_ALIASES.get(v, "other")


def _cache_key(prefix: str, *parts) -> str:
    """Build a deterministic cache key by hashing the inputs."""
    h = hashlib.sha256()
    for p in parts:
        if isinstance(p, (bytes, bytearray)):
            h.update(p)
        else:
            h.update(str(p).encode("utf-8", errors="replace"))
        h.update(b"\x1f")
    return f"ai_audit:{prefix}:{h.hexdigest()[:32]}"


class AIAuditorService:
    """Send normalized text to OpenAI and return parsed audit JSON."""

    def __init__(self):
        self._client = None  # lazy init

    def audit(self, text: str, doc_type_hint: str = "auto", language: str = "auto") -> dict:
        """
        Call OpenAI with the financial auditor prompt.
        Returns parsed JSON dict. Never raises — returns error dict on failure.

        Accepts both positional and keyword argument forms:
          audit(text, "invoice")
          audit(text, doc_type_hint="invoice", language="ar")
        """
        if not text or not text.strip():
            return self._fallback_result("Empty document text provided.")

        ck = _cache_key("text", _DEFAULT_MODEL, doc_type_hint, language, text)
        cached = cache.get(ck)
        if cached is not None:
            logger.info("AIAuditorService.audit cache hit (key=%s)", ck[-12:])
            return cached

        try:
            client = self._get_client()
            if client is None:
                return self._fallback_result("OpenAI API key not configured.")

            messages = self._build_messages(text, doc_type_hint, language)

            response = client.chat.completions.create(
                model=_DEFAULT_MODEL,
                messages=messages,
                max_tokens=_MAX_TOKENS,
                temperature=_TEMPERATURE,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content
            result = self._parse_response(content)
            if not result.get("_error"):
                cache.set(ck, result, _CACHE_TTL_SECONDS)
            return result

        except Exception as exc:
            logger.exception("AIAuditorService.audit failed: %s", exc)
            return self._fallback_result(str(exc))

    def _get_client(self):
        if self._client is not None:
            return self._client

        api_key = getattr(settings, "OPENAI_API_KEY", None)
        if not api_key:
            import os
            api_key = os.environ.get("OPENAI_API_KEY")

        if not api_key:
            logger.warning("OPENAI_API_KEY not set. AI audit will be skipped.")
            return None

        try:
            from openai import OpenAI
            self._client = OpenAI(api_key=api_key)
            return self._client
        except ImportError:
            logger.error("openai package is not installed.")
            return None

    def _build_messages(self, text: str, doc_type_hint: str, language: str = "auto") -> list:
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_message(text, doc_type_hint, language)},
        ]

    # ─────────── Vision (GPT-4o multimodal) ───────────

    def audit_images(
        self,
        images: list[bytes] | list[str],
        doc_type_hint: str = "auto",
        language: str = "auto",
        ocr_text: str = "",
    ) -> dict:
        """
        Send one or more images (raw bytes or file paths) to GPT-4o Vision and
        return the parsed audit JSON dict. Used for images and image-based PDFs.
        """
        # Build cache key from image bytes (hashed) + hint + language + ocr_text
        try:
            cache_parts = [_DEFAULT_MODEL, doc_type_hint, language, ocr_text or ""]
            for img in images:
                if isinstance(img, (bytes, bytearray)):
                    cache_parts.append(img)
                elif isinstance(img, str) and os.path.exists(img):
                    cache_parts.append(str(os.path.getsize(img)))
                    cache_parts.append(str(int(os.path.getmtime(img))))
                    cache_parts.append(img)
            ck = _cache_key("vision", *cache_parts)
            cached = cache.get(ck)
            if cached is not None:
                logger.info("AIAuditorService.audit_images cache hit (key=%s)", ck[-12:])
                return cached
        except Exception as exc:
            logger.warning("Vision cache key build failed: %s", exc)
            ck = None

        try:
            client = self._get_client()
            if client is None:
                return self._fallback_result("OpenAI API key not configured.")

            image_parts = self._encode_images(images)
            if not image_parts:
                return self._fallback_result("No valid images provided.")

            # Build a prompt that's honest about being a vision call. The base
            # prompt says "extracted text" — for image inputs we add a header
            # so the model knows to read directly from the attached image(s).
            vision_header = (
                "VISION MODE — the attached image(s) are the actual document.\n"
                "Read all visible text, numbers, tables, stamps, and QR codes "
                "from the image. The text block below is either empty or "
                "auxiliary OCR; trust the image as the source of truth.\n\n"
            )
            base_msg = build_user_message(
                ocr_text or "(no auxiliary text — extract from the image)",
                doc_type_hint,
                language,
            )
            text_part = vision_header + base_msg

            user_content = [{"type": "text", "text": text_part}] + image_parts

            response = client.chat.completions.create(
                model=_DEFAULT_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                max_tokens=_MAX_TOKENS,
                temperature=_TEMPERATURE,
                response_format={"type": "json_object"},
            )

            result = self._parse_response(response.choices[0].message.content)
            if ck and not result.get("_error"):
                cache.set(ck, result, _CACHE_TTL_SECONDS)
            return result

        except Exception as exc:
            logger.exception("AIAuditorService.audit_images failed: %s", exc)
            return self._fallback_result(str(exc))

    def _encode_images(self, images) -> list[dict]:
        """Convert a list of bytes or file paths into Vision API image parts."""
        parts: list[dict] = []
        for img in images[:10]:  # cap at 10 images per call
            if isinstance(img, (bytes, bytearray)):
                b64 = base64.b64encode(img).decode("ascii")
                mime = "image/png"
            elif isinstance(img, str) and os.path.exists(img):
                with open(img, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("ascii")
                ext = os.path.splitext(img)[1].lower().lstrip(".")
                mime = {
                    "jpg": "image/jpeg",
                    "jpeg": "image/jpeg",
                    "png": "image/png",
                    "webp": "image/webp",
                    "gif": "image/gif",
                }.get(ext, "image/jpeg")
            else:
                continue
            parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}", "detail": "high"},
            })
        return parts

    def _parse_response(self, content: str) -> dict:
        if not content:
            return self._fallback_result("Empty response from AI.")

        content = content.strip()
        fence_pattern = re.compile(r"^```(?:json)?\s*([\s\S]*?)\s*```$", re.MULTILINE)
        match = fence_pattern.search(content)
        if match:
            content = match.group(1).strip()

        try:
            result = json.loads(content)
        except json.JSONDecodeError as exc:
            logger.warning("JSON decode failed for AI response: %s | Content: %.200s", exc, content)
            json_match = re.search(r"\{[\s\S]*\}", content)
            if json_match:
                try:
                    result = json.loads(json_match.group())
                except json.JSONDecodeError:
                    return self._fallback_result(f"JSON parse error: {exc}")
            else:
                return self._fallback_result(f"JSON parse error: {exc}")

        if not isinstance(result, dict):
            return self._fallback_result("AI returned non-dict JSON.")

        # Normalize document_type to a canonical value
        raw_type = result.get("document_type", "")
        canonical = normalize_document_type(raw_type)
        if canonical != raw_type:
            logger.info("Normalized doc_type: %r -> %r", raw_type, canonical)
        result["document_type"] = canonical

        return result

    def _fallback_result(self, error: str) -> dict:
        logger.warning("AIAuditorService fallback result: %s", error)
        return {
            "document_type": "other",
            "document_type_confidence": 0.0,
            "overall_confidence": 0.0,
            "language_detected": "unknown",
            "executive_summary": f"لم يتمكن الذكاء الاصطناعي من معالجة المستند. الخطأ: {error}",
            "extracted_data": {},
            "field_confidence": {},
            "validation_results": [],
            "anomalies": [],
            "compliance_review": {
                "audit_readiness": "low",
                "traceability": "low",
                "completeness": "low",
                "key_missing_elements": [],
                "notes": [error],
            },
            "recommendations": ["يرجى إعادة المحاولة أو مراجعة المستند يدوياً."],
            "overall_risk_level": "medium",
            "_error": error,
        }
