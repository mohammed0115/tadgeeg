"""Unsupervised anomaly detection over ledger/invoice amounts.

**Why this exists next to Benford rather than instead of it.** Benford's law
asks one question — does the leading-digit distribution of a *population* look
manufactured — and answers it about the set, never about a row. It is a useful
first alarm and a poor accusation: a small vendor set, a price list with round
numbers, or a fiscal year of near-identical rent payments all deviate without
anyone doing anything wrong. It also cannot point at *which* transaction to
look at, which is the only thing an auditor can act on.

Isolation Forest answers the complementary question: given everything else in
this population, how unusual is *this* row. It isolates points with fewer
random splits than dense ones, so it needs no labelled fraud examples — which
matters here, because this product has none (see the feedback loop in
apps/audit/services/finding_feedback.py; until enough verdicts accumulate,
supervised detection has nothing to learn from).

**What this is not.** An outlier is not a finding. A large legitimate invoice
is an outlier; so is the one duplicate payment. This service scores and ranks,
and says so in its output — `is_anomaly` means "unusual", never "wrong". The
auditor's verdict is what turns one into the other, and that verdict is what
eventually makes a supervised model possible.

**Determinism.** `random_state` is fixed. An audit that scores the same
population differently on two runs cannot be defended, and re-running an audit
is something auditors do.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

logger = logging.getLogger("analytics.anomaly")

#: Below this, the model has nothing to learn a "normal" shape from and will
#: mark noise. Benford's own floor in the rule engine is 30; this is higher
#: because Isolation Forest partitions a feature space rather than compares one
#: distribution, and a handful of rows makes every point look isolated.
MIN_SAMPLE = 50

#: Expected share of anomalies. Not tuned to a dataset — it is the operating
#: point that decides how much an auditor is asked to review, and 2% of a
#: month's invoices is a queue a person can actually work through.
CONTAMINATION = 0.02

RANDOM_STATE = 20260803


@dataclass
class AnomalyResult:
    """Ranked outliers plus the reason the run is or is not trustworthy."""

    scored: list = field(default_factory=list)
    skipped_reason: str = ""
    sample_size: int = 0
    model: str = ""

    @property
    def ran(self) -> bool:
        return not self.skipped_reason

    @property
    def anomalies(self) -> list:
        return [row for row in self.scored if row["is_anomaly"]]


class AmountAnomalyDetector:
    """Isolation Forest over per-transaction features.

    Features are chosen to be things an auditor would themselves look at, so a
    flagged row can be explained rather than merely asserted:

      · amount — the obvious one;
      · deviation from the vendor's own mean, because "large" only means
        something relative to that vendor's history;
      · day of month, which catches period-end clustering;
      · weekend flag, since a transaction booked on a weekend is worth a look
        in most organisations.

    Amount is log-scaled. Raw SAR values span several orders of magnitude, and
    without the transform the tree splits are dominated by the largest invoices
    — the model would simply rediscover "big" and call it "anomalous".
    """

    def __init__(self, *, contamination: float = CONTAMINATION, random_state: int = RANDOM_STATE):
        self.contamination = contamination
        self.random_state = random_state

    def detect(self, transactions) -> AnomalyResult:
        """Score `transactions`: dicts with amount, vendor_name, txn_date, id."""
        rows = [t for t in transactions if self._amount_of(t) is not None]

        if len(rows) < MIN_SAMPLE:
            return AnomalyResult(
                skipped_reason=(
                    f"Need at least {MIN_SAMPLE} transactions to model what "
                    f"normal looks like; got {len(rows)}."
                ),
                sample_size=len(rows),
            )

        try:
            import numpy as np
            from sklearn.ensemble import IsolationForest
        except ImportError as exc:  # pragma: no cover - declared in requirements
            # Loud, not silent: a missing model must never read as "no
            # anomalies found". That is the difference between "we looked and
            # the books are clean" and "we never looked".
            logger.error("anomaly detection unavailable: %s", exc)
            return AnomalyResult(
                skipped_reason=f"Anomaly model unavailable on this deployment ({exc}).",
                sample_size=len(rows),
            )

        features = np.array([self._features(t, rows) for t in rows], dtype=float)

        forest = IsolationForest(
            contamination=self.contamination,
            random_state=self.random_state,
            n_estimators=200,
        )
        labels = forest.fit_predict(features)
        raw_scores = forest.score_samples(features)

        scored = []
        for row, label, raw in zip(rows, labels, raw_scores):
            scored.append({
                "id": row.get("id"),
                "amount": self._amount_of(row),
                "vendor_name": row.get("vendor_name") or "",
                "txn_date": row.get("txn_date"),
                # score_samples returns a negative number, more negative =
                # more isolated. Flipped so bigger means more unusual, which is
                # what a column header can honestly be called.
                "anomaly_score": round(float(-raw), 4),
                "is_anomaly": bool(label == -1),
                "reason": self._explain(row, rows),
            })

        scored.sort(key=lambda r: r["anomaly_score"], reverse=True)
        return AnomalyResult(
            scored=scored,
            sample_size=len(rows),
            model=f"IsolationForest(n=200, contamination={self.contamination})",
        )

    # ── features ─────────────────────────────────────────────────────────

    @staticmethod
    def _amount_of(txn):
        raw = txn.get("amount")
        if raw in (None, ""):
            return None
        try:
            return abs(float(raw))
        except (TypeError, ValueError):
            return None

    def _features(self, txn, population):
        import math

        amount = self._amount_of(txn) or 0.0
        vendor_mean = self._vendor_mean(txn.get("vendor_name"), population)
        txn_date = txn.get("txn_date")

        return [
            math.log10(amount + 1),
            (amount / vendor_mean) if vendor_mean else 1.0,
            txn_date.day if isinstance(txn_date, date) else 15,
            1.0 if isinstance(txn_date, date) and txn_date.weekday() >= 5 else 0.0,
        ]

    def _vendor_mean(self, vendor_name, population):
        if not vendor_name:
            return 0.0
        amounts = [
            self._amount_of(t) for t in population
            if (t.get("vendor_name") or "") == vendor_name
        ]
        amounts = [a for a in amounts if a is not None]
        return (sum(amounts) / len(amounts)) if amounts else 0.0

    def _explain(self, txn, population):
        """A short, checkable reason — not a restatement of the score.

        A model that says "0.72" and nothing else cannot be argued with, and an
        auditor who cannot argue with it will either accept everything or
        ignore everything.
        """
        reasons = []
        amount = self._amount_of(txn) or 0.0
        vendor_mean = self._vendor_mean(txn.get("vendor_name"), population)

        if vendor_mean and amount > vendor_mean * 3:
            reasons.append(
                f"{amount:,.0f} is {amount / vendor_mean:.1f}× this vendor's average "
                f"({vendor_mean:,.0f})"
            )
        txn_date = txn.get("txn_date")
        if isinstance(txn_date, date):
            if txn_date.weekday() >= 5:
                reasons.append("booked on a weekend")
            if txn_date.day >= 28:
                reasons.append("booked at period end")
        return " · ".join(reasons)
