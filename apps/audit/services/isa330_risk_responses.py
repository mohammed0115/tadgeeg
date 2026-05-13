"""ISA 330 — The Auditor's Responses to Assessed Risks.

ISA 330 mandates that for every assessed risk of material misstatement
(ROMM), the auditor must design and perform procedures whose nature,
timing, and extent are **responsive to that risk**. Higher risk →
tests of details rather than analytics; more persuasive evidence;
unpredictable timing; experienced staff.

This module formalises the mapping from a risk record to a response
plan. It is the bridge between the risk register (built during ISA 315)
and the engagement plan (ISA 300).

Public API:
  • ``AssessedRisk``       — one ROMM the team has assessed.
  • ``map_responses(risks)`` → list of ``RiskResponseMapping`` rows.

The mapping table is conservative: when in doubt, escalate.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List


# ─── Inputs ─────────────────────────────────────────────────────────────────
@dataclass(slots=True, frozen=True)
class AssessedRisk:
    """One assessed risk of material misstatement."""
    name:                str
    assertion:           str         # "existence" | "completeness" | ...
    inherent_risk:       str         # "low" | "medium" | "high" | "significant"
    control_risk:        str         # "low" | "medium" | "high"
    is_significant_risk: bool = False
    is_fraud_risk:       bool = False


# ─── Outputs ────────────────────────────────────────────────────────────────
@dataclass(slots=True)
class RiskResponseMapping:
    """One row of the ISA 330 response table for a risk."""
    risk_name:       str
    nature:          str        # tests of controls / details / analytics
    timing:          str        # interim / year-end / unpredictable
    extent:          str        # increased / standard / reduced
    staff_seniority: str        # senior / manager / partner
    rationale:       str
    isa330_paras:    tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "risk_name":       self.risk_name,
            "nature":          self.nature,
            "timing":          self.timing,
            "extent":          self.extent,
            "staff_seniority": self.staff_seniority,
            "rationale":       self.rationale,
            "isa330_paras":    list(self.isa330_paras),
        }


_RISK_RANK = {"low": 1, "medium": 2, "high": 3, "significant": 4}


def _combined(risk: AssessedRisk) -> int:
    """Combined risk = max(inherent, control)."""
    return max(
        _RISK_RANK.get(risk.inherent_risk.lower(), 0),
        _RISK_RANK.get(risk.control_risk.lower(), 0),
    )


def _response_for(risk: AssessedRisk) -> RiskResponseMapping:
    combined = _combined(risk)

    # Significant or fraud risks → §21 dictates substantive procedures
    # with timing close to period-end, performed by experienced staff.
    if risk.is_significant_risk or risk.is_fraud_risk:
        return RiskResponseMapping(
            risk_name=risk.name,
            nature="test of details (substantive)",
            timing="year-end + unpredictable",
            extent="increased",
            staff_seniority="manager+",
            rationale=(
                "Significant/fraud risk per ISA 315 §28 → ISA 330 §21 "
                "requires substantive procedures specifically responsive."
            ),
            isa330_paras=("ISA 330 §21", "ISA 330 §22"),
        )

    if combined >= 3:        # high
        return RiskResponseMapping(
            risk_name=risk.name,
            nature="test of details + analytics",
            timing="year-end",
            extent="increased",
            staff_seniority="senior",
            rationale=(
                "Combined inherent+control risk is high; analytics alone "
                "would not be persuasive enough (ISA 330 §7(b))."
            ),
            isa330_paras=("ISA 330 §7", "ISA 330 §18"),
        )

    if combined == 2:        # medium
        return RiskResponseMapping(
            risk_name=risk.name,
            nature="substantive analytics + targeted details",
            timing="interim, rolled forward to year-end",
            extent="standard",
            staff_seniority="senior",
            rationale=(
                "Medium risk — analytics suffice for the population; "
                "specific items at year-end addressed by sample testing."
            ),
            isa330_paras=("ISA 330 §7", "ISA 330 §18(a)"),
        )

    # low
    return RiskResponseMapping(
        risk_name=risk.name,
        nature="tests of controls + analytical procedures",
        timing="interim",
        extent="reduced",
        staff_seniority="staff",
        rationale=(
            "Low combined risk; controls testing reliance is appropriate "
            "where controls are designed and have operated effectively."
        ),
        isa330_paras=("ISA 330 §8",),
    )


def map_responses(risks: List[AssessedRisk]) -> List[RiskResponseMapping]:
    """Build the responsive procedures table for an engagement."""
    return [_response_for(r) for r in risks]
