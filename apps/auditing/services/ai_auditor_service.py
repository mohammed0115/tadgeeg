"""AI Auditor Service — send normalized text to OpenAI and return audit JSON."""

import json
import logging
import re

from django.conf import settings

from apps.auditing.prompts.financial_auditor_prompt import (
    SYSTEM_PROMPT,
    build_user_message,
)

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "gpt-4o"
_MAX_TOKENS = 4096
_TEMPERATURE = 0.1


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
            return self._parse_response(content)

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
            if not isinstance(result, dict):
                return self._fallback_result("AI returned non-dict JSON.")
            return result
        except json.JSONDecodeError as exc:
            logger.warning("JSON decode failed for AI response: %s | Content: %.200s", exc, content)
            json_match = re.search(r"\{[\s\S]*\}", content)
            if json_match:
                try:
                    return json.loads(json_match.group())
                except json.JSONDecodeError:
                    pass
            return self._fallback_result(f"JSON parse error: {exc}")

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
