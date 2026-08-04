"""Anonymous cross-tenant benchmarks — "is this normal for our size?"

An auditor's most useful question about a number is comparative: 4.2 findings
per hundred invoices means nothing alone, and a great deal next to "the median
for organisations your size is 1.8".

**This is other people's data, so the design is the whole feature.** Three
constraints, each enforced by construction rather than by remembering:

1. **Opt-in.** An organisation contributes only after
   `BenchmarkParticipation.opted_in` is set. Nobody's figures enter an
   aggregate because a default was permissive.

2. **A floor of k participants.** Below `MIN_COHORT` the comparison is refused
   outright. With two contributors, one of them can subtract itself from the
   average and read the other exactly — the aggregate *is* the disclosure. This
   is the constraint most easily lost in a refactor, so it is the first thing
   the method checks and the thing most of the tests are about.

3. **Ratios, never totals.** The service returns findings-per-hundred-invoices
   and similar. Absolute counts leak size, and size plus an industry label
   often identifies a company in a market this small.

Opting in also does not let you read your own contribution back out: the caller
sees the cohort median and their own position in it, never another
organisation's row. There is no method here that returns per-organisation
values, and that absence is deliberate.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from statistics import median

logger = logging.getLogger("analytics.benchmark")

#: k-anonymity floor. Below this a "cohort average" is a lookup table.
#: 5 rather than 3: with three, two colluding participants still isolate the
#: third, and collusion between competitors sharing an auditor is not exotic.
MIN_COHORT = 5


@dataclass
class Benchmark:
    """One comparative metric, or the reason there isn't one."""

    metric: str = ""
    label: str = ""
    your_value: float | None = None
    cohort_median: float | None = None
    cohort_size: int = 0
    percentile: int | None = None
    available: bool = False
    reason: str = ""

    @property
    def standing(self) -> str:
        """Better / typical / worse — never a bare number without context."""
        if not self.available or self.your_value is None or self.cohort_median is None:
            return "unknown"
        if self.cohort_median == 0:
            return "typical" if self.your_value == 0 else "worse"
        ratio = self.your_value / self.cohort_median
        if ratio <= 0.75:
            return "better"
        if ratio >= 1.25:
            return "worse"
        return "typical"


class BenchmarkService:
    """Cohort comparisons for one organisation."""

    def __init__(self, organization):
        self.organization = organization

    def findings_per_hundred_invoices(self) -> Benchmark:
        """The headline comparison: how noisy are our books versus our peers."""
        label = "Findings per 100 invoices"

        if not self._has_opted_in(self.organization):
            return Benchmark(
                metric="findings_per_100", label=label, available=False,
                reason=(
                    "Your organisation has not opted in to anonymous "
                    "benchmarking. Nothing has been contributed and nothing "
                    "can be compared."
                ),
            )

        cohort = self._cohort_values()
        if len(cohort) < MIN_COHORT:
            # Deliberately does NOT report how many are in the cohort beyond
            # "fewer than the floor" — the exact count is itself a signal about
            # how many organisations of this size exist on the platform.
            return Benchmark(
                metric="findings_per_100", label=label, available=False,
                cohort_size=0,
                reason=(
                    f"Fewer than {MIN_COHORT} organisations have opted in. A "
                    f"cohort this small would let a participant work out an "
                    f"individual organisation's figures from the average."
                ),
            )

        mine = self._value_for(self.organization)
        if mine is None:
            return Benchmark(
                metric="findings_per_100", label=label, available=False,
                reason="Your organisation has no audited invoices yet.",
            )

        below = sum(1 for value in cohort if value < mine)
        return Benchmark(
            metric="findings_per_100",
            label=label,
            your_value=round(mine, 2),
            cohort_median=round(median(cohort), 2),
            cohort_size=len(cohort),
            percentile=int(round(100 * below / len(cohort))),
            available=True,
            reason=f"Median of {len(cohort)} opted-in organisations.",
        )

    # ── internals ────────────────────────────────────────────────────────

    @staticmethod
    def _has_opted_in(organization) -> bool:
        from apps.analytics.models import BenchmarkParticipation

        return BenchmarkParticipation.objects.filter(
            organization=organization, opted_in=True
        ).exists()

    def _value_for(self, organization):
        """Findings per 100 invoices for one organisation, or None."""
        from apps.audit.models import AuditFinding
        from apps.invoices.models import Invoice

        invoices = Invoice.objects.filter(organization=organization).count()
        if not invoices:
            return None
        findings = AuditFinding.objects.filter(organization=organization).count()
        return 100.0 * findings / invoices

    def _cohort_values(self):
        """Ratios for every opted-in organisation — values only, never keyed.

        Returning a bare list rather than a mapping is the point: there is no
        organisation identifier in the result, so no caller downstream can
        accidentally render one, and no later refactor can start returning
        "the cohort" with names attached without deliberately adding them back.
        """
        from apps.analytics.models import BenchmarkParticipation

        values = []
        participations = (
            BenchmarkParticipation.objects
            .filter(opted_in=True)
            .select_related("organization")
        )
        for participation in participations:
            value = self._value_for(participation.organization)
            if value is not None:
                values.append(value)
        return values
