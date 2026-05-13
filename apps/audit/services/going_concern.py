"""ISA 570 — Going Concern.

Per ISA 570 (Revised) the auditor must:
  1. Evaluate management's assessment of the entity's ability to
     continue as a going concern for at least 12 months from the
     reporting date.
  2. Identify events or conditions that may cast significant doubt
     (financial / operating / other indicators).
  3. Determine whether a material uncertainty exists requiring
     disclosure or an emphasis-of-matter paragraph (ISA 570 §22-24).

This module captures the **indicator catalogue** from ISA 570 A3 and
turns it into a structured assessment.

Public API:
  • ``GoingConcernIndicators`` — dataclass holding the entity's
    indicator state (yes/no for each indicator).
  • ``assess_going_concern(indicators)`` — returns a
    ``GoingConcernAssessment`` with severity bucket, drivers, and
    the appropriate ISA 570 paragraph reference.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import List


# ─── Indicator state ───────────────────────────────────────────────────────
@dataclass(slots=True)
class GoingConcernIndicators:
    """Boolean flags for each ISA 570 A3 indicator. Default False."""

    # Financial indicators
    net_liability_position:           bool = False  # liabilities > assets
    fixed_term_borrowing_due:         bool = False  # debt maturity within 12mo without replacement plan
    indications_withdrawal_of_finance: bool = False
    negative_operating_cash_flow:     bool = False  # historical or latest period
    adverse_key_ratios:               bool = False  # e.g. current ratio < 1
    substantial_operating_losses:     bool = False
    arrears_or_discontinuance_dividends: bool = False
    inability_to_pay_creditors:       bool = False
    inability_to_comply_with_loan_terms: bool = False
    change_to_cash_on_delivery:       bool = False  # supplier action

    # Operating indicators
    intention_to_liquidate:           bool = False
    loss_of_key_management:           bool = False
    loss_of_major_market_franchise:   bool = False
    labour_difficulties:              bool = False
    shortages_of_supplies:            bool = False
    emergence_of_competitor:          bool = False

    # Other
    non_compliance_with_capital_or_statutory_requirements: bool = False
    pending_legal_proceedings:        bool = False
    changes_in_law_or_government_policy: bool = False
    uninsured_or_underinsured_catastrophes: bool = False

    # Mitigating evidence the auditor has gathered
    mgmt_has_credible_recovery_plan:  bool = False
    parent_letter_of_support:         bool = False
    refinancing_secured:              bool = False

    def yes_indicators(self) -> List[str]:
        """Return the field names where the indicator is True."""
        return [
            f.name for f in fields(self)
            if not f.name.startswith(("mgmt_", "parent_", "refinancing_"))
            and getattr(self, f.name) is True
        ]

    def mitigants(self) -> List[str]:
        return [
            f.name for f in fields(self)
            if f.name.startswith(("mgmt_", "parent_", "refinancing_"))
            and getattr(self, f.name) is True
        ]


# ─── Assessment output ─────────────────────────────────────────────────────
@dataclass(slots=True)
class GoingConcernAssessment:
    severity: str                  # "no_doubt" | "doubt_mitigated" | "material_uncertainty" | "going_concern_inappropriate"
    indicators_count: int
    indicators: List[str]
    mitigants: List[str]
    isa570_paragraph: str          # cross-reference to the standard's response
    recommended_opinion_modification: str

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "indicators_count": self.indicators_count,
            "indicators": self.indicators,
            "mitigants": self.mitigants,
            "isa570_paragraph": self.isa570_paragraph,
            "recommended_opinion_modification": self.recommended_opinion_modification,
        }


# ─── Scoring ───────────────────────────────────────────────────────────────
_HEAVY_INDICATORS = frozenset({
    "intention_to_liquidate",
    "net_liability_position",
    "inability_to_pay_creditors",
    "inability_to_comply_with_loan_terms",
})


def assess_going_concern(ind: GoingConcernIndicators) -> GoingConcernAssessment:
    """Bucket the entity per ISA 570 §22-24:

      no_doubt
        → no indicators OR all mitigated.

      doubt_mitigated
        → indicators present BUT management's plan is credible AND
          at least one structural mitigant exists.

      material_uncertainty
        → indicators present, plan not credible OR no mitigants;
          requires Material Uncertainty Related to Going Concern
          paragraph (ISA 570 §22).

      going_concern_inappropriate
        → intention to liquidate / cease operations OR insolvency
          imminent; requires adverse opinion (ISA 570 §21).
    """
    yes = ind.yes_indicators()
    mit = ind.mitigants()
    if ind.intention_to_liquidate:
        return GoingConcernAssessment(
            severity="going_concern_inappropriate",
            indicators_count=len(yes),
            indicators=yes,
            mitigants=mit,
            isa570_paragraph="ISA 570 §21",
            recommended_opinion_modification=(
                "Adverse opinion — going concern basis no longer appropriate."
            ),
        )

    heavy_yes = [i for i in yes if i in _HEAVY_INDICATORS]
    light_yes = [i for i in yes if i not in _HEAVY_INDICATORS]

    if not yes:
        return GoingConcernAssessment(
            severity="no_doubt",
            indicators_count=0,
            indicators=[],
            mitigants=mit,
            isa570_paragraph="ISA 570 §10-12 (concluding procedures)",
            recommended_opinion_modification="Unmodified opinion.",
        )

    # Heavy indicators flip the bar: a credible plan + a structural
    # mitigant are required, otherwise → material uncertainty.
    if heavy_yes:
        if ind.mgmt_has_credible_recovery_plan and (
            ind.refinancing_secured or ind.parent_letter_of_support
        ):
            return GoingConcernAssessment(
                severity="doubt_mitigated",
                indicators_count=len(yes),
                indicators=yes,
                mitigants=mit,
                isa570_paragraph="ISA 570 §19 (assessment with mitigating actions)",
                recommended_opinion_modification=(
                    "Unmodified opinion with emphasis-of-matter paragraph "
                    "on going concern."
                ),
            )
        return GoingConcernAssessment(
            severity="material_uncertainty",
            indicators_count=len(yes),
            indicators=yes,
            mitigants=mit,
            isa570_paragraph="ISA 570 §22",
            recommended_opinion_modification=(
                "Unmodified opinion + 'Material Uncertainty Related to Going "
                "Concern' section. If disclosure inadequate → qualified or "
                "adverse opinion."
            ),
        )

    # Only light indicators present.
    if ind.mgmt_has_credible_recovery_plan:
        return GoingConcernAssessment(
            severity="doubt_mitigated",
            indicators_count=len(yes),
            indicators=yes,
            mitigants=mit,
            isa570_paragraph="ISA 570 §19 (assessment with mitigating actions)",
            recommended_opinion_modification="Unmodified opinion.",
        )

    return GoingConcernAssessment(
        severity="material_uncertainty",
        indicators_count=len(yes),
        indicators=yes,
        mitigants=mit,
        isa570_paragraph="ISA 570 §22",
        recommended_opinion_modification=(
            "Unmodified opinion + Material Uncertainty paragraph."
        ),
    )
