"""Model registry — declarative list of every LM the platform may call.

The registry is the single source of truth for:

  • Which models are approved for use (defence against silent model swap).
  • Cost-per-token (input + output) for the budget guard.
  • Context window for upstream chunkers.
  • Training cutoff so a caller can surface "data freshness" warnings.

Adding a new model is intentionally a code change, not a setting — it
forces a review.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict


@dataclass(frozen=True)
class ModelSpec:
    name:                str            # canonical id ("claude-opus-4-7")
    provider:            str            # "anthropic" | "openai" | "gemini"
    context_window:      int
    input_cost_per_1k:   Decimal        # in USD
    output_cost_per_1k:  Decimal        # in USD
    training_cutoff:     str            # ISO date "2025-XX"
    approved_for_prod:   bool = True
    notes:               str = ""

    def cost(self, *, input_tokens: int, output_tokens: int) -> Decimal:
        """Compute the USD cost for one call."""
        return (
            (Decimal(input_tokens)  / 1000) * self.input_cost_per_1k +
            (Decimal(output_tokens) / 1000) * self.output_cost_per_1k
        )


_REGISTRY: Dict[str, ModelSpec] = {
    "claude-opus-4-7": ModelSpec(
        name="claude-opus-4-7",
        provider="anthropic",
        context_window=200_000,
        input_cost_per_1k=Decimal("0.015"),
        output_cost_per_1k=Decimal("0.075"),
        training_cutoff="2026-01",
    ),
    "claude-sonnet-4-6": ModelSpec(
        name="claude-sonnet-4-6",
        provider="anthropic",
        context_window=200_000,
        input_cost_per_1k=Decimal("0.003"),
        output_cost_per_1k=Decimal("0.015"),
        training_cutoff="2026-01",
    ),
    "claude-haiku-4-5": ModelSpec(
        name="claude-haiku-4-5",
        provider="anthropic",
        context_window=200_000,
        input_cost_per_1k=Decimal("0.0008"),
        output_cost_per_1k=Decimal("0.004"),
        training_cutoff="2026-01",
    ),
    "gpt-4o": ModelSpec(
        name="gpt-4o",
        provider="openai",
        context_window=128_000,
        input_cost_per_1k=Decimal("0.005"),
        output_cost_per_1k=Decimal("0.015"),
        training_cutoff="2024-10",
    ),
    "gpt-4o-mini": ModelSpec(
        name="gpt-4o-mini",
        provider="openai",
        context_window=128_000,
        input_cost_per_1k=Decimal("0.00015"),
        output_cost_per_1k=Decimal("0.0006"),
        training_cutoff="2024-10",
    ),
}


class ModelNotApprovedError(RuntimeError):
    """The named model is not in the registry or is not approved for prod."""


def get_model(name: str) -> ModelSpec:
    spec = _REGISTRY.get(name)
    if spec is None:
        raise ModelNotApprovedError(
            f"model '{name}' is not in the registry — add it to "
            f"apps/ai_safety/models_registry.py"
        )
    if not spec.approved_for_prod:
        raise ModelNotApprovedError(
            f"model '{name}' is registered but flagged not-for-production"
        )
    return spec


def all_models() -> list[dict]:
    return [
        {
            "name":             m.name,
            "provider":         m.provider,
            "context_window":   m.context_window,
            "input_cost_1k":    str(m.input_cost_per_1k),
            "output_cost_1k":   str(m.output_cost_per_1k),
            "training_cutoff":  m.training_cutoff,
            "approved":         m.approved_for_prod,
        }
        for m in _REGISTRY.values()
    ]
