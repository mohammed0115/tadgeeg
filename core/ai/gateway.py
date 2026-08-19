"""Single, tenant-aware gateway for OpenAI requests.

Production code must call this module instead of constructing an OpenAI client.
It enforces a real organisation owner, keeps the existing Redis token cap, and
persists an append-only accounting row for both successes and failures. Payload
persistence is diagnostic only: credentials and opaque media are removed and
all retained strings are bounded.
"""
from __future__ import annotations

import logging
import time
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from django.conf import settings

from core.services import ai_budget

logger = logging.getLogger("core.ai.gateway")

_MAX_PAYLOAD_STRING = 8_000
_SENSITIVE_KEYS = frozenset({
    "authorization", "api_key", "api-key", "token", "access_token",
    "refresh_token", "secret", "password",
})


class AIOrganizationRequired(RuntimeError):
    """Raised before an external call when a tenant owner is absent."""


class AIUsageGatewayError(RuntimeError):
    """Raised only for gateway configuration or provider failures."""


def _price_table() -> dict[str, dict[str, Decimal]]:
    """Return prices per million tokens, frozen by the current deployment config.

    The usage record stores the computed amount, so later edits to this table do
    not retroactively alter an invoice or a report.
    """
    configured = getattr(settings, "AI_USAGE_MODEL_PRICES_PER_MILLION", {}) or {}
    return {
        str(model): {
            "prompt": Decimal(str(values.get("prompt", 0))),
            "completion": Decimal(str(values.get("completion", 0))),
        }
        for model, values in configured.items()
        if isinstance(values, dict)
    }


def price_at_call(model: str, prompt_tokens: int, completion_tokens: int) -> Decimal:
    prices = _price_table().get(model, {"prompt": Decimal("0"), "completion": Decimal("0")})
    amount = (
        Decimal(max(0, int(prompt_tokens))) * prices["prompt"]
        + Decimal(max(0, int(completion_tokens))) * prices["completion"]
    ) / Decimal("1000000")
    return amount.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def _sanitize(value: Any, *, key: str = "") -> Any:
    """Make a bounded JSON-safe diagnostic representation without credentials."""
    if key.lower().replace("-", "_") in _SENSITIVE_KEYS:
        return "<redacted>"
    if isinstance(value, dict):
        return {str(k): _sanitize(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value[:50]]
    if isinstance(value, str):
        if value.startswith("data:") and ";base64," in value:
            return "<omitted data URL>"
        return value[:_MAX_PAYLOAD_STRING]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:_MAX_PAYLOAD_STRING]


def _failure_kind(exc: Exception) -> str:
    from apps.ai_safety.models import AIUsageRecord

    status_code = getattr(exc, "status_code", None)
    class_name = type(exc).__name__.lower()
    if status_code == 401 or "authentication" in class_name:
        return AIUsageRecord.FailureKind.AUTH_401
    if status_code == 429 or "ratelimit" in class_name or "rate_limit" in class_name:
        return AIUsageRecord.FailureKind.RATE_LIMIT
    if "timeout" in class_name:
        return AIUsageRecord.FailureKind.TIMEOUT
    if status_code == 400 or "badrequest" in class_name or "payload" in class_name:
        return AIUsageRecord.FailureKind.PAYLOAD
    return AIUsageRecord.FailureKind.OTHER


def _record_safely(*, organization, user, model: str, operation: str,
                   prompt_tokens: int, completion_tokens: int,
                   status: str, failure_kind: str = "", latency_ms: int = 0,
                   document_id=None, request_payload: dict | None = None,
                   response_payload: dict | None = None) -> None:
    """Persist telemetry without turning a telemetry outage into an AI outage."""
    try:
        from apps.ai_safety.models import AIUsagePayload, AIUsageRecord

        record = AIUsageRecord.objects.create(
            organization=organization,
            user=user if getattr(user, "pk", None) else None,
            model=model,
            operation=operation,
            prompt_tokens=max(0, int(prompt_tokens or 0)),
            completion_tokens=max(0, int(completion_tokens or 0)),
            estimated_cost=price_at_call(model, prompt_tokens, completion_tokens),
            status=status,
            failure_kind=failure_kind,
            latency_ms=max(0, int(latency_ms or 0)),
            document_id=document_id,
        )
        AIUsagePayload.objects.create(
            usage_record=record,
            request_payload=_sanitize(request_payload or {}),
            response_payload=_sanitize(response_payload or {}),
        )
    except Exception:
        logger.exception("AI usage telemetry write failed; provider result remains usable")


def _usage_counts(response) -> tuple[int, int]:
    usage = getattr(response, "usage", None)
    return (
        int(getattr(usage, "prompt_tokens", 0) or 0),
        int(getattr(usage, "completion_tokens", 0) or 0),
    )


def chat_completion(*, organization, operation: str, messages: list[dict],
                    model: str | None = None, max_tokens: int = 2_000,
                    user=None, document_id=None, timeout: float | None = None,
                    client_factory=None, **kwargs):
    """Execute one OpenAI chat request through the metered, tenant-safe path."""
    if not getattr(organization, "pk", None):
        raise AIOrganizationRequired("AI requests require an organization owner.")
    selected_model = model or getattr(settings, "OPENAI_MODEL", "gpt-4o")
    request_payload = {
        "model": selected_model,
        "operation": operation,
        "messages": messages,
        "max_tokens": max_tokens,
        **kwargs,
    }
    started = time.monotonic()
    try:
        ai_budget.guard(organization.pk, projected_tokens=max_tokens)
        if client_factory is None:
            from openai import OpenAI
            client_factory = OpenAI

        client_kwargs = {"api_key": getattr(settings, "OPENAI_API_KEY", "")}
        if timeout is not None:
            client_kwargs["timeout"] = timeout
        response = client_factory(**client_kwargs).chat.completions.create(
            model=selected_model,
            messages=messages,
            max_tokens=max_tokens,
            **kwargs,
        )
        prompt_tokens, completion_tokens = _usage_counts(response)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        _record_safely(
            organization=organization, user=user, model=selected_model,
            operation=operation, prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens, status="success",
            latency_ms=elapsed_ms, document_id=document_id,
            request_payload=request_payload,
            response_payload={
                "id": getattr(response, "id", ""),
                "model": getattr(response, "model", selected_model),
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                },
                "content": getattr(response.choices[0].message, "content", "")
                if getattr(response, "choices", None) else "",
            },
        )
        # Maintain the existing daily Redis guard for all migrated callers.
        ai_budget.charge(organization.pk, prompt_tokens + completion_tokens)
        return response
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        _record_safely(
            organization=organization, user=user, model=selected_model,
            operation=operation, prompt_tokens=0, completion_tokens=0,
            status="failed", failure_kind=_failure_kind(exc), latency_ms=elapsed_ms,
            document_id=document_id, request_payload=request_payload,
            response_payload={
                "error_type": type(exc).__name__,
                "status_code": getattr(exc, "status_code", None),
            },
        )
        raise
