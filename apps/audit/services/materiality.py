"""
Materiality calculator (ISA 320, ISA 450).

Implements the standard 5-tier benchmarks auditors use to set materiality
thresholds for an engagement. Output drives the Sampling engine and the
ISA 700 opinion ("misstatements above performance materiality require
adjustment").

Benchmarks (adapted from ISA 320 paragraph A4 + Big-4 firm guidance):
  • Revenue            — most common for profit-oriented entities (0.5%–1%)
  • Total assets       — for asset-heavy entities (0.5%–1%)
  • Profit before tax  — for stable profit-oriented entities (5%–10%)
  • Equity             — for not-for-profit / capital-intensive (1%–2%)
  • Expenses           — for not-for-profit (0.5%–1%)

Performance materiality = overall materiality × (50%–75%, default 75%).
Clearly trivial threshold = overall materiality × 5% (default).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional


@dataclass(slots=True, frozen=True)
class MaterialityBenchmark:
    name: str
    pct_low: Decimal
    pct_high: Decimal
    rationale: str


BENCHMARKS: dict[str, MaterialityBenchmark] = {
    "revenue": MaterialityBenchmark(
        "Revenue",
        Decimal("0.005"), Decimal("0.01"),
        "Profit-oriented entity with stable revenue stream.",
    ),
    "total_assets": MaterialityBenchmark(
        "Total Assets",
        Decimal("0.005"), Decimal("0.01"),
        "Asset-heavy or capital-intensive industry (banking, utilities, real estate).",
    ),
    "profit_before_tax": MaterialityBenchmark(
        "Profit Before Tax",
        Decimal("0.05"), Decimal("0.10"),
        "Stable, profit-oriented entity — most-cited benchmark in ISA 320.",
    ),
    "equity": MaterialityBenchmark(
        "Equity",
        Decimal("0.01"), Decimal("0.02"),
        "Capital-intensive entity, holding companies, or breakeven entities.",
    ),
    "total_expenses": MaterialityBenchmark(
        "Total Expenses",
        Decimal("0.005"), Decimal("0.01"),
        "Not-for-profit / public-sector entity.",
    ),
}


@dataclass(slots=True)
class MaterialityResult:
    """Result of a materiality computation. All amounts are in the engagement currency."""

    benchmark: str
    benchmark_amount: Decimal
    pct_used: Decimal
    overall_materiality: Decimal
    performance_pct: Decimal
    performance_materiality: Decimal
    clearly_trivial_pct: Decimal
    clearly_trivial: Decimal
    rationale: str
    judgment_notes: list[str] = field(default_factory=list)
    component_allocation: list[dict] = field(default_factory=list)
    flagged_items: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "benchmark": self.benchmark,
            "benchmark_amount": float(self.benchmark_amount),
            "pct_used": float(self.pct_used),
            "overall_materiality": float(self.overall_materiality),
            "performance_pct": float(self.performance_pct),
            "performance_materiality": float(self.performance_materiality),
            "clearly_trivial_pct": float(self.clearly_trivial_pct),
            "clearly_trivial": float(self.clearly_trivial),
            "rationale": self.rationale,
            "judgment_notes": self.judgment_notes,
            "component_allocation": self.component_allocation,
            "flagged_items": self.flagged_items,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Judgment factors — adjust the percentage applied to the benchmark
# ─────────────────────────────────────────────────────────────────────────────

# Each factor pulls the percentage toward `pct_low` (more conservative) or
# `pct_high` (more aggressive) based on the auditor's risk assessment.
# The shifts are ISA 320 paragraph A4 + Big-4 firm guidance.
JUDGMENT_FACTORS = {
    "industry_risk": {
        "low":      Decimal("0.10"),    # +10% of the band toward pct_high
        "moderate": Decimal("0"),       # neutral
        "high":     Decimal("-0.20"),   # -20% toward pct_low (be tighter)
    },
    "control_environment": {
        "strong":   Decimal("0.15"),
        "adequate": Decimal("0"),
        "weak":     Decimal("-0.25"),   # poor controls → tighter materiality
    },
    "prior_misstatements": {
        "none":     Decimal("0.10"),
        "few":      Decimal("0"),
        "many":     Decimal("-0.20"),
    },
    "going_concern_doubt": {
        "no":       Decimal("0"),
        "some":     Decimal("-0.10"),
        "yes":      Decimal("-0.30"),   # going-concern doubt = much tighter
    },
    "first_year_audit": {
        "no":       Decimal("0"),
        "yes":      Decimal("-0.10"),   # first-year = unfamiliar = tighter
    },
}


def _apply_judgment(
    pct_low: Decimal, pct_high: Decimal, factors: dict,
) -> tuple[Decimal, list[str]]:
    """Pick a percentage inside [pct_low, pct_high] adjusted by judgment.

    Each factor maps to a shift in [-1, +1] that linearly interpolates between
    pct_low (-1) and pct_high (+1). Shifts sum, then clamp; the final position
    is converted back to an absolute percentage.

    Returns the adjusted percentage and a list of human-readable notes
    explaining each adjustment so the working paper can quote the rationale.
    """
    if not factors:
        return (pct_low + pct_high) / 2, []

    shift = Decimal("0")
    notes: list[str] = []
    for factor_name, level in factors.items():
        if factor_name not in JUDGMENT_FACTORS:
            continue
        level_str = str(level).lower()
        if level_str not in JUDGMENT_FACTORS[factor_name]:
            continue
        delta = JUDGMENT_FACTORS[factor_name][level_str]
        shift += delta
        if delta != 0:
            direction = "tighter" if delta < 0 else "looser"
            notes.append(
                f"{factor_name.replace('_', ' ')}={level_str}: {direction} "
                f"({delta:+.0%} band shift)"
            )

    # Clamp shift to [-1, +1]; map to interpolation in [0, 1].
    shift = max(Decimal("-1"), min(Decimal("1"), shift))
    t = (shift + Decimal("1")) / Decimal("2")
    pct = pct_low + (pct_high - pct_low) * t
    return pct, notes


def calculate(
    benchmark_amount: float | Decimal,
    benchmark_key: str = "profit_before_tax",
    pct_override: Optional[Decimal] = None,
    performance_pct: Decimal = Decimal("0.75"),
    clearly_trivial_pct: Decimal = Decimal("0.05"),
    judgment_factors: Optional[dict] = None,
    components: Optional[list[dict]] = None,
) -> MaterialityResult:
    """
    Compute a materiality threshold for the engagement.

    Args:
        benchmark_amount:    Selected benchmark figure (e.g. revenue 50_000_000).
        benchmark_key:       One of BENCHMARKS keys.
        pct_override:        Use this percentage instead of the band midpoint
                             (overrides any judgment-factor adjustments).
        performance_pct:     Performance materiality factor (default 75%).
        clearly_trivial_pct: Clearly-trivial threshold (default 5% of overall).
        judgment_factors:    Optional dict like
                             ``{"industry_risk": "high", "control_environment": "weak"}``.
                             Tightens or loosens the percentage inside the
                             benchmark's band; see JUDGMENT_FACTORS for keys.
        components:          Optional list of segments, each
                             ``{"name": "Riyadh", "weight_pct": Decimal("60")}``.
                             Sum of weights must equal 100. The result includes
                             a per-component allocation of overall materiality.

    Returns:
        MaterialityResult with overall, performance, clearly-trivial numbers,
        plus judgment notes and component allocation when supplied.
    """
    if benchmark_key not in BENCHMARKS:
        raise ValueError(f"Unknown benchmark: {benchmark_key}")

    bm = BENCHMARKS[benchmark_key]
    base = Decimal(str(benchmark_amount))

    # Pick the percentage. Explicit override wins; otherwise judgment factors
    # interpolate inside the band; default falls back to the midpoint.
    if pct_override is not None:
        pct = Decimal(str(pct_override))
        notes: list[str] = [f"pct override: {pct:.2%}"]
    elif judgment_factors:
        pct, notes = _apply_judgment(bm.pct_low, bm.pct_high, judgment_factors)
    else:
        pct = (bm.pct_low + bm.pct_high) / 2
        notes = []

    overall = base * pct
    performance = overall * performance_pct
    clearly_trivial = overall * clearly_trivial_pct

    # Component allocation — split overall materiality across segments by
    # weight. Each component carries its own performance + clearly-trivial
    # numbers so the team auditing that segment has thresholds to work to.
    allocation: list[dict] = []
    if components:
        total_weight = sum(Decimal(str(c.get("weight_pct", 0))) for c in components)
        if total_weight == 0:
            raise ValueError("components weights must sum to a non-zero value")
        for c in components:
            w = Decimal(str(c.get("weight_pct", 0)))
            share = (w / total_weight)
            comp_overall = overall * share
            allocation.append({
                "name":             c.get("name", ""),
                "weight_pct":       float(w),
                "share_pct":        float(share * 100),
                "overall":          float(comp_overall.quantize(Decimal("0.01"))),
                "performance":      float((comp_overall * performance_pct).quantize(Decimal("0.01"))),
                "clearly_trivial":  float((comp_overall * clearly_trivial_pct).quantize(Decimal("0.01"))),
            })
        # Validate weights sum to 100% (with a small Decimal tolerance).
        if abs(total_weight - Decimal("100")) > Decimal("0.01"):
            notes.append(f"⚠ component weights sum to {total_weight}%, expected 100%")

    return MaterialityResult(
        benchmark=bm.name,
        benchmark_amount=base,
        pct_used=pct,
        overall_materiality=overall.quantize(Decimal("0.01")),
        performance_pct=performance_pct,
        performance_materiality=performance.quantize(Decimal("0.01")),
        clearly_trivial_pct=clearly_trivial_pct,
        clearly_trivial=clearly_trivial.quantize(Decimal("0.01")),
        rationale=bm.rationale,
        judgment_notes=notes,
        component_allocation=allocation,
    )


def flag_invoices_above_threshold(invoices, threshold: Decimal) -> list[dict]:
    """
    Iterate over an invoice queryset and return rows whose total_amount
    exceeds the supplied threshold (typically performance_materiality).
    """
    flagged: list[dict] = []
    for inv in invoices.iterator():
        try:
            amount = Decimal(str(getattr(inv, "total_amount", 0) or 0))
        except (TypeError, ValueError):
            continue
        if amount >= threshold:
            flagged.append({
                "id": str(getattr(inv, "id", "")),
                "invoice_number": getattr(inv, "invoice_number", "") or "",
                "vendor": getattr(inv, "vendor_name", "") or "",
                "amount": float(amount),
                "exceeds_by": float(amount - threshold),
            })
    flagged.sort(key=lambda r: r["amount"], reverse=True)
    return flagged
