"""ISA 540 — Auditing Accounting Estimates and Related Disclosures.

ISA 540 (Revised) addresses risks of material misstatement (RoMM)
arising from accounting estimates: provisions, fair-value
measurements, impairment, expected credit losses, useful-life
assumptions for fixed assets, etc.

The auditor's job per ISA 540:
  1. Identify estimates with significant management judgment.
  2. Assess the inherent risk (estimation uncertainty,
     subjectivity, complexity).
  3. Test management's process — point estimate vs. auditor's range.
  4. Evaluate disclosure adequacy.

This module exposes:

  • ``EstimateProfile`` — represents one estimate (e.g. "Inventory
    obsolescence provision") with the inputs ISA 540 cares about.
  • ``assess_estimation_uncertainty(profile)`` — returns a 0-100
    uncertainty score with severity bucket + driver breakdown.
  • ``compute_auditor_range(profile)`` — supports a ±N% sensitivity
    range around management's point estimate.
  • ``flag_estimates(profiles, materiality)`` — given a portfolio of
    estimates and the materiality threshold from ``materiality.py``,
    surface the ones that need extended audit procedures.

Implementation kept deliberately small and pure-data — the engagement
orchestrator (post-ISA-workflow build-out) wires this into the
sampling + working-papers flow.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable, List, Optional


# ─── Inputs ────────────────────────────────────────────────────────────────
@dataclass(slots=True)
class EstimateProfile:
    """One accounting estimate as the auditor sees it."""
    name: str                                # "Inventory obsolescence"
    category: str                            # "provision" | "fair_value" | "depreciation" | "ecl" | "other"
    management_estimate: Decimal             # the point value on the books
    estimation_method: str                   # "point" | "range" | "discounted_cash_flow" | "model_based"
    complexity: int                          # 1 (low) .. 5 (very complex / model-based)
    subjectivity: int                        # 1 (low) .. 5 (very subjective)
    estimation_uncertainty: int              # 1 (narrow range) .. 5 (wide range)
    relies_on_external_data: bool            # market quotes, third-party valuations
    prior_period_misstatement: bool          # was this estimate misstated last year?
    disclosure_quality: int                  # 1 (poor) .. 5 (excellent)
    notes: str = ""

    def as_dict(self) -> dict:
        return {
            "name":                    self.name,
            "category":                self.category,
            "management_estimate":     str(self.management_estimate),
            "estimation_method":       self.estimation_method,
            "complexity":              self.complexity,
            "subjectivity":            self.subjectivity,
            "estimation_uncertainty":  self.estimation_uncertainty,
            "relies_on_external_data": self.relies_on_external_data,
            "prior_period_misstatement": self.prior_period_misstatement,
            "disclosure_quality":      self.disclosure_quality,
            "notes":                   self.notes,
        }


# ─── Output ────────────────────────────────────────────────────────────────
@dataclass(slots=True)
class EstimateAssessment:
    profile: EstimateProfile
    uncertainty_score: int                   # 0-100 (higher = more risk)
    severity: str                            # "low" | "medium" | "high" | "significant_risk"
    drivers: List[str] = field(default_factory=list)
    auditor_range_low:  Optional[Decimal] = None
    auditor_range_high: Optional[Decimal] = None
    exceeds_materiality: Optional[bool]   = None

    def to_dict(self) -> dict:
        return {
            "profile":           self.profile.as_dict(),
            "uncertainty_score": self.uncertainty_score,
            "severity":          self.severity,
            "drivers":           self.drivers,
            "auditor_range_low":  str(self.auditor_range_low)  if self.auditor_range_low  is not None else None,
            "auditor_range_high": str(self.auditor_range_high) if self.auditor_range_high is not None else None,
            "exceeds_materiality": self.exceeds_materiality,
        }


# ─── Scoring ───────────────────────────────────────────────────────────────
def _bucket(score: int) -> str:
    if score >= 75: return "significant_risk"   # ISA 540 R.20 — extended procedures required
    if score >= 50: return "high"
    if score >= 25: return "medium"
    return "low"


def assess_estimation_uncertainty(profile: EstimateProfile) -> EstimateAssessment:
    """Weighted score 0-100. Weights chosen to match ISA 540 A20-A24
    factors that drive estimation risk."""
    drivers: list[str] = []
    score = 0

    # Complexity 0-25 points
    c_pts = (profile.complexity - 1) * 6      # 0..24
    score += c_pts
    if c_pts >= 18:
        drivers.append("model-based / complex methodology")

    # Subjectivity 0-25 points
    s_pts = (profile.subjectivity - 1) * 6
    score += s_pts
    if s_pts >= 18:
        drivers.append("high management judgment")

    # Estimation uncertainty (width of the range) 0-25 points
    u_pts = (profile.estimation_uncertainty - 1) * 6
    score += u_pts
    if u_pts >= 18:
        drivers.append("wide range of reasonable outcomes")

    # External-data reliance — softer signal, +10
    if profile.relies_on_external_data:
        score += 10
        drivers.append("relies on external valuations / market quotes")

    # Prior-period misstatement is a strong indicator, +15
    if profile.prior_period_misstatement:
        score += 15
        drivers.append("misstated in the prior period")

    # Disclosure quality 1 → -0pts (perfect), 5 → +0pts; missing disclosure
    # adds risk because users can't assess the estimate.
    if profile.disclosure_quality <= 2:
        score += 10
        drivers.append("poor disclosure quality")

    score = max(0, min(100, int(score)))
    return EstimateAssessment(
        profile=profile,
        uncertainty_score=score,
        severity=_bucket(score),
        drivers=drivers,
    )


def compute_auditor_range(
    profile: EstimateProfile, *, sensitivity_pct: Decimal = Decimal("0.10"),
) -> tuple[Decimal, Decimal]:
    """± sensitivity_pct around management's point estimate. Default ±10%."""
    mgmt = Decimal(profile.management_estimate)
    delta = (mgmt * sensitivity_pct).quantize(Decimal("0.01"))
    return mgmt - delta, mgmt + delta


def flag_estimates(
    profiles: Iterable[EstimateProfile],
    *,
    performance_materiality: Decimal,
    sensitivity_pct: Decimal = Decimal("0.10"),
) -> List[EstimateAssessment]:
    """Run every estimate through the scorer; attach an auditor range
    and a materiality-breach flag (the estimate's range crosses the
    performance-materiality threshold)."""
    out: list[EstimateAssessment] = []
    for prof in profiles:
        a = assess_estimation_uncertainty(prof)
        a.auditor_range_low, a.auditor_range_high = compute_auditor_range(
            prof, sensitivity_pct=sensitivity_pct,
        )
        range_width = a.auditor_range_high - a.auditor_range_low
        a.exceeds_materiality = range_width > performance_materiality
        out.append(a)
    return sorted(out, key=lambda x: x.uncertainty_score, reverse=True)
