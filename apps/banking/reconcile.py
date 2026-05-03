"""
Reconciliation engine — Phase 5.3.

Given a window of bank transactions and the org's outstanding invoices,
score every (transaction, invoice) pair on four signals and return the
high-confidence matches as suggestions.

Signals (each weighted 0–25, sum 0–100):
  • amount_match      — |tx.amount – inv.total_amount| ≤ tolerance
  • date_proximity    — invoice within ±N days of transaction
  • reference_match   — tx.reference / description contains invoice_number
  • counterparty_match — tx.counterparty fuzzy-matches invoice.vendor_name

The engine is sandboxed and deterministic: same inputs ⇒ same scores.
Persistence + status updates live in ``apps.banking.services``; this
module is pure scoring.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable


# Tunables — tighten in production once we have a labelled match dataset.
AMOUNT_TOLERANCE_PCT  = Decimal("0.005")    # 0.5%
DATE_TOLERANCE_DAYS   = 3
HIGH_CONFIDENCE       = 80
MEDIUM_CONFIDENCE     = 60


# ─────────────────────────────────────────────────────────────────────────────
# Result types
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class MatchResult:
    """One scored (transaction, invoice) pair."""
    transaction: object
    invoice:     object
    score:       int = 0
    confidence:  str = "low"
    reasons:     list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "transaction_id": str(getattr(self.transaction, "id", "")),
            "invoice_id":     str(getattr(self.invoice, "id", "")),
            "score":          self.score,
            "confidence":     self.confidence,
            "reasons":        self.reasons,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Per-signal scoring
# ─────────────────────────────────────────────────────────────────────────────

def _normalise_string(s: str) -> str:
    """Lowercase + strip non-alnum so fuzzy comparisons work across spellings."""
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def _score_amount(tx_amount: Decimal, inv_amount: Decimal) -> tuple[int, dict]:
    if tx_amount is None or inv_amount is None or inv_amount == 0:
        return 0, {"signal": "amount", "score": 0, "reason": "missing amount"}
    if tx_amount <= 0 or inv_amount <= 0:
        return 0, {"signal": "amount", "score": 0, "reason": "non-positive amount"}

    diff = abs(tx_amount - inv_amount)
    if diff == 0:
        return 25, {"signal": "amount", "score": 25, "reason": "exact match"}

    pct = diff / inv_amount
    if pct <= AMOUNT_TOLERANCE_PCT:
        return 22, {"signal": "amount", "score": 22,
                    "reason": f"within {AMOUNT_TOLERANCE_PCT * 100:.1f}%"}
    if pct <= Decimal("0.02"):
        return 14, {"signal": "amount", "score": 14, "reason": "within 2%"}
    if pct <= Decimal("0.05"):
        return 7, {"signal": "amount", "score": 7, "reason": "within 5%"}
    return 0, {"signal": "amount", "score": 0,
               "reason": f"too far apart ({pct:.0%})"}


def _score_date(tx_at, inv_date) -> tuple[int, dict]:
    if not tx_at or not inv_date:
        return 0, {"signal": "date", "score": 0, "reason": "missing date"}
    tx_date = tx_at.date() if hasattr(tx_at, "date") else tx_at
    delta = abs((tx_date - inv_date).days)
    if delta == 0:
        return 25, {"signal": "date", "score": 25, "reason": "same day"}
    if delta <= DATE_TOLERANCE_DAYS:
        return 22, {"signal": "date", "score": 22, "reason": f"within {delta}d"}
    if delta <= 7:
        return 14, {"signal": "date", "score": 14, "reason": f"within 7d ({delta}d)"}
    if delta <= 30:
        return 7, {"signal": "date", "score": 7, "reason": f"within 30d ({delta}d)"}
    return 0, {"signal": "date", "score": 0, "reason": f"{delta}d apart"}


def _score_reference(tx_ref: str, tx_desc: str, inv_number: str) -> tuple[int, dict]:
    target = (inv_number or "").strip()
    if not target:
        return 0, {"signal": "reference", "score": 0, "reason": "missing invoice_number"}

    haystack = f"{tx_ref} {tx_desc}".lower()
    target_l = target.lower()
    if target_l in haystack:
        return 25, {"signal": "reference", "score": 25,
                    "reason": f"description contains '{target}'"}
    # Try without punctuation (INV-001 vs INV001).
    h_norm = _normalise_string(haystack)
    t_norm = _normalise_string(target_l)
    if t_norm and t_norm in h_norm:
        return 18, {"signal": "reference", "score": 18,
                    "reason": "normalised match"}
    return 0, {"signal": "reference", "score": 0,
               "reason": "no reference overlap"}


def _score_counterparty(tx_party: str, inv_vendor: str) -> tuple[int, dict]:
    a = _normalise_string(tx_party)
    b = _normalise_string(inv_vendor)
    if not a or not b:
        return 0, {"signal": "counterparty", "score": 0, "reason": "missing party"}
    if a == b:
        return 25, {"signal": "counterparty", "score": 25, "reason": "exact party"}
    # Substring or shared prefix of 6+ chars.
    if len(a) >= 6 and len(b) >= 6:
        if a in b or b in a:
            return 20, {"signal": "counterparty", "score": 20,
                        "reason": "substring match"}
        if a[:6] == b[:6]:
            return 12, {"signal": "counterparty", "score": 12,
                        "reason": "shared 6-char prefix"}
    return 0, {"signal": "counterparty", "score": 0, "reason": "no party overlap"}


# ─────────────────────────────────────────────────────────────────────────────
# Scorer
# ─────────────────────────────────────────────────────────────────────────────

def score_pair(transaction, invoice) -> MatchResult:
    """Run all four signals and aggregate the score (0–100)."""
    reasons: list[dict] = []
    total = 0

    inv_amount = Decimal(str(getattr(invoice, "total_amount", 0) or 0))
    tx_amount  = Decimal(str(getattr(transaction, "amount", 0) or 0))
    s, r = _score_amount(tx_amount, inv_amount)
    total += s; reasons.append(r)

    s, r = _score_date(getattr(transaction, "posted_at", None),
                       getattr(invoice, "invoice_date", None))
    total += s; reasons.append(r)

    s, r = _score_reference(getattr(transaction, "reference", "") or "",
                            getattr(transaction, "description", "") or "",
                            getattr(invoice, "invoice_number", "") or "")
    total += s; reasons.append(r)

    s, r = _score_counterparty(getattr(transaction, "counterparty", "") or "",
                               getattr(invoice, "vendor_name", "") or "")
    total += s; reasons.append(r)

    confidence = ("high" if total >= HIGH_CONFIDENCE
                  else "medium" if total >= MEDIUM_CONFIDENCE
                  else "low")

    return MatchResult(
        transaction=transaction, invoice=invoice,
        score=total, confidence=confidence,
        reasons=reasons,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Window matcher
# ─────────────────────────────────────────────────────────────────────────────

def match_window(transactions: Iterable, invoices: Iterable, *,
                 min_score: int = MEDIUM_CONFIDENCE) -> list[MatchResult]:
    """For each transaction, return the best invoice match above ``min_score``.

    Each invoice can appear at most once in the output — once a transaction
    claims it, later transactions look elsewhere. This stops two debits
    from "double-clearing" the same invoice.
    """
    invoices_list = list(invoices)
    claimed: set[str] = set()
    out: list[MatchResult] = []

    for tx in transactions:
        if getattr(tx, "is_reconciled", False):
            continue
        # Skip credits — those are receipts, not vendor-payment matches.
        if getattr(tx, "direction", "debit") == "credit":
            continue

        best: MatchResult | None = None
        for inv in invoices_list:
            if str(inv.id) in claimed:
                continue
            res = score_pair(tx, inv)
            if best is None or res.score > best.score:
                best = res

        if best and best.score >= min_score:
            out.append(best)
            claimed.add(str(best.invoice.id))

    return out
