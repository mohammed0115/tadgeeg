"""High-level facade combining prompt registry + redactor + model
registry + budget guard in a single ``call_model()`` helper.

Callers should never directly hit the provider SDK in production code —
go through this facade so the audit trail is complete::

    from apps.ai_safety.runtime import call_model

    text, meta = call_model(
        organization=org,
        prompt_name="invoice.classify",
        prompt_kwargs={"invoice_number": "INV-001"},
        model="claude-haiku-4-5",
        max_output_tokens=2_000,
        user=request.user,
    )

The actual provider call is delegated to a ``backend`` callable so the
module stays decoupled from ``anthropic`` / ``openai`` SDKs and can be
fully unit-tested.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Optional

from apps.ai_safety.budget import assert_within_budget, record_call
from apps.ai_safety.models_registry import get_model
from apps.ai_safety.prompts import get as get_prompt
from apps.ai_safety.redaction import redact


@dataclass(frozen=True)
class CallMeta:
    model:          str
    prompt_name:    str
    prompt_version: int
    prompt_sha:     str
    input_tokens:   int
    output_tokens:  int
    cost_usd:       Decimal
    redacted:       bool


# Backend signature: (model_name, rendered_prompt, max_output_tokens)
# returns (text, input_tokens, output_tokens). The default backend
# raises — production wires this to anthropic/openai SDK via DI.
BackendFn = Callable[[str, str, int], tuple[str, int, int]]


def _default_backend(model: str, prompt: str, max_out: int):
    raise RuntimeError(
        "AI runtime backend not configured — wire a callable via "
        "apps.ai_safety.runtime.set_backend()"
    )


_BACKEND: BackendFn = _default_backend


def set_backend(fn: BackendFn) -> None:
    """Plug the real provider call here. Tests use this to inject a stub."""
    global _BACKEND
    _BACKEND = fn


def call_model(*,
               organization,
               prompt_name: str,
               prompt_kwargs: Optional[dict] = None,
               model: str,
               max_output_tokens: int = 2048,
               prompt_version: Optional[int] = None,
               user=None) -> tuple[str, CallMeta]:
    """Run a guarded model call. Returns ``(text, meta)``.

    Order of operations:
        1. Resolve prompt (registry).
        2. Render it with caller's kwargs.
        3. Redact PII from the rendered prompt (defence in depth).
        4. Resolve model spec (registry).
        5. Estimate cost upper-bound; check budget.
        6. Call backend.
        7. Compute actual cost; record event; redact output.
    """
    tpl = get_prompt(prompt_name, prompt_version)
    rendered = tpl.render(**(prompt_kwargs or {}))
    safe_prompt = redact(rendered)

    spec = get_model(model)

    # Upper-bound cost = full output budget at output rate + the prompt's
    # token count approximated as len/4. Conservative on purpose.
    approx_input_tokens = max(1, len(safe_prompt) // 4)
    projected = spec.cost(
        input_tokens=approx_input_tokens,
        output_tokens=max_output_tokens,
    )
    assert_within_budget(organization, projected_cost=projected)

    text, input_tokens, output_tokens = _BACKEND(model, safe_prompt, max_output_tokens)
    actual_cost = spec.cost(input_tokens=input_tokens, output_tokens=output_tokens)
    safe_text = redact(text)

    record_call(
        organization,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost=actual_cost,
        prompt_name=tpl.name,
        prompt_version=tpl.version,
        prompt_sha=tpl.sha256,
        user=user,
    )
    meta = CallMeta(
        model=model,
        prompt_name=tpl.name,
        prompt_version=tpl.version,
        prompt_sha=tpl.sha256,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=actual_cost,
        redacted=(safe_text != text or safe_prompt != rendered),
    )
    return safe_text, meta
