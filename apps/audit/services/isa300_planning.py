"""ISA 300 — Planning an Audit of Financial Statements.

ISA 300 requires the auditor to develop:
  • An **overall audit strategy** (§7-12).
  • A **detailed audit plan** (§9), updated as the engagement progresses.

The strategy sets scope, timing, direction, and resourcing. The plan
specifies the nature/timing/extent of procedures. Both must be
documented (§12).

This module turns those into named services so an Engagement row can
attach a strategy + plan and a reviewer can see them at a glance.

Public API:
  • ``EngagementContext``  — inputs the auditor knows at planning time.
  • ``build_audit_strategy(ctx)`` → ``AuditStrategy`` (overall).
  • ``build_audit_plan(strategy)`` → ``AuditPlan`` (procedures).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import List


# ─── Inputs ─────────────────────────────────────────────────────────────────
@dataclass(slots=True, frozen=True)
class EngagementContext:
    """Facts known to the auditor at planning time."""
    organization_name:   str
    reporting_period:    str                    # e.g. "FY2026"
    industry:            str                    # "retail" | "manufacturing" | ...
    revenue_base:        Decimal                # for benchmark materiality
    is_listed:           bool = False
    is_first_year:       bool = False
    prior_year_modification: bool = False       # qualified / adverse opinion
    has_internal_audit:  bool = False
    has_subsidiaries:    bool = False
    risk_areas_known_in_advance: tuple[str, ...] = ()


# ─── Outputs ────────────────────────────────────────────────────────────────
@dataclass(slots=True)
class AuditStrategy:
    """ISA 300 §7-12 — overall strategy."""
    scope:           str                # what we will audit
    timing:          str                # field-work window
    direction:       str                # what we will focus on
    materiality_benchmark: str          # which benchmark we'll anchor on
    resourcing:      str                # team composition / specialists
    communications:  list[str]          # who is informed, when
    isa_paras:       tuple[str, ...] = ("ISA 300 §7", "ISA 300 §8", "ISA 300 §11")

    def to_dict(self) -> dict:
        return {
            "scope": self.scope,
            "timing": self.timing,
            "direction": self.direction,
            "materiality_benchmark": self.materiality_benchmark,
            "resourcing": self.resourcing,
            "communications": list(self.communications),
            "isa_paras": list(self.isa_paras),
        }


@dataclass(slots=True)
class PlannedProcedure:
    name:        str
    nature:      str    # "test of controls" | "substantive analytic" | "test of details"
    timing:      str    # "interim" | "year-end" | "subsequent events"
    extent:      str    # "all" | "sample" | "scan"


@dataclass(slots=True)
class AuditPlan:
    """ISA 300 §9 — detailed plan."""
    strategy:    AuditStrategy
    procedures:  List[PlannedProcedure]
    isa_paras:   tuple[str, ...] = ("ISA 300 §9", "ISA 300 §10")

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy.to_dict(),
            "procedures": [
                {"name": p.name, "nature": p.nature,
                 "timing": p.timing, "extent": p.extent}
                for p in self.procedures
            ],
            "isa_paras": list(self.isa_paras),
        }


# ─── Builders ───────────────────────────────────────────────────────────────
def _benchmark_for(ctx: EngagementContext) -> str:
    if ctx.is_listed:
        return "Profit before tax (5%)"
    if ctx.industry == "non_profit":
        return "Total expenses (1%)"
    return "Revenue (1%)"


def build_audit_strategy(ctx: EngagementContext) -> AuditStrategy:
    direction_parts: list[str] = []
    if ctx.is_first_year:
        direction_parts.append(
            "Opening balances and prior-year comparatives (ISA 510)."
        )
    if ctx.prior_year_modification:
        direction_parts.append(
            "Areas underlying prior-year modification — confirm resolution."
        )
    if ctx.has_subsidiaries:
        direction_parts.append("Component-auditor coordination (ISA 600).")
    direction_parts.append("Revenue, receivables, going concern, fraud (ISA 240/570).")
    for area in ctx.risk_areas_known_in_advance:
        direction_parts.append(f"Specific risk area: {area}.")

    communications: list[str] = [
        "Audit committee — strategy presentation at kickoff (ISA 260 §15-17)",
        "Management — fieldwork plan & deliverables 2 weeks prior",
    ]
    if ctx.has_subsidiaries:
        communications.append("Component auditors — instructions issued at planning")

    resourcing = "Lead partner + manager + 2 seniors"
    if ctx.is_listed:
        resourcing += " + EQR partner (ISQM 1 §35)"
    if ctx.industry in ("banking", "insurance"):
        resourcing += " + specialist (financial-instruments expert)"

    timing = "Interim Q3, year-end fieldwork Q1 next year, file release within 60 days of period-end"

    return AuditStrategy(
        scope=(f"Audit of the financial statements of {ctx.organization_name} "
               f"for {ctx.reporting_period}, conducted under ISA."),
        timing=timing,
        direction="; ".join(direction_parts),
        materiality_benchmark=_benchmark_for(ctx),
        resourcing=resourcing,
        communications=communications,
    )


_BASELINE_PROCEDURES: list[PlannedProcedure] = [
    PlannedProcedure(
        name="Walkthrough of revenue cycle",
        nature="test of controls", timing="interim", extent="sample",
    ),
    PlannedProcedure(
        name="Bank confirmation",
        nature="test of details", timing="year-end", extent="all",
    ),
    PlannedProcedure(
        name="Receivables circularization (ISA 505)",
        nature="test of details", timing="year-end", extent="sample",
    ),
    PlannedProcedure(
        name="Cut-off testing for revenue & inventory",
        nature="test of details", timing="year-end", extent="sample",
    ),
    PlannedProcedure(
        name="Accounting estimates review (ISA 540)",
        nature="substantive analytic", timing="year-end", extent="all",
    ),
    PlannedProcedure(
        name="Going-concern review (ISA 570)",
        nature="substantive analytic", timing="year-end", extent="all",
    ),
    PlannedProcedure(
        name="Journal-entry testing (ISA 240 §32)",
        nature="test of details", timing="year-end", extent="sample",
    ),
    PlannedProcedure(
        name="Subsequent-events review (ISA 560)",
        nature="test of details", timing="subsequent events", extent="all",
    ),
]


def build_audit_plan(strategy: AuditStrategy,
                     *,
                     extra: List[PlannedProcedure] | None = None) -> AuditPlan:
    procedures = list(_BASELINE_PROCEDURES)
    if extra:
        procedures.extend(extra)
    return AuditPlan(strategy=strategy, procedures=procedures)
