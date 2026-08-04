"""Isolation Forest beside Benford — and the ways an anomaly score can mislead.

Benford answers a question about a population; this answers one about a row.
The tests below are mostly about the boundary between the two claims the
service is allowed to make ("unusual") and the one it is not ("wrong"), plus
the failure modes that would let it look like it worked when it did not:
too small a sample, a missing model read as a clean set, and scores that move
between runs of the same audit.
"""

from datetime import date

import pytest

from apps.analytics.anomaly_service import (
    MIN_SAMPLE,
    AmountAnomalyDetector,
)


def _population(n=80, base=1000.0):
    """A boring, dense population: same vendor, mid-month, similar amounts."""
    return [
        {"id": i, "amount": base + (i % 7) * 10, "vendor_name": "Steady Supplies",
         "txn_date": date(2026, 3, 10)}
        for i in range(n)
    ]


# ── Refusals ─────────────────────────────────────────────────────────────────

def test_a_small_population_is_refused_not_guessed_at():
    result = AmountAnomalyDetector().detect(_population(n=MIN_SAMPLE - 1))

    assert not result.ran
    assert str(MIN_SAMPLE) in result.skipped_reason
    assert result.anomalies == []


def test_a_refusal_is_distinguishable_from_a_clean_result():
    """«We could not look» and «we looked and found nothing» must not look alike.

    Both return zero anomalies. Only one of them is evidence.
    """
    refused = AmountAnomalyDetector().detect(_population(n=3))
    clean = AmountAnomalyDetector().detect(_population(n=80))

    assert refused.anomalies == [] and not refused.ran
    assert clean.ran
    assert clean.skipped_reason == ""


def test_rows_without_a_usable_amount_are_dropped_not_zeroed():
    """Treating a missing amount as 0.0 would make every blank row an outlier."""
    population = _population(n=60) + [
        {"id": "x", "amount": None, "vendor_name": "V", "txn_date": date(2026, 3, 1)},
        {"id": "y", "amount": "not-a-number", "vendor_name": "V", "txn_date": date(2026, 3, 1)},
    ]
    result = AmountAnomalyDetector().detect(population)

    assert result.sample_size == 60
    assert {"x", "y"}.isdisjoint({row["id"] for row in result.scored})


# ── Does it actually find the planted outlier ────────────────────────────────

def test_a_planted_outlier_ranks_first():
    population = _population(n=80)
    population.append({
        "id": "PLANTED", "amount": 950_000.0,
        "vendor_name": "Steady Supplies", "txn_date": date(2026, 3, 31),
    })

    result = AmountAnomalyDetector().detect(population)

    assert result.ran
    assert result.scored[0]["id"] == "PLANTED"
    assert result.scored[0]["is_anomaly"] is True


def test_the_ordinary_rows_are_not_all_flagged():
    """A detector that flags everything has told the auditor nothing."""
    result = AmountAnomalyDetector().detect(_population(n=200))

    assert len(result.anomalies) < len(result.scored) * 0.1


def test_a_flagged_row_carries_a_checkable_reason():
    """A bare score cannot be argued with, so it gets accepted or ignored wholesale."""
    population = _population(n=80)
    population.append({
        "id": "PLANTED", "amount": 500_000.0,
        "vendor_name": "Steady Supplies", "txn_date": date(2026, 3, 29),
    })

    top = AmountAnomalyDetector().detect(population).scored[0]

    assert "average" in top["reason"]
    assert "period end" in top["reason"]


# ── Determinism ──────────────────────────────────────────────────────────────

def test_the_same_population_scores_identically_twice():
    """Re-running an audit is normal. Scores that drift cannot be defended."""
    population = _population(n=90)
    population.append({"id": "P", "amount": 400_000.0,
                       "vendor_name": "Steady Supplies", "txn_date": date(2026, 3, 30)})

    first = AmountAnomalyDetector().detect(population)
    second = AmountAnomalyDetector().detect(population)

    assert [r["id"] for r in first.scored] == [r["id"] for r in second.scored]
    assert [r["anomaly_score"] for r in first.scored] == [r["anomaly_score"] for r in second.scored]


# ── The claim it is allowed to make ──────────────────────────────────────────

def test_the_output_says_unusual_and_never_says_wrong():
    """`is_anomaly` is a statistical statement, not an audit finding.

    A large legitimate invoice is an outlier. If this service ever grows a
    field called `is_fraud` or `violation`, the verdict has moved from the
    auditor to an unsupervised model that was never trained on a single
    confirmed case.
    """
    result = AmountAnomalyDetector().detect(_population(n=80))

    for row in result.scored:
        assert set(row) == {
            "id", "amount", "vendor_name", "txn_date",
            "anomaly_score", "is_anomaly", "reason",
        }


def test_the_model_used_is_recorded():
    """An accuracy claim needs to name what produced it."""
    result = AmountAnomalyDetector().detect(_population(n=80))
    assert "IsolationForest" in result.model


def test_a_missing_model_is_reported_rather_than_read_as_a_clean_set(monkeypatch):
    """The worst failure here is a silent one: sklearn absent, zero anomalies
    returned, and an audit report that says the books look fine."""
    import builtins

    real_import = builtins.__import__

    def _no_sklearn(name, *args, **kwargs):
        if name.startswith("sklearn"):
            raise ImportError("No module named 'sklearn'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_sklearn)
    result = AmountAnomalyDetector().detect(_population(n=80))

    assert not result.ran
    assert "unavailable" in result.skipped_reason.lower()
    assert result.anomalies == []


# ── Complementarity with Benford ─────────────────────────────────────────────

def test_it_finds_what_benford_structurally_cannot():
    """Benford reports on a distribution; it cannot name a transaction.

    A population that conforms to Benford perfectly can still contain one
    duplicated payment, and that row is what an auditor can act on.
    """
    import math

    # Benford-conforming leading digits.
    population = []
    for digit in range(1, 10):
        count = int(round(math.log10(1 + 1 / digit) * 300))
        for i in range(count):
            population.append({
                "id": f"{digit}-{i}", "amount": float(f"{digit}{i % 90:02d}"),
                "vendor_name": "Mixed Vendors", "txn_date": date(2026, 3, (i % 28) + 1),
            })

    population.append({"id": "DUPLICATE", "amount": 888_888.0,
                       "vendor_name": "Mixed Vendors", "txn_date": date(2026, 3, 31)})

    result = AmountAnomalyDetector().detect(population)

    assert result.ran
    assert "DUPLICATE" in {row["id"] for row in result.anomalies}
