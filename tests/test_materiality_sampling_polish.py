"""
Tests for Phase 1.2 — Materiality + Sampling polish.

Covers:
  • Judgment factors shift the percentage inside the band correctly.
  • Multi-component allocation sums back to overall materiality.
  • Error projection (MLE + UEL) for MUS samples.
  • Acceptability flag against performance materiality.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.audit.services import materiality as M
from apps.audit.services import sampling as S


# ─────────────────────────────────────────────────────────────────────────────
# Judgment factors
# ─────────────────────────────────────────────────────────────────────────────

def test_no_judgment_yields_band_midpoint():
    """Without judgment factors the calculator uses the midpoint of the band."""
    res = M.calculate(
        benchmark_amount=Decimal("100000000"),
        benchmark_key="profit_before_tax",
    )
    # PBT band is 5%–10%, midpoint = 7.5%.
    assert res.pct_used == Decimal("0.075")
    assert res.judgment_notes == []


def test_high_risk_factors_pull_pct_toward_low():
    """High-risk + weak controls + many prior errors → percentage near pct_low."""
    res = M.calculate(
        benchmark_amount=Decimal("100000000"),
        benchmark_key="profit_before_tax",
        judgment_factors={
            "industry_risk":       "high",
            "control_environment": "weak",
            "prior_misstatements": "many",
        },
    )
    # Sum of shifts = -0.20 + -0.25 + -0.20 = -0.65 → clamps inside [-1, +1]
    # → t = (1 + (-0.65)) / 2 = 0.175 → pct = 5% + (10%-5%)*0.175 = 5.875%
    assert res.pct_used == Decimal("0.05") + (Decimal("0.10") - Decimal("0.05")) * Decimal("0.175")
    assert res.pct_used < Decimal("0.075"), "must be tighter than midpoint"
    # Each factor leaves a note.
    assert len(res.judgment_notes) == 3
    assert any("industry risk" in n for n in res.judgment_notes)
    assert any("control environment" in n for n in res.judgment_notes)


def test_low_risk_factors_pull_pct_toward_high():
    """Low-risk + strong controls → percentage near pct_high."""
    res = M.calculate(
        benchmark_amount=Decimal("100000000"),
        benchmark_key="profit_before_tax",
        judgment_factors={
            "industry_risk":       "low",
            "control_environment": "strong",
        },
    )
    assert res.pct_used > Decimal("0.075"), "should be looser than midpoint"


def test_pct_override_wins_over_judgment():
    """An explicit pct override replaces any judgment-driven adjustment."""
    res = M.calculate(
        benchmark_amount=Decimal("1000000"),
        benchmark_key="revenue",
        pct_override=Decimal("0.0075"),
        judgment_factors={"industry_risk": "high"},  # would normally tighten
    )
    assert res.pct_used == Decimal("0.0075")
    # Judgment notes still record the override happened.
    assert any("override" in n.lower() for n in res.judgment_notes)


def test_unknown_factor_levels_are_silently_ignored():
    """Unknown level strings are dropped — no exception."""
    res = M.calculate(
        benchmark_amount=Decimal("1000000"),
        benchmark_key="revenue",
        judgment_factors={
            "industry_risk":    "extreme",  # not in JUDGMENT_FACTORS["industry_risk"]
            "made_up_factor":   "yes",      # entire factor unknown
            "control_environment": "weak",  # this one DOES apply
        },
    )
    # Only the recognised factor shifted the band.
    assert any("control" in n for n in res.judgment_notes)
    assert not any("industry" in n for n in res.judgment_notes)


# ─────────────────────────────────────────────────────────────────────────────
# Multi-component allocation
# ─────────────────────────────────────────────────────────────────────────────

def test_component_allocation_sums_back_to_overall():
    """Sum of per-component overall amounts must equal overall materiality."""
    res = M.calculate(
        benchmark_amount=Decimal("100000000"),
        benchmark_key="profit_before_tax",
        components=[
            {"name": "Riyadh",  "weight_pct": Decimal("60")},
            {"name": "Jeddah",  "weight_pct": Decimal("30")},
            {"name": "Dammam",  "weight_pct": Decimal("10")},
        ],
    )
    assert len(res.component_allocation) == 3
    total = sum(c["overall"] for c in res.component_allocation)
    # Allow rounding noise from quantize(0.01) on each segment.
    assert abs(total - float(res.overall_materiality)) < 0.05


def test_component_weights_must_be_non_zero():
    """All-zero weights raise a clear error."""
    with pytest.raises(ValueError, match="non-zero"):
        M.calculate(
            benchmark_amount=Decimal("1000000"),
            benchmark_key="revenue",
            components=[
                {"name": "A", "weight_pct": Decimal("0")},
                {"name": "B", "weight_pct": Decimal("0")},
            ],
        )


def test_component_weights_off_100_get_warning_note():
    """Weights summing to ≠100% emit a judgment note rather than failing."""
    res = M.calculate(
        benchmark_amount=Decimal("1000000"),
        benchmark_key="revenue",
        components=[
            {"name": "A", "weight_pct": Decimal("70")},
            {"name": "B", "weight_pct": Decimal("20")},  # sum = 90%
        ],
    )
    # Each component still gets a sensible share of the renormalised total.
    assert sum(c["share_pct"] for c in res.component_allocation) == pytest.approx(100, abs=0.5)
    assert any("100" in n for n in res.judgment_notes)


# ─────────────────────────────────────────────────────────────────────────────
# Error projection
# ─────────────────────────────────────────────────────────────────────────────

def test_zero_errors_gives_basic_precision_only():
    """A clean sample (no errors) has MLE = 0 and UEL = basic precision."""
    res = S.project_error(
        sample_errors=[],
        sampling_interval=10000,
        population_size=1000,
        sample_size=100,
        confidence_pct=95,
    )
    assert res.most_likely_error == 0.0
    # Basic precision = R(0) × interval = 3.00 × 10000 = 30000 at 95%.
    assert res.basic_precision == pytest.approx(30000, abs=1)
    assert res.incremental_allowance == 0.0
    assert res.upper_error_limit == pytest.approx(30000, abs=1)


def test_one_full_taint_error_increases_uel():
    """One item that's 100% wrong adds MLE + an incremental-allowance bump."""
    res = S.project_error(
        sample_errors=[10000],         # full taint at the interval
        sampling_interval=10000,
        population_size=1000,
        sample_size=100,
        confidence_pct=95,
    )
    # MLE = 1.0 × 10000 = 10000.
    assert res.most_likely_error == pytest.approx(10000, abs=1)
    # UEL must exceed basic precision (otherwise the error didn't raise the bound).
    assert res.upper_error_limit > res.basic_precision


def test_acceptability_against_performance_materiality():
    """When UEL ≤ PM the projection is acceptable, otherwise not."""
    # Tight performance materiality: 1000 — far below basic precision.
    tight = S.project_error(
        sample_errors=[],
        sampling_interval=10000,
        population_size=1000,
        sample_size=100,
        performance_materiality=1000,
    )
    assert tight.is_acceptable is False
    assert tight.threshold == 1000.0

    # Generous performance materiality: 100k — UEL of ~30k is fine.
    generous = S.project_error(
        sample_errors=[],
        sampling_interval=10000,
        population_size=1000,
        sample_size=100,
        performance_materiality=100000,
    )
    assert generous.is_acceptable is True


def test_unsupported_confidence_raises():
    """Confidence levels outside the lookup table raise a clear error."""
    with pytest.raises(ValueError, match="Unsupported confidence_pct"):
        S.project_error(
            sample_errors=[],
            sampling_interval=10000,
            population_size=1000,
            sample_size=100,
            confidence_pct=42,
        )


def test_taint_caps_at_one_hundred_percent():
    """An error larger than the interval still tints at 100% (no over-shoot)."""
    res = S.project_error(
        sample_errors=[50000],   # 5× the interval — should cap at 100% taint
        sampling_interval=10000,
        population_size=1000,
        sample_size=100,
    )
    # MLE = 1.0 (capped) × 10000 = 10000, NOT 50000.
    assert res.most_likely_error == pytest.approx(10000, abs=1)
