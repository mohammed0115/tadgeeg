"""Zakat calculator (Saudi).

Zakat is the Islamic religious levy that Saudi/GCC-owned entities pay
to ZATCA at 2.5% of the **Zakat base**. The Zakat base is *not* taxable
income — it's an adjusted equity figure prescribed by Saudi Zakat
regulations (Implementing Regulations of the Zakat Collection, 1437H).

Two computation methods are accepted:
  1. **Equity method** — Zakat base = adjusted equity + long-term
     liabilities − long-term assets, all measured at year-end.
  2. **Working-capital method** — Zakat base = adjusted net working
     capital + adjusted profits. Rarely used; equity method dominates.

This service implements the equity method, which matches the standard
ZATCA filing template line numbers. It returns both the base and the
2.5% calculation so callers can drop it directly into the filing.

Public API:
  • ``ZakatInputs`` — line items from the trial balance.
  • ``compute_zakat(inputs)`` → ``ZakatAssessment``.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


ZAKAT_RATE = Decimal("0.025")            # 2.5%


@dataclass(slots=True, frozen=True)
class ZakatInputs:
    """Year-end figures from the trial balance. All values in SAR."""

    # Additions to the base (the "wealth" side)
    paid_up_capital:              Decimal = Decimal("0")
    retained_earnings:            Decimal = Decimal("0")
    statutory_reserve:            Decimal = Decimal("0")
    other_reserves:               Decimal = Decimal("0")
    long_term_liabilities:        Decimal = Decimal("0")
    long_term_provisions:         Decimal = Decimal("0")    # EOSI, etc.
    minority_interest:            Decimal = Decimal("0")
    adjusted_profit:              Decimal = Decimal("0")

    # Deductions from the base (the "non-zakatable assets" side)
    fixed_assets_net:             Decimal = Decimal("0")
    investments_in_subsidiaries:  Decimal = Decimal("0")
    intangible_assets:            Decimal = Decimal("0")
    accumulated_losses:           Decimal = Decimal("0")    # subtract from additions
    investment_in_zakatable_subs: Decimal = Decimal("0")    # already paying

    # Special case: if zakat base < adjusted profit, the floor is the
    # adjusted profit. Negative bases are NOT zero — the rule is:
    # base = max(computed_base, adjusted_profit)
    apply_profit_floor: bool = True


@dataclass(slots=True, frozen=True)
class ZakatAssessment:
    additions:        Decimal       # sum of equity + long-term lines
    deductions:       Decimal       # sum of non-zakatable assets
    raw_base:         Decimal       # additions − deductions
    zakat_base:       Decimal       # max(raw_base, profit_floor) if applicable
    profit_floor_applied: bool
    zakat_due:        Decimal       # zakat_base × 2.5%
    rate:             Decimal = ZAKAT_RATE

    def to_dict(self) -> dict:
        return {
            "additions":            str(self.additions),
            "deductions":           str(self.deductions),
            "raw_base":             str(self.raw_base),
            "zakat_base":           str(self.zakat_base),
            "profit_floor_applied": self.profit_floor_applied,
            "rate":                 str(self.rate),
            "zakat_due":            str(self.zakat_due),
        }


def compute_zakat(inputs: ZakatInputs) -> ZakatAssessment:
    """Apply the equity-method calculation."""
    additions = (
        inputs.paid_up_capital
        + inputs.retained_earnings
        + inputs.statutory_reserve
        + inputs.other_reserves
        + inputs.long_term_liabilities
        + inputs.long_term_provisions
        + inputs.minority_interest
        + inputs.adjusted_profit
        - inputs.accumulated_losses
    )
    deductions = (
        inputs.fixed_assets_net
        + inputs.investments_in_subsidiaries
        + inputs.intangible_assets
        + inputs.investment_in_zakatable_subs
    )
    raw_base = additions - deductions

    profit_floor_applied = False
    if inputs.apply_profit_floor and raw_base < inputs.adjusted_profit:
        zakat_base = inputs.adjusted_profit
        profit_floor_applied = True
    else:
        zakat_base = raw_base

    # Negative bases yield zero zakat; the regulation never refunds.
    if zakat_base < 0:
        zakat_base = Decimal("0")

    zakat_due = (zakat_base * ZAKAT_RATE).quantize(Decimal("0.01"))

    return ZakatAssessment(
        additions=additions,
        deductions=deductions,
        raw_base=raw_base,
        zakat_base=zakat_base,
        profit_floor_applied=profit_floor_applied,
        zakat_due=zakat_due,
    )
