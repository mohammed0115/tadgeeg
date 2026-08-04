"""Risk forecasting — and the ways a trend line lies.

A slope is trivially easy to compute and trivially easy to over-read. Two
points fit a perfect line; an all-zero series produces a confident "stable";
a downward line eventually predicts a negative number of findings. Each of
those would be presented to an auditor as a projection, and each is an
artefact of the arithmetic rather than a fact about the books.

So most of what follows is about refusals and about the honesty of the
uncertainty label, not about whether the slope is arithmetically right.
"""

from datetime import date, timedelta

import pytest
from django.utils import timezone

from apps.analytics.risk_forecast_service import MIN_PERIODS, RiskForecastService


@pytest.fixture
def make_findings(db, organization):
    """Create findings dated N months back, so a real series exists."""
    from apps.audit.models import AuditFinding

    def _make(counts_by_months_ago, rule_code="DUP-001", invoice=None):
        now = timezone.now()

        def month_start(months_ago):
            """Exact calendar month, not now - 30*n days.

            Day arithmetic drifts: 30 days back from the 31st lands in the same
            month, so two buckets collapse into one and another comes out empty
            — which turns a deliberately flat fixture into a fake trend and
            makes the test disagree with the service for no real reason.
            The 15th keeps every stamp comfortably inside its month.
            """
            year, month = now.year, now.month - months_ago
            while month <= 0:
                month += 12
                year -= 1
            return now.replace(year=year, month=month, day=15,
                               hour=12, minute=0, second=0, microsecond=0)

        for months_ago, count in counts_by_months_ago.items():
            stamp = month_start(months_ago)
            for i in range(count):
                finding = AuditFinding.objects.create(
                    organization=organization,
                    rule_code=rule_code,
                    rule_name="Duplicate invoice",
                    message=f"m-{months_ago}-{i}",
                    invoice=invoice,
                )
                # first_detected_at is auto_now_add; move it deliberately.
                AuditFinding.objects.filter(pk=finding.pk).update(first_detected_at=stamp)
    return _make


# ── Refusals ─────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_a_short_history_is_refused_not_extrapolated(organization, make_findings):
    """Two points fit a perfect line. That is the trap, not the result."""
    make_findings({0: 5, 1: 3})

    trend = RiskForecastService(organization).overall_trend(months_back=2)

    assert trend.confidence == "insufficient"
    assert trend.direction == "unknown"
    assert str(MIN_PERIODS) in trend.reason
    assert trend.projection == []


@pytest.mark.django_db
def test_an_empty_window_is_not_reported_as_stable(organization):
    """"Stable" implies something was measured. Nothing was."""
    trend = RiskForecastService(organization).overall_trend(months_back=12)

    assert trend.confidence == "insufficient"
    assert trend.direction == "unknown"
    assert "No findings" in trend.reason


# ── Direction ────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_a_rising_series_reads_as_deteriorating(organization, make_findings):
    make_findings({5: 1, 4: 3, 3: 5, 2: 8, 1: 11, 0: 14})

    trend = RiskForecastService(organization).overall_trend(months_back=8)

    assert trend.direction == "deteriorating"
    assert trend.slope > 0.5


@pytest.mark.django_db
def test_a_falling_series_reads_as_improving(organization, make_findings):
    make_findings({5: 14, 4: 11, 3: 8, 2: 5, 1: 3, 0: 1})

    trend = RiskForecastService(organization).overall_trend(months_back=8)

    assert trend.direction == "improving"
    assert trend.slope < -0.5


@pytest.mark.django_db
def test_a_flat_series_is_stable_rather_than_deteriorating(organization, make_findings):
    """Without a dead band, +0.02/month reads as deterioration, and an auditor
    told everything is deteriorating stops reading any of it."""
    make_findings({5: 4, 4: 4, 3: 4, 2: 4, 1: 4, 0: 4})

    assert RiskForecastService(organization).overall_trend(months_back=8).direction == "stable"


# ── Projection sanity ────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_a_projection_never_goes_negative(organization, make_findings):
    """A steep decline extrapolates below zero. Negative findings is an
    artefact of the line, not a forecast."""
    make_findings({4: 40, 3: 30, 2: 20, 1: 10, 0: 1})

    trend = RiskForecastService(organization).overall_trend(months_back=6)

    assert all(value >= 0 for _, value in trend.projection)


@pytest.mark.django_db
def test_the_projection_horizon_is_bounded(organization, make_findings):
    """Past a quarter, a linear fit on monthly audit data is extrapolating
    beyond anything it saw."""
    make_findings({5: 1, 4: 2, 3: 3, 2: 4, 1: 5, 0: 6})

    trend = RiskForecastService(organization).overall_trend(months_back=8)

    assert 1 <= len(trend.projection) <= 3


@pytest.mark.django_db
def test_quiet_months_count_as_zero_rather_than_being_dropped(organization, make_findings):
    """A gap makes a quiet month look like it never happened, which flattens a
    real improvement into a straight line."""
    make_findings({4: 10, 0: 10})

    trend = RiskForecastService(organization).overall_trend(months_back=6)
    counts = [count for _, count in trend.periods]

    assert 0 in counts, "months with no findings were dropped from the series"


# ── Honesty of the uncertainty label ─────────────────────────────────────────

@pytest.mark.django_db
def test_confidence_never_claims_more_than_moderate(organization, make_findings):
    """Twelve monthly points is not "high confidence" in any sense a
    statistician would accept, and the vocabulary should not offer the word."""
    make_findings({i: i + 1 for i in range(12)})

    trend = RiskForecastService(organization).overall_trend(months_back=12)

    assert trend.confidence in {"low", "moderate"}
    assert trend.confidence != "high"


@pytest.mark.django_db
def test_a_short_but_valid_series_is_labelled_low_not_moderate(organization, make_findings):
    make_findings({2: 1, 1: 2, 0: 3})

    trend = RiskForecastService(organization).overall_trend(months_back=4)

    assert trend.confidence == "low"


@pytest.mark.django_db
def test_the_sample_behind_the_slope_is_reported(organization, make_findings):
    """A slope with no sample size behind it is the unsourced claim, rebuilt."""
    make_findings({3: 2, 2: 4, 1: 6, 0: 8})

    trend = RiskForecastService(organization).overall_trend(months_back=6)

    assert "months" in trend.reason and "findings" in trend.reason
    assert trend.periods


# ── Tenant isolation ─────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_another_tenants_findings_do_not_enter_the_trend(organization, make_findings):
    from apps.audit.models import AuditFinding
    from apps.authentication.models import Organization

    make_findings({3: 1, 2: 1, 1: 1, 0: 1})

    other = Organization.objects.create(name="Other", name_ar="أخرى")
    for i in range(50):
        AuditFinding.objects.create(
            organization=other, rule_code="DUP-001",
            rule_name="Duplicate", message=f"other-{i}",
        )

    trend = RiskForecastService(organization).overall_trend(months_back=6)
    assert sum(count for _, count in trend.periods) == 4


# ── Breakdowns ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_rules_are_ranked_worst_first(organization, make_findings):
    make_findings({3: 1, 2: 2, 1: 3, 0: 9}, rule_code="RISING-1")
    make_findings({3: 9, 2: 6, 1: 3, 0: 1}, rule_code="FALLING-1")

    trends = RiskForecastService(organization).by_rule(months_back=6)

    assert trends[0].key == "RISING-1"
    assert trends[-1].key == "FALLING-1"


@pytest.mark.django_db
def test_findings_with_no_invoice_are_not_bucketed_under_a_blank_vendor(
    organization, make_findings
):
    make_findings({3: 2, 2: 2, 1: 2, 0: 2})  # no invoice attached

    trends = RiskForecastService(organization).by_vendor(months_back=6)

    assert all(t.key for t in trends), "a blank vendor bucket appeared"
