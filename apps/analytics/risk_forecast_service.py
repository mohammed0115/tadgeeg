"""Where is risk heading, from the findings already recorded.

The product answers "what is wrong now" well and "what is about to go wrong"
not at all. An auditor planning next quarter's engagement wants the second
question: which vendors are deteriorating, which rules are firing more often,
whether the trend is up or down.

**Deliberately not a model.** This fits a least-squares line to a monthly
series and reports the slope with the sample behind it. Given the data actually
available — a handful of months of findings per tenant — an ARIMA or a gradient
booster would produce a more impressive number with no more information in it,
and would be far harder for an auditor to challenge. ISA 500 asks for evidence
that can be evaluated; "findings rose from 4 to 11 a month over six months,
slope +1.3/month" can be. A neural forecast cannot.

**Every projection carries its own uncertainty.** A trend from three points is
reported as a trend from three points. The `confidence` field is not decoration
— a caller that renders the number without it has rebuilt the unsourced
accuracy claim this codebase spent the day removing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

logger = logging.getLogger("analytics.forecast")

#: Below this many periods a slope is arithmetic, not evidence. Two points
#: always fit a perfect line, which is exactly the trap.
MIN_PERIODS = 3

#: How far ahead a linear fit on monthly audit data can be defended. Beyond one
#: quarter the line is extrapolating past anything it saw.
MAX_HORIZON_MONTHS = 3


@dataclass
class Trend:
    """A fitted direction plus everything needed to argue with it."""

    key: str = ""
    label: str = ""
    periods: list = field(default_factory=list)     # [(period_start, count)]
    slope: float = 0.0                              # findings per month
    projection: list = field(default_factory=list)  # [(period_start, expected)]
    confidence: str = "insufficient"                # insufficient | low | moderate
    reason: str = ""

    @property
    def direction(self) -> str:
        """Deteriorating / improving / stable — with a dead band.

        Without the band, +0.02 findings per month reads as "deteriorating",
        and an auditor who is told everything is deteriorating stops reading.
        """
        if self.confidence == "insufficient":
            return "unknown"
        if self.slope > 0.5:
            return "deteriorating"
        if self.slope < -0.5:
            return "improving"
        return "stable"


class RiskForecastService:
    """Monthly finding counts → direction, per tenant."""

    def __init__(self, organization):
        self.organization = organization

    # ── public ───────────────────────────────────────────────────────────

    def overall_trend(self, *, months_back: int = 12) -> Trend:
        series = self._monthly_counts(months_back=months_back)
        return self._fit(series, key="overall", label="All findings")

    def by_rule(self, *, months_back: int = 12, limit: int = 10) -> list:
        """Worst-deteriorating rules first — the ones worth attention."""
        from apps.audit.models import AuditFinding

        # .order_by() with no arguments before .distinct() — AuditFinding.Meta
        # sets ordering = ["-last_detected_at"], and Django adds an ORDER BY
        # column into the SELECT for a DISTINCT query. The result is that
        # `.distinct()` silently does nothing: every row comes back, so this
        # looped once per FINDING rather than once per rule, ran a query each
        # time, and returned the same rule ten times over.
        codes = (
            AuditFinding.objects
            .filter(organization=self.organization)
            .order_by()
            .values_list("rule_code", flat=True)
            .distinct()
        )

        trends = []
        for code in codes:
            series = self._monthly_counts(months_back=months_back, rule_code=code)
            trend = self._fit(series, key=code, label=code)
            if trend.confidence != "insufficient":
                trends.append(trend)

        trends.sort(key=lambda t: t.slope, reverse=True)
        return trends[:limit]

    def by_vendor(self, *, months_back: int = 12, limit: int = 10) -> list:
        """Vendors whose findings are growing.

        Joined through the invoice, because a finding knows its invoice and the
        invoice knows the vendor; there is no vendor on the finding itself.
        Findings with no invoice (session- or document-level) are excluded
        rather than bucketed under a blank vendor.
        """
        from apps.audit.models import AuditFinding

        # .order_by() first — see by_rule above for why .distinct() is a no-op
        # without it on a model that declares Meta.ordering.
        vendors = (
            AuditFinding.objects
            .filter(organization=self.organization, invoice__isnull=False)
            .exclude(invoice__vendor_name="")
            .order_by()
            .values_list("invoice__vendor_name", flat=True)
            .distinct()
        )

        trends = []
        for vendor_name in vendors:
            series = self._monthly_counts(months_back=months_back, vendor_name=vendor_name)
            trend = self._fit(series, key=vendor_name, label=vendor_name)
            if trend.confidence != "insufficient":
                trends.append(trend)

        trends.sort(key=lambda t: t.slope, reverse=True)
        return trends[:limit]

    # ── internals ────────────────────────────────────────────────────────

    def _monthly_counts(self, *, months_back, rule_code=None, vendor_name=None):
        """[(month_start, count)] with empty months present as zero.

        Absent months must be zeros, not gaps: dropping them makes a quiet
        month look like it never happened and flattens a real improvement into
        a straight line.
        """
        from django.db.models import Count
        from django.db.models.functions import TruncMonth
        from django.utils import timezone

        from apps.audit.models import AuditFinding

        today = timezone.now().date()
        first_month = (today.replace(day=1) - timedelta(days=31 * (months_back - 1))).replace(day=1)

        queryset = AuditFinding.objects.filter(
            organization=self.organization,
            first_detected_at__date__gte=first_month,
        )
        if rule_code:
            queryset = queryset.filter(rule_code=rule_code)
        if vendor_name:
            queryset = queryset.filter(invoice__vendor_name=vendor_name)

        counted = {
            row["month"].date() if hasattr(row["month"], "date") else row["month"]: row["n"]
            for row in queryset.annotate(month=TruncMonth("first_detected_at"))
                                .values("month").annotate(n=Count("id"))
            if row["month"]
        }

        # The series starts at the first month that actually has data, not at
        # the window edge. A zero BETWEEN two real months is a fact — nothing
        # was found that month. A zero BEFORE the first finding ever recorded
        # is not: it is the absence of history, and padding with it drags the
        # slope toward flat. A tenant whose findings fell 14 → 1 over six
        # months came out "stable" purely because the two months before they
        # started using the product were counted as quiet ones.
        if not counted:
            return []

        start = max(first_month, min(counted))

        series, cursor = [], start
        while cursor <= today.replace(day=1):
            series.append((cursor, counted.get(cursor, 0)))
            cursor = (cursor + timedelta(days=32)).replace(day=1)
        return series

    def _fit(self, series, *, key, label):
        """Least squares on (index, count). No dependency — it is three lines."""
        # Two different reasons to refuse, and they are not interchangeable:
        # "nothing was ever recorded here" is a statement about the tenant,
        # "three months is too short to fit a line" is one about the method.
        # A caller showing the reason to a user needs the right one.
        if not series:
            return Trend(
                key=key, label=label, periods=[], confidence="insufficient",
                reason="No findings recorded in this window.",
            )

        if len(series) < MIN_PERIODS:
            return Trend(
                key=key, label=label, periods=series, confidence="insufficient",
                reason=f"Needs at least {MIN_PERIODS} months of history; got {len(series)}.",
            )

        # A series of all zeros is not a trend, it is an absence of findings.
        # Reporting "stable" for it would imply something was measured.
        if not any(count for _, count in series):
            return Trend(
                key=key, label=label, periods=series, confidence="insufficient",
                reason="No findings recorded in this window.",
            )

        n = len(series)
        xs = list(range(n))
        ys = [count for _, count in series]
        mean_x = sum(xs) / n
        mean_y = sum(ys) / n

        denominator = sum((x - mean_x) ** 2 for x in xs)
        slope = (
            sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denominator
            if denominator else 0.0
        )
        intercept = mean_y - slope * mean_x

        last_month = series[-1][0]
        projection = []
        for step in range(1, MAX_HORIZON_MONTHS + 1):
            month = (last_month + timedelta(days=32 * step)).replace(day=1)
            # Clamped at zero: a downward line eventually predicts a negative
            # number of findings, which is not a forecast, it is an artefact.
            projection.append((month, max(0.0, round(intercept + slope * (n - 1 + step), 1))))

        # Named honestly. Six monthly points is not "high confidence" in any
        # sense a statistician would accept, so the vocabulary stops at
        # "moderate" — there is no level above it here by design.
        confidence = "moderate" if n >= 6 else "low"

        return Trend(
            key=key, label=label, periods=series,
            slope=round(slope, 2), projection=projection, confidence=confidence,
            reason=f"Least-squares fit over {n} months ({sum(ys)} findings).",
        )
