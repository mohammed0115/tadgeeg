"""Report-level AI narrative synthesis.

The deterministic `findings_service.build_narrative` produces a safe,
template-based executive narrative from the rule-based findings register.
This service makes ONE LLM call per report to upgrade that narrative to
Big4-style prose grounded in the same numbers — when no API key is
configured (or the call fails), callers fall back to the deterministic
output, so reports never break.

Output shape matches `build_narrative` exactly:
    {
        "conclusion":   str,
        "key_findings": list[str],
        "exec_recs":    list[str],
        "immediate":    list[str],
        "future":       list[str],
    }
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "gpt-4o-mini"
_MAX_TOKENS = 1200
_TEMPERATURE = 0.2
_CACHE_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 days

_REQUIRED_KEYS = ("conclusion", "key_findings", "exec_recs", "immediate", "future")


def _api_key() -> str | None:
    return getattr(settings, "OPENAI_API_KEY", None) or os.environ.get("OPENAI_API_KEY")


def _build_summary_payload(findings_register: dict, type_label: str, type_singular: str) -> dict:
    """Strip findings_register down to the fields the model actually needs.

    Keeping the prompt small matters for both cost and reproducible caching:
    the same set of findings should always hash to the same key.
    """
    findings = findings_register.get("findings", []) or []
    by_sev = findings_register.get("by_severity", {}) or {}
    return {
        "type_label":    type_label,
        "type_singular": type_singular,
        "totals": {
            "findings":          len(findings),
            "critical":          int(by_sev.get("critical", 0)),
            "high":              int(by_sev.get("high", 0)),
            "medium":            int(by_sev.get("medium", 0)),
            "low":               int(by_sev.get("low", 0)),
            "documents_affected": int(findings_register.get("total_invoices_affected", 0)),
            "financial_impact":   float(findings_register.get("total_financial_impact", 0) or 0),
        },
        "findings": [
            {
                "rule_code":      f.get("rule_code"),
                "title":          f.get("title"),
                "severity":       f.get("severity"),
                "failure_count":  f.get("failure_count"),
                "recommendation": f.get("recommendation"),
            }
            for f in findings[:30]  # cap to keep prompt bounded
        ],
    }


def _hash_payload(payload: dict, language: str) -> str:
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False) + f"|lang={language}"
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


_SYSTEM_PROMPT = (
    "You are a senior financial auditor (Big4 standard). You will receive a "
    "JSON object summarizing the rule-based findings of an automated audit "
    "over a portfolio of financial documents. Your job is to synthesize a "
    "concise, professional executive narrative grounded ONLY in the numbers "
    "provided. Do NOT invent rule codes, document counts, or amounts that "
    "are not in the input.\n\n"
    "Return STRICT JSON ONLY, matching this schema exactly:\n"
    "{\n"
    '  "conclusion":   "string — one sentence overall opinion",\n'
    '  "key_findings": ["3-5 bullet strings, each citing real numbers from the input"],\n'
    '  "exec_recs":    ["3 bullet strings — strategic, executive-level"],\n'
    '  "immediate":    ["3-4 bullet strings — concrete actions for blocking findings"],\n'
    '  "future":       ["3-4 bullet strings — longer-horizon controls/training"]\n'
    "}\n\n"
    "Style: terse, audit-grade, no marketing tone. Match the requested language."
)


def _build_user_message(payload: dict, language: str) -> str:
    lang_name = {"ar": "Arabic", "en": "English"}.get(language, "Arabic")
    return (
        f"Language: {lang_name}\n\n"
        f"Findings summary (JSON):\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def _validate_shape(result: Any) -> dict | None:
    if not isinstance(result, dict):
        return None
    out: dict = {}
    for key in _REQUIRED_KEYS:
        val = result.get(key)
        if key == "conclusion":
            if not isinstance(val, str) or not val.strip():
                return None
            out[key] = val.strip()
        else:
            if not isinstance(val, list):
                return None
            out[key] = [str(v).strip() for v in val if str(v).strip()]
    return out


def build_ai_narrative(
    *,
    findings_register: dict,
    type_label: str,
    type_singular: str,
    language: str = "ar",
    organization=None,
) -> dict | None:
    """Return an LLM-synthesized narrative, or None to signal "fall back".

    Never raises. Caches successful results for 7 days keyed by the findings
    payload + language, so re-renders of the same report are free.

    When ``organization`` is supplied, the AI cost guard runs first: a denied
    org (suspended / unsubscribed / over daily token budget) returns None and
    the caller keeps its deterministic narrative — no OpenAI spend.
    """
    if not findings_register or not findings_register.get("findings"):
        return None  # nothing to synthesize — caller's deterministic path is fine
    if organization is None:
        logger.warning("ai_narrative_service: organization is required; using deterministic narrative")
        return None
    from apps.billing.ai_access import ai_access_allowed
    if not ai_access_allowed(organization, projected_tokens=_MAX_TOKENS):
        logger.info("ai_narrative_service: AI access denied for org — falling back")
        return None
    api_key = _api_key()
    if not api_key:
        logger.info("ai_narrative_service: OPENAI_API_KEY not set — skipping synthesis")
        return None

    payload = _build_summary_payload(findings_register, type_label, type_singular)
    ck = f"ai_narrative:{_hash_payload(payload, language)}"
    cached = cache.get(ck)
    if cached is not None:
        logger.info("ai_narrative_service: cache hit (%s)", ck[-12:])
        return cached

    try:
        from core.ai.gateway import chat_completion

        resp = chat_completion(
            organization=organization,
            operation="narrative",
            model=_DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": _build_user_message(payload, language)},
            ],
            max_tokens=_MAX_TOKENS,
            temperature=_TEMPERATURE,
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content
        parsed = json.loads(content) if content else None
        narrative = _validate_shape(parsed)
        if narrative is None:
            logger.warning("ai_narrative_service: invalid shape from LLM; falling back")
            return None
        cache.set(ck, narrative, _CACHE_TTL_SECONDS)
        return narrative
    except Exception as exc:
        logger.warning("ai_narrative_service: synthesis failed (%s); falling back", exc)
        return None
