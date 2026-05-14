"""ISA 200 — Audit Risk Decomposition.

ISA 200 §A32-A47 defines:

    Audit Risk = Inherent Risk × Control Risk × Detection Risk

  • Inherent Risk (IR):    susceptibility to material misstatement before
                            considering related controls.
  • Control Risk (CR):     risk that a misstatement won't be prevented
                            or detected by the entity's controls.
  • Detection Risk (DR):   risk that the auditor's procedures fail to
                            detect a misstatement that exists. Auditor-
                            controlled — set after IR and CR are assessed.

The auditor PLANS Detection Risk to achieve a desired Audit Risk:
    DR = AR / (IR × CR)

This module provides the calculator + a bucketed reporter.

Public API:
  • ``RiskAssessmentInputs``      — dataclass capturing IR / CR signals.
  • ``assess(inputs)``            — returns ``AuditRiskAssessment``.
  • ``plan_detection_risk(...)``  — given IR / CR, what DR achieves the
                                    desired AR.
  • ``residual_risk(inherent, control_effectiveness)`` — COSO ERM 2017.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


# Default target audit risk (5% is the BIG4 industry default).
DEFAULT_TARGET_AUDIT_RISK = Decimal("0.05")


# ─── Inputs ─────────────────────────────────────────────────────────────────
@dataclass(slots=True, frozen=True)
class RiskAssessmentInputs:
    """Per-engagement / per-row inputs the auditor scores 0-100."""

    # Inherent risk drivers (the 'untouched' susceptibility):
    industry_volatility:        int = 0     # 0-25 — sector + macro
    complexity_of_transactions: int = 0     # 0-25 — exotic accounting
    susceptibility_to_fraud:    int = 0     # 0-25 — cash-heavy, high-judgement
    related_party_density:      int = 0     # 0-25 — RPTs in scope

    # Control risk drivers (the entity's defences):
    control_design_strength:    int = 0     # 0-25 — design quality
    control_operating_effectiveness: int = 0  # 0-25 — actually working
    segregation_of_duties_score: int = 0    # 0-25
    monitoring_strength:        int = 0     # 0-25 — internal audit, MIS

    # Auditor's planned procedures (drives Detection Risk):
    sample_extent:              int = 0     # 0-25 — population coverage
    procedure_persuasiveness:   int = 0     # 0-25 — analytics vs details
    timing_of_procedures:       int = 0     # 0-25 — interim vs YE
    staff_competence:           int = 0     # 0-25 — junior vs partner

    notes: str = ""

    # ── Derived 0-100 scores ───────────────────────────────────────────────
    @property
    def inherent_score(self) -> int:
        """0-100. Higher = more inherent risk."""
        return min(100,
            self.industry_volatility +
            self.complexity_of_transactions +
            self.susceptibility_to_fraud +
            self.related_party_density,
        )

    @property
    def control_score(self) -> int:
        """0-100. Higher = WORSE controls = MORE control risk.

        The four driver scores measure control *strength* (higher = better)
        so we invert: CR = 100 − strength_total.
        """
        strength = (
            self.control_design_strength +
            self.control_operating_effectiveness +
            self.segregation_of_duties_score +
            self.monitoring_strength
        )
        return max(0, min(100, 100 - strength))

    @property
    def detection_score(self) -> int:
        """0-100. Higher = WORSE coverage = MORE detection risk."""
        coverage = (
            self.sample_extent +
            self.procedure_persuasiveness +
            self.timing_of_procedures +
            self.staff_competence
        )
        return max(0, min(100, 100 - coverage))


# ─── Output ─────────────────────────────────────────────────────────────────
def _bucket(score: int) -> str:
    if score >= 75: return "very_high"
    if score >= 50: return "high"
    if score >= 25: return "moderate"
    return "low"


@dataclass(slots=True, frozen=True)
class AuditRiskAssessment:
    inherent_risk:      int     # 0-100
    control_risk:       int     # 0-100
    detection_risk:     int     # 0-100 — planned by auditor
    audit_risk:         Decimal # product, 0..1 (probability)
    audit_risk_pct:     Decimal # × 100, easier UI
    inherent_bucket:    str
    control_bucket:     str
    detection_bucket:   str
    target_audit_risk:  Decimal = DEFAULT_TARGET_AUDIT_RISK
    on_target:          bool = False
    notes:              str = ""
    isa_paras:          tuple[str, ...] = ("ISA 200 §A32", "ISA 200 §A36",
                                            "ISA 200 §A42", "ISA 315", "ISA 330")

    def to_dict(self) -> dict:
        return {
            "inherent_risk":     self.inherent_risk,
            "control_risk":      self.control_risk,
            "detection_risk":    self.detection_risk,
            "audit_risk":        str(self.audit_risk),
            "audit_risk_pct":    str(self.audit_risk_pct),
            "inherent_bucket":   self.inherent_bucket,
            "control_bucket":    self.control_bucket,
            "detection_bucket":  self.detection_bucket,
            "target_audit_risk": str(self.target_audit_risk),
            "on_target":         self.on_target,
            "isa_paras":         list(self.isa_paras),
        }


# ─── Public API ─────────────────────────────────────────────────────────────
def assess(inputs: RiskAssessmentInputs,
           *,
           target_audit_risk: Decimal = DEFAULT_TARGET_AUDIT_RISK,
           ) -> AuditRiskAssessment:
    """Compute IR/CR/DR + product audit risk per ISA 200."""
    ir = inputs.inherent_score
    cr = inputs.control_score
    dr = inputs.detection_score

    # Express each on 0..1 and multiply.
    ar = (
        (Decimal(ir) / 100) *
        (Decimal(cr) / 100) *
        (Decimal(dr) / 100)
    ).quantize(Decimal("0.0001"))

    return AuditRiskAssessment(
        inherent_risk=ir,
        control_risk=cr,
        detection_risk=dr,
        audit_risk=ar,
        audit_risk_pct=(ar * 100).quantize(Decimal("0.01")),
        inherent_bucket=_bucket(ir),
        control_bucket=_bucket(cr),
        detection_bucket=_bucket(dr),
        target_audit_risk=target_audit_risk,
        on_target=ar <= target_audit_risk,
        notes=inputs.notes,
    )


def plan_detection_risk(*,
                        inherent_risk: int,
                        control_risk: int,
                        target_audit_risk: Decimal = DEFAULT_TARGET_AUDIT_RISK,
                        ) -> int:
    """Given IR + CR + desired AR, return the DR (0-100) the auditor needs
    to plan for.  Floor at 1 to avoid division collapse, cap at 100."""
    ir = max(1, min(100, inherent_risk))
    cr = max(1, min(100, control_risk))
    # DR_decimal = AR / (IR_decimal × CR_decimal)
    ir_d = Decimal(ir) / 100
    cr_d = Decimal(cr) / 100
    denom = ir_d * cr_d
    if denom == 0:
        return 100
    dr_d = target_audit_risk / denom
    dr_pct = int((min(Decimal("1"), max(Decimal("0"), dr_d)) * 100).to_integral_value())
    return max(1, min(100, dr_pct))


def residual_risk(inherent: int, control_effectiveness: int) -> float:
    """COSO ERM 2017 residual risk model.

    Residual = Inherent × (1 − control_effectiveness/100).

    Both inputs 0-100. Output 0-100.
    """
    eff = max(0, min(100, control_effectiveness))
    return round(max(0, inherent) * (1 - eff / 100), 2)
