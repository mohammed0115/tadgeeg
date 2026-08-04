"""Why did this rule fire?

An auditor signing off on a finding is exercising professional judgement, and
ISA does not let them delegate it to a machine. To exercise it they need to see
what the engine actually compared — which field, what it expected, what it
found — not a sentence asserting a conclusion.

The engine already produces most of this and then loses it. Two producers write
findings, and they carry different amounts of detail:

  · ``apps.rule_engine`` builds ``EvidenceItem`` objects with ``field_name``,
    ``expected_value`` and ``actual_value``. Full explanation available.
  · ``core.services.invoice_validator`` builds ``{passed, description, message,
    severity}`` — a rendered Arabic sentence and nothing structured.

Both land in ``AuditFinding.details``, and the UI showed neither. This module
normalises whatever is there into one shape.

**It does not invent the missing parts.** Where a producer never recorded an
expected value, the explanation says so rather than reconstructing something
plausible from the message text. A fabricated "expected: 15%" under an audit
finding would be the same failure as the hardcoded 98% accuracy figure, in a
place where it does more damage.
"""

from __future__ import annotations

from django.utils.translation import gettext as _


class Explanation:
    """What the engine compared, in a shape a template can render.

    ``complete`` is False when the producing rule did not record structured
    evidence. Callers must show that state, not hide it — "we cannot show you
    the comparison" is a fact the auditor needs.
    """

    __slots__ = ("rule_code", "rule_name", "severity", "message",
                 "checks", "complete", "source")

    def __init__(self, *, rule_code, rule_name, severity, message,
                 checks, complete, source):
        self.rule_code = rule_code
        self.rule_name = rule_name
        self.severity = severity
        self.message = message
        self.checks = checks
        self.complete = complete
        self.source = source

    def as_dict(self):
        return {
            "rule_code": self.rule_code,
            "rule_name": self.rule_name,
            "severity": self.severity,
            "message": self.message,
            "checks": self.checks,
            "complete": self.complete,
            "source": self.source,
        }


def explain(finding) -> Explanation:
    """Normalise ``finding.details`` into a structured explanation."""
    details = finding.details if isinstance(finding.details, dict) else {}

    checks = _from_evidence(details)
    complete = bool(checks)
    if not complete:
        checks = _from_flat_detail(details)

    return Explanation(
        rule_code=finding.rule_code,
        rule_name=finding.rule_name or details.get("description") or finding.rule_code,
        severity=finding.severity,
        message=finding.message,
        checks=checks,
        complete=complete,
        source=finding.source,
    )


def _from_evidence(details):
    """The rule_engine path: EvidenceItem dicts with expected vs actual.

    Only entries that carry an actual comparison are kept. An EvidenceItem
    with neither an expected nor an actual value explains nothing, and padding
    the list with those would make an incomplete explanation look complete.
    """
    evidence = details.get("evidence")
    if not isinstance(evidence, list):
        return []

    checks = []
    for item in evidence:
        if not isinstance(item, dict):
            continue
        expected = item.get("expected_value")
        actual = item.get("actual_value")
        if expected is None and actual is None:
            continue
        checks.append({
            "field": item.get("field_name_ar") or item.get("field_name") or "",
            "expected": expected,
            "actual": actual,
            "kind": item.get("evidence_type") or "comparison",
            "note": item.get("description_ar") or item.get("description") or "",
        })
    return checks


def _from_flat_detail(details):
    """The invoice_validator path: a rendered sentence, no structured fields.

    Returns the sentence marked as narrative so the template can present it as
    the rule's own words rather than as a comparison the auditor can check.
    Deliberately does NOT parse values out of the Arabic text: a regex that
    guessed "the expected VAT was 15%" from a message would be inventing
    evidence, and this is the one place in the product where that is least
    acceptable.
    """
    message = details.get("message") or details.get("description")
    if not message:
        return []
    return [{
        "field": "",
        "expected": None,
        "actual": None,
        "kind": "narrative",
        "note": message,
    }]


def incompleteness_reason():
    """Shown when ``complete`` is False. One sentence, no euphemism."""
    return _(
        "This rule did not record which field it compared, so the check "
        "cannot be shown in full. Review the invoice directly before relying "
        "on this finding."
    )
