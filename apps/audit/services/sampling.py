"""
Audit Sampling engine (ISA 530).

Implements three classic sampling methods:
  1. Random sampling — uniform pick across population.
  2. Systematic sampling — every n-th item starting from a random offset.
  3. Monetary-Unit Sampling (MUS) — proportional to amount; high-value
     transactions are guaranteed to be selected.

The output is always a deterministic list of (population_index, weight, reason)
so the auditor can re-run the same sample with the same seed.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable, Optional


@dataclass(slots=True)
class SamplingResult:
    method: str
    population_size: int
    sample_size: int
    sampled_indices: list[int]
    sampled_items: list[dict]
    coverage_pct: float
    seed: Optional[int] = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "population_size": self.population_size,
            "sample_size": self.sample_size,
            "sampled_indices": self.sampled_indices,
            "sampled_items": self.sampled_items,
            "coverage_pct": self.coverage_pct,
            "seed": self.seed,
            "notes": self.notes,
        }


def _serialize(item) -> dict:
    """Best-effort dict snapshot of an Invoice/Document for the audit working paper."""
    return {
        "id": str(getattr(item, "id", "") or ""),
        "invoice_number": getattr(item, "invoice_number", "") or "",
        "vendor": getattr(item, "vendor_name", "") or "",
        "amount": float(getattr(item, "total_amount", 0) or 0),
        "date": str(getattr(item, "invoice_date", "") or ""),
        "risk_level": getattr(item, "risk_level", "") or "",
    }


def random_sample(
    population: list, sample_size: int, seed: int = 42,
) -> SamplingResult:
    """Uniform random sample of `sample_size` items from `population`."""
    n = len(population)
    sample_size = min(sample_size, n)
    rng = random.Random(seed)
    indices = sorted(rng.sample(range(n), sample_size))
    items = [_serialize(population[i]) for i in indices]
    return SamplingResult(
        method="random",
        population_size=n,
        sample_size=sample_size,
        sampled_indices=indices,
        sampled_items=items,
        coverage_pct=round(sample_size / n * 100, 2) if n else 0.0,
        seed=seed,
    )


def systematic_sample(
    population: list, sample_size: int, seed: int = 42,
) -> SamplingResult:
    """Every n/sample_size-th item, starting from a random offset."""
    n = len(population)
    sample_size = min(sample_size, n)
    rng = random.Random(seed)
    if sample_size == 0:
        step = 1
        start = 0
    else:
        step = max(1, n // sample_size)
        start = rng.randint(0, step - 1) if step > 1 else 0
    indices = list(range(start, n, step))[:sample_size]
    items = [_serialize(population[i]) for i in indices]
    return SamplingResult(
        method="systematic",
        population_size=n,
        sample_size=len(indices),
        sampled_indices=indices,
        sampled_items=items,
        coverage_pct=round(len(indices) / n * 100, 2) if n else 0.0,
        seed=seed,
        notes=[f"Step interval: {step}", f"Random start offset: {start}"],
    )


def monetary_unit_sample(
    population: list,
    sampling_interval: float | Decimal,
    *,
    amount_attr: str = "total_amount",
    seed: int = 42,
) -> SamplingResult:
    """
    Monetary-unit sampling (PPS — probability-proportional-to-size).

    Treats the population as a stream of monetary units; advances by
    `sampling_interval` and selects whichever transaction the cursor lands on.
    Any transaction larger than the interval is guaranteed to be selected.
    """
    rng = random.Random(seed)
    interval = Decimal(str(sampling_interval))
    if interval <= 0:
        raise ValueError("sampling_interval must be positive")

    cursor = Decimal(str(rng.uniform(0.0, float(interval))))
    cumulative = Decimal("0")
    selected: list[int] = []
    notes: list[str] = []

    for idx, item in enumerate(population):
        amt = Decimal(str(getattr(item, amount_attr, 0) or 0))
        if amt <= 0:
            continue
        next_cum = cumulative + amt
        # Step the cursor forward while the next monetary unit lies inside this item.
        while cursor < next_cum:
            selected.append(idx)
            cursor += interval
        cumulative = next_cum

    selected = sorted(set(selected))
    sampled_items = [_serialize(population[i]) for i in selected]
    n = len(population)
    return SamplingResult(
        method="monetary_unit",
        population_size=n,
        sample_size=len(selected),
        sampled_indices=selected,
        sampled_items=sampled_items,
        coverage_pct=round(len(selected) / n * 100, 2) if n else 0.0,
        seed=seed,
        notes=[
            f"Sampling interval: {interval}",
            f"Total population value: {cumulative}",
            "MUS guarantees selection of any item ≥ sampling_interval",
        ],
    )


def suggest_sample_size(
    population_size: int,
    confidence_pct: int = 95,
    expected_error_rate: float = 0.05,
) -> int:
    """
    Rule-of-thumb sample size for attribute sampling at a given confidence
    level. Uses ISA 530 Appendix 3 lookup tables (simplified).
    """
    if population_size < 50:
        return population_size
    base = {
        90: 25,
        95: 60,
        99: 90,
    }.get(confidence_pct, 60)
    # More expected errors → bigger sample.
    factor = 1 + (expected_error_rate * 4)
    return min(int(base * factor), population_size)


# ─────────────────────────────────────────────────────────────────────────────
# Error projection (ISA 530 §A18–A23) — evaluate sample misstatements
# ─────────────────────────────────────────────────────────────────────────────

# AICPA / ISA 530 reliability factors (Poisson, two-sided) for the "incremental
# allowance for sampling risk" used in MUS error projection. Values are the
# upper-1-tailed reliability factor R(N=k errors, confidence=C). Lookup: confidence
# → list of factors indexed by k (0, 1, 2, 3, 4, 5+).
_RELIABILITY_FACTORS = {
    99: [4.61, 6.64, 8.41, 10.05, 11.61, 13.11],
    95: [3.00, 4.75, 6.30, 7.76, 9.16, 10.52],
    90: [2.31, 3.89, 5.33, 6.69, 8.00, 9.28],
    80: [1.61, 3.00, 4.28, 5.52, 6.72, 7.91],
}


@dataclass(slots=True)
class ErrorProjection:
    """
    Result of projecting sample misstatements to the population.

    Fields:
      most_likely_error: best estimate of total population misstatement.
      upper_error_limit: MLE plus an "allowance for sampling risk" — auditor
                         compares this to performance materiality.
      basic_precision:   the precision component contributed by zero errors.
      incremental_allowance: extra precision from each observed error.
      sample_errors:     the per-item misstatements provided by the auditor.
    """
    method: str
    confidence_pct: int
    population_size: int
    sample_size: int
    sampling_interval: float
    sample_errors: list[float]
    most_likely_error: float
    basic_precision: float
    incremental_allowance: float
    upper_error_limit: float
    is_acceptable: Optional[bool] = None
    threshold: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "confidence_pct": self.confidence_pct,
            "population_size": self.population_size,
            "sample_size": self.sample_size,
            "sampling_interval": self.sampling_interval,
            "sample_errors": self.sample_errors,
            "most_likely_error": self.most_likely_error,
            "basic_precision": self.basic_precision,
            "incremental_allowance": self.incremental_allowance,
            "upper_error_limit": self.upper_error_limit,
            "is_acceptable": self.is_acceptable,
            "threshold": self.threshold,
        }


def project_error(
    sample_errors: list[float | Decimal],
    sampling_interval: float | Decimal,
    population_size: int,
    sample_size: int,
    confidence_pct: int = 95,
    performance_materiality: Optional[float | Decimal] = None,
    method: str = "monetary_unit",
) -> ErrorProjection:
    """
    Project the total population misstatement from a sample's errors.

    Implements the AICPA / Big-4 standard MUS upper-error-limit formula:

        most_likely_error    = Σ (taint_i × sampling_interval)
        basic_precision      = R(0) × sampling_interval
        incremental_allowance = Σ ((R(k) - R(k-1) - 1) × tainting_k × interval)
        upper_error_limit    = MLE + basic_precision + incremental_allowance

    where each `taint_i` is the percentage error for that sample item
    (misstatement / book value), capped at 100% for overstatement.

    For random / systematic attribute samples, ``sampling_interval`` should
    be set to ``population_total / sample_size`` and the result still gives
    a defensible upper-bound estimate.

    Args:
        sample_errors:           List of per-item misstatement amounts (positive
                                  = overstatement). Same currency as the
                                  population.
        sampling_interval:       MUS interval (or pop-total ÷ sample-size for
                                  attribute samples).
        population_size:         Number of items in the population.
        sample_size:             Number of items in the sample.
        confidence_pct:          80, 90, 95, or 99.
        performance_materiality: Optional. If supplied, the result includes
                                  ``is_acceptable = upper_error_limit ≤ pm``.
        method:                   Just stamped on the result for the working paper.

    Returns:
        ErrorProjection with MLE, UEL, and acceptability flag.
    """
    factors = _RELIABILITY_FACTORS.get(confidence_pct)
    if not factors:
        raise ValueError(f"Unsupported confidence_pct {confidence_pct}; "
                         f"choose one of {sorted(_RELIABILITY_FACTORS)}")

    interval = Decimal(str(sampling_interval))
    errors = [Decimal(str(e)) for e in sample_errors]

    # Tainting % for each item — capped at 100% per AICPA guidance.
    # Item is overstated if error > 0.
    taints: list[Decimal] = []
    for e in errors:
        if interval == 0:
            taints.append(Decimal("0"))
            continue
        t = e / interval
        if t > Decimal("1"):
            t = Decimal("1")
        if t < Decimal("-1"):
            t = Decimal("-1")
        taints.append(t)

    mle = sum((t * interval for t in taints), Decimal("0"))
    basic_precision = Decimal(str(factors[0])) * interval

    # Incremental allowance: ranked taints (descending), each contributes
    # (R(k) - R(k-1) - 1) × taint × interval. Beyond k=5 we use the slope
    # between the last two factors.
    sorted_taints = sorted((abs(t) for t in taints), reverse=True)
    incremental = Decimal("0")
    for k, taint in enumerate(sorted_taints, start=1):
        if k < len(factors):
            delta = Decimal(str(factors[k])) - Decimal(str(factors[k - 1])) - Decimal("1")
        else:
            # Linear extrapolation past the table.
            slope = Decimal(str(factors[-1])) - Decimal(str(factors[-2]))
            delta = slope - Decimal("1")
        if delta < 0:
            delta = Decimal("0")
        incremental += delta * taint * interval

    uel = mle + basic_precision + incremental

    threshold = None
    is_acceptable = None
    if performance_materiality is not None:
        threshold = float(performance_materiality)
        is_acceptable = float(uel) <= threshold

    return ErrorProjection(
        method=method,
        confidence_pct=confidence_pct,
        population_size=population_size,
        sample_size=sample_size,
        sampling_interval=float(interval),
        sample_errors=[float(e) for e in errors],
        most_likely_error=float(mle.quantize(Decimal("0.01"))),
        basic_precision=float(basic_precision.quantize(Decimal("0.01"))),
        incremental_allowance=float(incremental.quantize(Decimal("0.01"))),
        upper_error_limit=float(uel.quantize(Decimal("0.01"))),
        is_acceptable=is_acceptable,
        threshold=threshold,
    )
