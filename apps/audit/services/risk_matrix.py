"""Risk matrix builder for the dashboard.

Aggregates per-invoice + per-vendor risk into a 5×5 likelihood × impact
heat map used by the audit-review dashboard. Backs the F-11 / Risk
Management Framework gap in the Enterprise Audit Review.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List


# Axis labels — fixed 5×5 grid matching COSO ERM convention.
LIKELIHOOD = ["rare", "unlikely", "possible", "likely", "almost_certain"]
IMPACT     = ["insignificant", "minor", "moderate", "major", "severe"]


@dataclass(slots=True)
class HeatCell:
    likelihood: str
    impact:     str
    count:      int = 0
    total_amount: Decimal = Decimal("0")
    samples:    List[str] = field(default_factory=list)   # up to 5 invoice ids

    @property
    def severity(self) -> str:
        """Composite severity for the cell, used to colour the dashboard:
          • likelihood index + impact index ≥ 7 → critical
          • 5..6 → high
          • 3..4 → medium
          • else → low"""
        li = LIKELIHOOD.index(self.likelihood)
        ip = IMPACT.index(self.impact)
        total = li + ip
        if total >= 7: return "critical"
        if total >= 5: return "high"
        if total >= 3: return "medium"
        return "low"

    def to_dict(self) -> dict:
        return {
            "likelihood":   self.likelihood,
            "impact":       self.impact,
            "severity":     self.severity,
            "count":        self.count,
            "total_amount": str(self.total_amount),
            "samples":      self.samples,
        }


def _likelihood_from_risk(risk_score: float) -> str:
    if risk_score >= 80: return "almost_certain"
    if risk_score >= 60: return "likely"
    if risk_score >= 40: return "possible"
    if risk_score >= 20: return "unlikely"
    return "rare"


def _impact_from_amount(amount: Decimal, materiality: Decimal) -> str:
    """Bucket the financial impact relative to performance materiality."""
    if materiality <= 0:
        # Fallback if no materiality set — use absolute SAR brackets.
        if amount >= Decimal("1000000"): return "severe"
        if amount >= Decimal("250000"):  return "major"
        if amount >= Decimal("50000"):   return "moderate"
        if amount >= Decimal("10000"):   return "minor"
        return "insignificant"
    ratio = amount / materiality
    if ratio >= 2:    return "severe"
    if ratio >= 1:    return "major"
    if ratio >= 0.5:  return "moderate"
    if ratio >= 0.1:  return "minor"
    return "insignificant"


def build_invoice_risk_matrix(invoices, *, materiality: Decimal = Decimal("0")) -> Dict:
    """Return the 5×5 grid summary + cell list, given an iterable of
    Invoice rows.

    Each invoice is placed by:
      • likelihood ← Invoice.risk_score (0-100)
      • impact     ← Invoice.total_amount vs performance materiality
    """
    grid: dict[tuple[str, str], HeatCell] = {}
    for li in LIKELIHOOD:
        for ip in IMPACT:
            grid[(li, ip)] = HeatCell(likelihood=li, impact=ip)

    totals = {"count": 0, "total_amount": Decimal("0"), "by_severity": {
        "critical": 0, "high": 0, "medium": 0, "low": 0,
    }}

    for inv in invoices:
        amount = Decimal(getattr(inv, "total_amount", 0) or 0)
        risk   = float(getattr(inv, "risk_score", 0) or 0)
        li = _likelihood_from_risk(risk)
        ip = _impact_from_amount(amount, materiality)
        cell = grid[(li, ip)]
        cell.count += 1
        cell.total_amount += amount
        if len(cell.samples) < 5:
            cell.samples.append(str(getattr(inv, "pk", "")))
        totals["count"] += 1
        totals["total_amount"] += amount
        totals["by_severity"][cell.severity] += 1

    return {
        "cells":  [grid[(li, ip)].to_dict() for li in LIKELIHOOD for ip in IMPACT],
        "totals": {
            "count":        totals["count"],
            "total_amount": str(totals["total_amount"]),
            "by_severity":  totals["by_severity"],
        },
        "axes": {
            "likelihood": LIKELIHOOD,
            "impact":     IMPACT,
        },
    }
