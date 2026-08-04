"""One vocabulary across the audit engines, and the trap it closes.

`RuleStatus` is defined twice with different members and different values.
`auditing.RuleStatus.PASSED == audit.RuleStatus.PASSED` is False — one is
`'passed'`, the other `'PASSED'` — so a caller comparing a result from one
engine against the other's enum gets no match, no exception and no log. The
branch simply never runs.

Nothing crosses the two today, which makes it a trap rather than a bug. The
tests below pin the trap itself (so nobody "tidies" the two enums into
agreement by accident and thinks the problem was cosmetic), the canonical
vocabulary that replaces it, and the distinctions inside that vocabulary that
are easy to collapse and expensive to get wrong.
"""

import pytest

from apps.audit_platform import (
    RuleOutcome,
    RuleSeverity,
    from_audit_engine_status,
    from_auditing_status,
    to_storage_value,
)


# ── The defect, pinned ───────────────────────────────────────────────────────

def test_the_two_engines_genuinely_disagree():
    """Not a story about the past — assert it, so the shape stays visible."""
    from apps.audit.rules.base_rule import RuleStatus as EngineB
    from apps.auditing.accounting_rules.enums import RuleStatus as EngineA

    assert EngineA is not EngineB
    assert EngineA.PASSED != EngineB.PASSED, (
        "the two RuleStatus enums now agree — if they were unified, this facade "
        "can be simplified; if they were made to compare equal by accident, that "
        "is worse than the original problem"
    )
    assert not hasattr(EngineB, "WARNING"), (
        "apps.audit gained WARNING — _AUDIT_ENGINE needs the mapping"
    )


def test_both_engines_land_on_the_same_canonical_value():
    """The point of the facade in one line."""
    from apps.audit.rules.base_rule import RuleStatus as EngineB
    from apps.auditing.accounting_rules.enums import RuleStatus as EngineA

    assert from_auditing_status(EngineA.PASSED) is from_audit_engine_status(EngineB.PASSED)
    assert from_auditing_status(EngineA.FAILED) is from_audit_engine_status(EngineB.FAILED)


# ── Adapters ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value,expected", [
    ("passed", RuleOutcome.PASSED),
    ("warning", RuleOutcome.WARNING),
    ("not_applicable", RuleOutcome.NOT_APPLICABLE),
    ("insufficient_data", RuleOutcome.INSUFFICIENT_DATA),
])
def test_auditing_values_translate(value, expected):
    assert from_auditing_status(value) is expected


@pytest.mark.parametrize("value,expected", [
    ("PASSED", RuleOutcome.PASSED),
    ("ERROR", RuleOutcome.ERRORED),
    ("SKIPPED", RuleOutcome.SKIPPED),
])
def test_audit_engine_values_translate(value, expected):
    assert from_audit_engine_status(value) is expected


def test_raw_strings_from_the_database_are_accepted():
    """Rows written before this module existed come back as plain text. A
    converter that only handled live enum members would fail exactly where the
    data is oldest."""
    assert from_auditing_status("PASSED") is RuleOutcome.PASSED
    assert from_auditing_status("  warning  ") is RuleOutcome.WARNING


def test_an_unknown_status_raises_rather_than_falling_back():
    """A default of PASSED would turn an unmapped state into a clean audit."""
    with pytest.raises(ValueError, match="unknown"):
        from_auditing_status("probably_fine")
    with pytest.raises(ValueError, match="unknown"):
        from_audit_engine_status("MAYBE")


def test_none_is_refused():
    with pytest.raises(ValueError, match="None"):
        from_auditing_status(None)


# ── The distinctions worth keeping ───────────────────────────────────────────

def test_a_crashed_rule_is_not_a_failed_rule():
    """Folding ERRORED into FAILED converts an engine outage into a wall of
    audit findings — and an auditor chasing a hundred phantom problems."""
    assert RuleOutcome.ERRORED is not RuleOutcome.FAILED
    assert RuleOutcome.FAILED.is_actionable
    assert not RuleOutcome.ERRORED.is_actionable


def test_not_applicable_and_insufficient_data_stay_apart():
    """"Nothing to find here" and "we could not look" are different facts —
    the same distinction the quota, precision and benchmark code each had to
    protect."""
    assert RuleOutcome.NOT_APPLICABLE is not RuleOutcome.INSUFFICIENT_DATA
    assert RuleOutcome.NOT_APPLICABLE.is_conclusive
    assert not RuleOutcome.INSUFFICIENT_DATA.is_conclusive


def test_inconclusive_outcomes_do_not_count_as_clean():
    """A coverage figure that counts these as passes reports high accuracy
    having measured nothing."""
    for outcome in (RuleOutcome.ERRORED, RuleOutcome.SKIPPED, RuleOutcome.INSUFFICIENT_DATA):
        assert not outcome.is_conclusive


def test_a_warning_reaches_the_auditor():
    assert RuleOutcome.WARNING.is_actionable
    assert RuleOutcome.WARNING.is_conclusive


# ── Storage ──────────────────────────────────────────────────────────────────

def test_storage_values_match_the_column_the_model_declares():
    """If these drift, Django writes the new value anyway — it does not
    validate `choices` on save() — and nothing reads it back correctly."""
    from apps.auditing.models import AccountingRuleEvaluation

    allowed = {choice[0] for choice in AccountingRuleEvaluation.RuleStatus.choices}
    for outcome in RuleOutcome:
        if outcome in (RuleOutcome.ERRORED, RuleOutcome.SKIPPED):
            continue
        assert to_storage_value(outcome) in allowed, (
            f"{outcome.value!r} has no column to go in"
        )


@pytest.mark.parametrize("outcome", [RuleOutcome.ERRORED, RuleOutcome.SKIPPED])
def test_storing_an_engine_fault_as_an_evaluation_is_refused(outcome):
    """Django would store it silently. Refusing loudly beats a row nothing
    can read back."""
    with pytest.raises(ValueError, match="no column"):
        to_storage_value(outcome)


# ── Severity ─────────────────────────────────────────────────────────────────

def test_info_survives_the_union():
    """apps.auditing has INFO and apps.audit does not. Mapping INFO onto LOW
    would inflate every low-severity count with informational rows."""
    assert RuleSeverity.INFO is not RuleSeverity.LOW


def test_only_critical_blocks_approval():
    assert RuleSeverity.CRITICAL.blocks_approval
    for severity in (RuleSeverity.INFO, RuleSeverity.LOW,
                     RuleSeverity.MEDIUM, RuleSeverity.HIGH):
        assert not severity.blocks_approval


# ── The facade's own boundaries ──────────────────────────────────────────────

def test_the_facade_exposes_one_import_path():
    import apps.audit_platform as facade

    for name in ("RuleOutcome", "RuleSeverity", "from_auditing_status",
                 "from_audit_engine_status", "to_storage_value"):
        assert hasattr(facade, name)


def test_the_facade_does_not_re_export_models():
    """Importing a model through a facade breaks related_name reasoning,
    migration detection and select_related autocompletion, and buys nothing:
    a model is already one name from one app."""
    import apps.audit_platform as facade

    for name in dir(facade):
        attribute = getattr(facade, name)
        assert not (
            isinstance(attribute, type)
            and hasattr(attribute, "_meta")
            and hasattr(attribute._meta, "db_table")
        ), f"{name} is a Django model — the facade is for vocabulary, not models"


def test_the_three_apps_are_still_three_apps():
    """The facade unifies the interface. It is not a merge, and it must not
    become a reason to think one happened: the tables are still separate and
    still hold live tenant data.
    """
    from django.apps import apps as django_apps

    installed = {config.name for config in django_apps.get_app_configs()}
    for label in ("apps.audit", "apps.auditing", "apps.audit_engine"):
        assert label in installed
