"""ISA 240 — The Auditor's Responsibilities Relating to Fraud.

The fraud-rule catalogue (`apps/rule_engine/catalog.py`) and the unified
fraud engine (`apps/audit/services/fraud_engine.py`) cover the **detection**
side. What ISA 240 actually demands on top of detection is a
**response framework** — once a fraud risk is identified, the standard
specifies which audit procedures are appropriate.

This module turns that response side into a structured, named service.

Coverage map:
  • ISA 240 §16-24  — Risk identification → covered by fraud_engine.
  • ISA 240 §25-32  — Response to assessed risks → **this module**.
  • ISA 240 §32     — Management-override of controls is *always*
                      a significant risk; required procedures here.
  • ISA 240 §40-43  — Communications with management & TCWG.

Public API:
  • ``FraudRiskFactor`` — one identified factor + the affected assertion.
  • ``assess_fraud_responses(factors)`` → ``FraudResponsePlan`` with
    auditor procedures, references to ISA 240 paragraphs, and a
    management-override standing-procedure block per §32.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


# ─── Inputs ─────────────────────────────────────────────────────────────────
@dataclass(slots=True, frozen=True)
class FraudRiskFactor:
    """A single fraud risk the engagement team has identified."""
    name:        str                    # e.g. "revenue_recognition"
    description: str
    severity:    str                    # "low" | "medium" | "high"
    affected_assertions: tuple[str, ...] = ()   # e.g. ("existence", "cutoff")
    detected_by: str = ""               # link to fraud_engine signal name


# ─── Outputs ────────────────────────────────────────────────────────────────
@dataclass(slots=True)
class AuditProcedure:
    name:          str
    description:   str
    isa240_para:   str                  # paragraph reference
    is_required:   bool = True          # vs. "consider"

    def to_dict(self) -> dict:
        return {
            "name":        self.name,
            "description": self.description,
            "isa240_para": self.isa240_para,
            "is_required": self.is_required,
        }


@dataclass(slots=True)
class FraudResponsePlan:
    overall_severity:  str              # max of input factor severities
    factors:           List[FraudRiskFactor]
    procedures:        List[AuditProcedure]
    mgmt_override_procedures: List[AuditProcedure] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "overall_severity": self.overall_severity,
            "factors": [
                {"name": f.name, "severity": f.severity,
                 "affected_assertions": list(f.affected_assertions)}
                for f in self.factors
            ],
            "procedures":       [p.to_dict() for p in self.procedures],
            "mgmt_override":    [p.to_dict() for p in self.mgmt_override_procedures],
        }


# ─── Catalogue of standard responses ────────────────────────────────────────
# Maps a fraud signal name (from fraud_engine) → list of procedures the
# auditor should perform. Drawn from ISA 240 §A37-A41.
_RESPONSE_CATALOGUE: dict[str, list[AuditProcedure]] = {
    "duplicate": [
        AuditProcedure(
            name="vouch_to_original",
            description=(
                "Vouch the suspected duplicate invoice back to the original "
                "supplier statement and bank payment record. Confirm whether "
                "a corresponding payment was actually issued."
            ),
            isa240_para="ISA 240 §A37",
        ),
        AuditProcedure(
            name="vendor_confirmation",
            description=(
                "Send an external confirmation request to the vendor for the "
                "disputed invoice number."
            ),
            isa240_para="ISA 240 §A39",
        ),
    ],
    "benford": [
        AuditProcedure(
            name="extended_sample",
            description=(
                "Extend the sample for the population that failed Benford. "
                "Apply ISA 530 sampling with a smaller monetary interval."
            ),
            isa240_para="ISA 240 §A38",
        ),
    ],
    "vendor_risk": [
        AuditProcedure(
            name="kyc_redo",
            description=(
                "Re-perform vendor on-boarding due diligence: trade register, "
                "VAT-number lookup, beneficial-owner search."
            ),
            isa240_para="ISA 240 §A37",
        ),
    ],
    "behavioral": [
        AuditProcedure(
            name="data_analytic_correlation",
            description=(
                "Correlate flagged invoices with payroll, login, and access "
                "logs for the period (weekend posting, after-hours approvals)."
            ),
            isa240_para="ISA 240 §A40",
        ),
    ],
    "structural": [
        AuditProcedure(
            name="forensic_document_examination",
            description=(
                "Engage a forensic-document specialist to examine alterations, "
                "handwritten edits, or low-OCR pages."
            ),
            isa240_para="ISA 240 §A41",
        ),
    ],
}


def _management_override_procedures() -> list[AuditProcedure]:
    """Per ISA 240 §32, the auditor must perform these regardless of
    whether a specific fraud risk has been identified — management
    override is *always* a presumed risk."""
    return [
        AuditProcedure(
            name="journal_entry_testing",
            description=(
                "Test the appropriateness of journal entries recorded in the "
                "general ledger and other adjustments made in the preparation "
                "of the financial statements."
            ),
            isa240_para="ISA 240 §32(a)",
        ),
        AuditProcedure(
            name="estimates_bias_review",
            description=(
                "Review accounting estimates for biases and evaluate whether "
                "the circumstances producing the bias represent a risk of "
                "material misstatement due to fraud (cross-ref ISA 540)."
            ),
            isa240_para="ISA 240 §32(b)",
        ),
        AuditProcedure(
            name="significant_unusual_transactions",
            description=(
                "Evaluate the business rationale (or lack thereof) for "
                "significant transactions outside the normal course of "
                "business or that otherwise appear unusual."
            ),
            isa240_para="ISA 240 §32(c)",
        ),
    ]


_SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}


def assess_fraud_responses(factors: List[FraudRiskFactor]) -> FraudResponsePlan:
    """Build the response plan for the engagement.

    Always includes the §32 management-override procedures, even if
    ``factors`` is empty — that's the whole point of the standard.
    """
    if factors:
        worst = max(factors, key=lambda f: _SEVERITY_RANK.get(f.severity.lower(), 0))
        overall = worst.severity
    else:
        overall = "low"

    procedures: list[AuditProcedure] = []
    seen: set[str] = set()
    for f in factors:
        for p in _RESPONSE_CATALOGUE.get(f.detected_by, []):
            if p.name in seen:
                continue
            seen.add(p.name)
            procedures.append(p)

    return FraudResponsePlan(
        overall_severity=overall,
        factors=list(factors),
        procedures=procedures,
        mgmt_override_procedures=_management_override_procedures(),
    )
