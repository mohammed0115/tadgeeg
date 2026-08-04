"""Canonical rule outcome and severity, plus adapters from each engine.

The two engines disagree about both the members and the values:

    apps.auditing   passed  failed  warning  not_applicable  insufficient_data
    apps.audit      PASSED  FAILED  ERROR    SKIPPED

Neither is wrong for its own engine. `WARNING` is meaningful to a rules engine
that grades a document and meaningless to one that either ran a check or did
not; `ERROR` is the reverse. What is wrong is that both are called `RuleStatus`,
so a comparison across them fails silently — `'passed' != 'PASSED'`.

`RuleOutcome` below is the union, and the adapters map each engine onto it. The
mapping choices are the interesting part and are argued at each one, because a
wrong mapping here would be exactly the silent failure this module exists to
stop — worse, in fact, since it would look like it had been handled.
"""

from __future__ import annotations

from enum import Enum


class RuleOutcome(str, Enum):
    """What a rule concluded, across every engine.

    `str` mixin so a value can be compared to, and stored as, plain text
    without callers reaching for `.value`. The stored form is the lowercase
    one, matching what `apps.auditing` already writes to
    `AccountingRuleEvaluation.rule_status` — changing the persisted vocabulary
    would need a data migration over existing evaluations, and there is no
    reason to pay that.
    """

    PASSED = "passed"
    FAILED = "failed"

    #: The rule fired but the finding is advisory. `apps.audit` has no such
    #: state; a warning from that engine is impossible rather than absent.
    WARNING = "warning"

    #: The rule does not apply to this entity or standard — a positive
    #: statement, distinct from "we could not check".
    NOT_APPLICABLE = "not_applicable"

    #: The rule applies but the inputs were missing. Kept separate from
    #: NOT_APPLICABLE because collapsing them is the same unmeasured-is-not-zero
    #: mistake the quota, precision and benchmark code each had to avoid: one
    #: means "nothing to find here", the other means "we could not look".
    INSUFFICIENT_DATA = "insufficient_data"

    #: The rule itself broke. Maps from apps.audit's ERROR, and is NOT folded
    #: into FAILED: a crashed rule tells you nothing about the books, while a
    #: failed rule tells you something is wrong with them. Merging the two
    #: converts an engine outage into a wall of audit findings.
    ERRORED = "errored"

    #: Deliberately not run — filtered out, out of scope, disabled. Distinct
    #: from NOT_APPLICABLE, which is the engine's judgement rather than a
    #: caller's instruction.
    SKIPPED = "skipped"

    @property
    def is_actionable(self) -> bool:
        """Does an auditor need to look at this?

        WARNING is included; ERRORED is not — an engine fault is an operations
        problem, and putting it in an auditor's queue trains them to dismiss
        the queue.
        """
        return self in (RuleOutcome.FAILED, RuleOutcome.WARNING)

    @property
    def is_conclusive(self) -> bool:
        """Did the engine actually reach a judgement about the data?

        False for ERRORED, SKIPPED and INSUFFICIENT_DATA. A coverage figure
        computed without this distinction counts "we never looked" as a clean
        result — which is how a system reports high accuracy having measured
        nothing.
        """
        return self in (
            RuleOutcome.PASSED,
            RuleOutcome.FAILED,
            RuleOutcome.WARNING,
            RuleOutcome.NOT_APPLICABLE,
        )


class RuleSeverity(str, Enum):
    """How bad, across every engine.

    `apps.auditing` carries INFO and `apps.audit` does not. INFO is kept: an
    engine that has it needs somewhere to put it, and mapping INFO onto LOW
    would inflate every low-severity count with purely informational rows.
    """

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def blocks_approval(self) -> bool:
        return self is RuleSeverity.CRITICAL


# ── Adapters ─────────────────────────────────────────────────────────────────
# Each takes an engine's native value — the enum member, its `.value`, or the
# raw string read back out of the database — and returns the canonical one.
# Raw strings are accepted on purpose: values persisted before this module
# existed come back from the ORM as text, and a converter that only handles
# live enum members would fail exactly where the data is oldest.


def _normalise(value) -> str:
    if value is None:
        raise ValueError("rule status is None — an absent outcome is not an outcome")
    raw = getattr(value, "value", value)
    return str(raw).strip().lower()


#: apps.auditing already speaks the canonical vocabulary; this is a validating
#: pass-through rather than a translation.
_AUDITING = {
    "passed": RuleOutcome.PASSED,
    "failed": RuleOutcome.FAILED,
    "warning": RuleOutcome.WARNING,
    "not_applicable": RuleOutcome.NOT_APPLICABLE,
    "insufficient_data": RuleOutcome.INSUFFICIENT_DATA,
}

#: apps.audit uses uppercase names and has two states of its own.
_AUDIT_ENGINE = {
    "passed": RuleOutcome.PASSED,
    "failed": RuleOutcome.FAILED,
    "error": RuleOutcome.ERRORED,
    "skipped": RuleOutcome.SKIPPED,
}


def from_auditing_status(value) -> RuleOutcome:
    """Translate an `apps.auditing` rule status."""
    key = _normalise(value)
    try:
        return _AUDITING[key]
    except KeyError:
        raise ValueError(
            f"unknown apps.auditing rule status {key!r}. Add it to _AUDITING and "
            f"to RuleOutcome — a silent fallback here is what this module exists "
            f"to prevent."
        ) from None


def from_audit_engine_status(value) -> RuleOutcome:
    """Translate an `apps.audit` rule status."""
    key = _normalise(value)
    try:
        return _AUDIT_ENGINE[key]
    except KeyError:
        raise ValueError(
            f"unknown apps.audit rule status {key!r}. Add it to _AUDIT_ENGINE and "
            f"to RuleOutcome."
        ) from None


def to_storage_value(outcome: RuleOutcome) -> str:
    """The string to persist.

    `AccountingRuleEvaluation.rule_status` accepts the five apps.auditing
    values. ERRORED and SKIPPED have no column to go in, and Django does NOT
    validate `choices` on save — it would write them happily and nothing would
    read them back correctly. Refusing loudly beats storing a value the model
    does not know.
    """
    if outcome in (RuleOutcome.ERRORED, RuleOutcome.SKIPPED):
        raise ValueError(
            f"{outcome.value!r} has no column in AccountingRuleEvaluation.rule_status. "
            f"Record the engine fault in the run log, not as an evaluation — "
            f"Django does not validate choices on save() and would store it silently."
        )
    return outcome.value
