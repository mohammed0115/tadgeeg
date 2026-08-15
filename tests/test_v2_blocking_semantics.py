"""A modifier may raise the score. It may not create a block.

The base engine (apps/rule_engine/risk/risk_engine.py) sets blocks_approval in
exactly three places, and every one names a rule failure:

    :802  triggers_critical_override
    :890  a rule marked blocks_approval that failed
    :926  a critical-severity failure

`grep -c ">= 75"` over that file returns 0 — there is no score threshold in it.

V2's _apply_adjustment used to add a fourth path, blocking on the composite
total. That could refuse a document with no failing rule to point at, and an
auditor asked to justify the refusal would have nothing to cite. Blocking has
to stay attributable. CTO decision, shipment 5 §1, option (a).

What the modifiers still do is unchanged and deliberate: risk_score and
risk_level move, so ranking improves, and requires_manual_review still fires on
score — review is not a refusal.

No MagicMock appears in this file. A mock answers getattr for any name, which
is exactly how the previous shipment's fix passed its own tests while calling
the wrong function. The stubs below are explicit classes with only the
attributes the code under test is entitled to read.
"""

import pytest

from apps.rule_engine.pipeline.stages.risk_engine import (
    VendorRiskModifier,
    _apply_adjustment,
)


class _Context:
    """Only what the modifiers read. Anything else raises AttributeError,
    which is the point — a stub that answers every question hides mistakes."""

    def __init__(self, vendor_context=None, erp_context=None, normalized_doc=None):
        self.vendor_context = vendor_context or {}
        self.erp_context = erp_context or {}
        self.normalized_doc = normalized_doc


def _risk(score, blocks=False):
    """The dict shape _apply_adjustment operates on."""
    return {
        "risk_score": score,
        "risk_level": "medium",
        "blocks_approval": blocks,
        "requires_manual_review": False,
    }


# ── The property this change exists for ──────────────────────────────────────

def test_modifier_cannot_create_a_block():
    """Score crosses 75 under a modifier; approval stays unblocked.

    Unapproved vendor (+15) with two flags (+20) = +35, taking 55 to 90.
    """
    modifier = VendorRiskModifier()
    context = _Context(vendor_context={
        "is_approved": False,
        "flags": ["late_payments", "compliance_issue"],
    })

    out = modifier.apply(_risk(55.0, blocks=False), context)

    assert out["risk_score"] == 90.0, "the modifier did not apply its adjustment"
    assert out["risk_level"] == "critical", "risk_level must still escalate"
    assert out["blocks_approval"] is False, (
        "a modifier created a block. Blocking must stay attributable to a "
        "failing rule — this document has none to cite."
    )


def test_blocking_rule_still_blocks():
    """The legitimate path is untouched: a block already set stays set, and a
    modifier does not clear it either."""
    modifier = VendorRiskModifier()
    context = _Context(vendor_context={"is_approved": False, "flags": []})

    out = modifier.apply(_risk(40.0, blocks=True), context)

    assert out["blocks_approval"] is True, (
        "a block set by a failing rule was cleared by a modifier"
    )
    assert out["risk_score"] == 55.0


def test_manual_review_still_triggers_on_score():
    """Review is not a refusal, so raising it on score remains correct."""
    out = _apply_adjustment(_risk(45.0, blocks=False), 10.0, ["some_reason"])

    assert out["risk_score"] == 55.0
    assert out["requires_manual_review"] is True
    assert out["blocks_approval"] is False


def test_modifier_reasons_are_still_recorded():
    """The adjustment must remain explainable even though it no longer blocks."""
    out = _apply_adjustment(_risk(10.0), 15.0, ["unapproved_vendor"])

    assert "unapproved_vendor" in out["modifier_reasons"]


# ── The guard, seen failing ──────────────────────────────────────────────────

def test_this_guard_can_fail():
    """Reintroduce the removed behaviour and confirm the guard above catches it.

    The two deleted lines are applied to a copy of the result here — the file
    is not edited. If this stops failing, test_modifier_cannot_create_a_block
    has stopped proving anything.
    """
    modifier = VendorRiskModifier()
    context = _Context(vendor_context={
        "is_approved": False,
        "flags": ["late_payments", "compliance_issue"],
    })

    out = modifier.apply(_risk(55.0, blocks=False), context)

    # The removed lines, verbatim:
    if not out.get("blocks_approval"):
        out["blocks_approval"] = out["risk_score"] >= 75

    assert out["blocks_approval"] is True, (
        "the old behaviour no longer blocks at >= 75, so this guard is no "
        "longer reproducing the defect it is meant to detect"
    )

    # And that is precisely what the real assertion refuses.
    with pytest.raises(AssertionError):
        assert out["blocks_approval"] is False


def test_the_base_engine_has_no_score_threshold():
    """The premise the whole decision rests on, asserted rather than assumed.

    If a score threshold is ever added to the base engine, blocking stops being
    attributable there too, and this change's reasoning needs revisiting.
    """
    import re
    from pathlib import Path

    base = Path(__file__).resolve().parents[1] / "apps/rule_engine/risk/risk_engine.py"
    source = base.read_text(encoding="utf-8")

    # Anchored to the start of the line so comments and the f-strings that
    # describe the behaviour ("... → blocks_approval=True, minimum HIGH") are
    # not counted as assignments. A first version of this test used a bare
    # `in`-style search and reported 7.
    assignments = [
        line.strip() for line in source.splitlines()
        if re.match(r"^\s*[\w.]*\bblocks_approval\s*=\s*True\s*(#.*)?$", line)
    ]
    assert len(assignments) == 3, (
        f"the base engine now sets blocks_approval in {len(assignments)} places, "
        f"not 3 — the decision was made against three rule-based paths"
    )
    assert ">= 75" not in source, (
        "a score threshold appeared in the base engine; blocking is no longer "
        "attributable to a rule there either"
    )
