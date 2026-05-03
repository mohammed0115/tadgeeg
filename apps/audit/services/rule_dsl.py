"""
Custom rule DSL evaluator — Phase 2.2 of the Enterprise Roadmap.

Spec
----
A rule is a JSON object with two top-level keys:

    {
      "when": <condition>,
      "then": {"action": "flag", "severity": "high", "message": "..."}
    }

A *condition* is one of:

  • A leaf  →  {"field": "...", "op": "...", "value": ...}
  • An AND →  {"all": [<condition>, <condition>, ...]}
  • An OR  →  {"any": [<condition>, <condition>, ...]}
  • A NOT  →  {"not": <condition>}

Operators (per leaf condition's ``op`` field):

  Numeric / comparison: >  <  >=  <=  ==  !=
  String              : contains  not_contains  starts_with  ends_with  regex
  List / membership   : in  not_in
  Existence           : is_empty  is_set

The evaluator is *sandboxed*:

  • Only operates on a plain dict input — never imports app code.
  • All field access goes through ``_get(invoice, path)`` which supports
    dotted notation (``"line_items.0.amount"``) but never executes Python
    expressions or eval(). Regex flags are restricted to ``IGNORECASE``.
  • Bounded recursion depth (``MAX_DEPTH``) so a malicious nesting can't
    blow the stack.

Designed to evaluate one rule against ~100 invoices in < 50 ms — keeping
the "preview-against-sample" flow under 5 s easily.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

logger = logging.getLogger("finai")

MAX_DEPTH = 10
COMPARISON_OPS = {">", "<", ">=", "<=", "==", "!="}
STRING_OPS     = {"contains", "not_contains", "starts_with", "ends_with", "regex"}
LIST_OPS       = {"in", "not_in"}
EXISTENCE_OPS  = {"is_empty", "is_set"}
ALL_OPS = COMPARISON_OPS | STRING_OPS | LIST_OPS | EXISTENCE_OPS


# ─────────────────────────────────────────────────────────────────────────────
# DSL validation
# ─────────────────────────────────────────────────────────────────────────────

class DSLValidationError(ValueError):
    """Raised when a rule's DSL is syntactically invalid."""


def validate_dsl(dsl: dict) -> None:
    """Walk the DSL and raise DSLValidationError on the first problem.

    Validating up-front means the visual builder gets clear errors instead
    of opaque KeyError / TypeError stack traces during evaluation.
    """
    if not isinstance(dsl, dict):
        raise DSLValidationError("DSL must be a JSON object")

    when = dsl.get("when")
    then = dsl.get("then")
    if when is None or then is None:
        raise DSLValidationError("DSL must contain both 'when' and 'then' keys")

    _validate_condition(when, depth=0)
    _validate_then(then)


def _validate_condition(node: Any, depth: int) -> None:
    if depth > MAX_DEPTH:
        raise DSLValidationError(f"Condition tree exceeds maximum depth of {MAX_DEPTH}")
    if not isinstance(node, dict):
        raise DSLValidationError("Each condition node must be a JSON object")

    keys = set(node.keys())
    combinator_keys = keys & {"all", "any", "not"}
    if len(combinator_keys) > 1:
        raise DSLValidationError(
            f"Condition node mixes combinators: {sorted(combinator_keys)}"
        )

    if "all" in node:
        if not isinstance(node["all"], list) or not node["all"]:
            raise DSLValidationError("'all' must be a non-empty list")
        for child in node["all"]:
            _validate_condition(child, depth + 1)
        return

    if "any" in node:
        if not isinstance(node["any"], list) or not node["any"]:
            raise DSLValidationError("'any' must be a non-empty list")
        for child in node["any"]:
            _validate_condition(child, depth + 1)
        return

    if "not" in node:
        _validate_condition(node["not"], depth + 1)
        return

    # Leaf condition.
    if "field" not in node or "op" not in node:
        raise DSLValidationError(
            f"Leaf condition must have 'field' and 'op' (got keys: {sorted(node.keys())})"
        )

    op = node["op"]
    if op not in ALL_OPS:
        raise DSLValidationError(
            f"Unknown operator '{op}'. Allowed: {sorted(ALL_OPS)}"
        )

    if op not in EXISTENCE_OPS and "value" not in node:
        raise DSLValidationError(f"Operator '{op}' requires a 'value' key")

    if op == "regex":
        try:
            re.compile(str(node.get("value", "")))
        except re.error as exc:
            raise DSLValidationError(f"Invalid regex: {exc}") from exc


def _validate_then(then: Any) -> None:
    if not isinstance(then, dict):
        raise DSLValidationError("'then' must be a JSON object")
    action = then.get("action")
    if action not in {"flag", "block", "warn"}:
        raise DSLValidationError(
            f"'then.action' must be flag|block|warn (got {action!r})"
        )
    sev = then.get("severity", "medium")
    if sev not in {"low", "medium", "high", "critical"}:
        raise DSLValidationError(
            f"'then.severity' must be low|medium|high|critical (got {sev!r})"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Field access
# ─────────────────────────────────────────────────────────────────────────────

def _get(doc: dict, path: str) -> Any:
    """Resolve a dotted path inside a dict — never executes attribute access.

    ``_get({"a": {"b": [{"c": 1}]}}, "a.b.0.c") == 1``
    Returns None for any missing segment.
    """
    cur: Any = doc
    if not isinstance(path, str) or not path:
        return None
    for part in path.split("."):
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return cur


# ─────────────────────────────────────────────────────────────────────────────
# Operator implementations
# ─────────────────────────────────────────────────────────────────────────────

def _to_decimal(v: Any):
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _eval_leaf(field_value: Any, op: str, expected: Any) -> bool:
    if op in EXISTENCE_OPS:
        is_set = (field_value is not None and field_value != "" and field_value != [])
        return is_set if op == "is_set" else (not is_set)

    if op in COMPARISON_OPS:
        # Try numeric comparison first; fall back to string compare so date
        # strings still compare lexicographically (ISO dates sort correctly).
        a = _to_decimal(field_value)
        b = _to_decimal(expected)
        if a is not None and b is not None:
            if op == ">":  return a >  b
            if op == "<":  return a <  b
            if op == ">=": return a >= b
            if op == "<=": return a <= b
            if op == "==": return a == b
            if op == "!=": return a != b
        a_s, b_s = str(field_value or ""), str(expected or "")
        if op == "==": return a_s == b_s
        if op == "!=": return a_s != b_s
        if op == ">":  return a_s >  b_s
        if op == "<":  return a_s <  b_s
        if op == ">=": return a_s >= b_s
        if op == "<=": return a_s <= b_s
        return False

    if op in STRING_OPS:
        s = str(field_value or "")
        e = str(expected or "")
        if op == "contains":     return e in s
        if op == "not_contains": return e not in s
        if op == "starts_with":  return s.startswith(e)
        if op == "ends_with":    return s.endswith(e)
        if op == "regex":
            try:
                return bool(re.search(e, s))
            except re.error:
                return False

    if op in LIST_OPS:
        # ``expected`` is expected to be a JSON list; comparison is on str.
        items = expected if isinstance(expected, list) else [expected]
        items_s = {str(x) for x in items}
        in_set = str(field_value or "") in items_s
        return in_set if op == "in" else (not in_set)

    return False


# ─────────────────────────────────────────────────────────────────────────────
# Evaluation
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RuleEvalResult:
    triggered: bool
    action: str = ""
    severity: str = ""
    message: str = ""
    explanation: str = ""

    def to_dict(self) -> dict:
        return {
            "triggered":   self.triggered,
            "action":      self.action,
            "severity":    self.severity,
            "message":     self.message,
            "explanation": self.explanation,
        }


def _eval_condition(node: dict, doc: dict, depth: int = 0) -> bool:
    if depth > MAX_DEPTH:
        return False

    if "all" in node:
        return all(_eval_condition(c, doc, depth + 1) for c in node["all"])
    if "any" in node:
        return any(_eval_condition(c, doc, depth + 1) for c in node["any"])
    if "not" in node:
        return not _eval_condition(node["not"], doc, depth + 1)

    field_value = _get(doc, node.get("field", ""))
    return _eval_leaf(field_value, node.get("op", ""), node.get("value"))


def evaluate(dsl: dict, doc: dict) -> RuleEvalResult:
    """Evaluate one rule's DSL against one document. Never raises."""
    try:
        validate_dsl(dsl)
    except DSLValidationError as exc:
        return RuleEvalResult(triggered=False, explanation=f"invalid DSL: {exc}")

    try:
        triggered = _eval_condition(dsl["when"], doc)
    except Exception as exc:   # never let the audit engine die on a bad rule
        logger.warning("[rule_dsl] evaluation error: %s", exc)
        return RuleEvalResult(triggered=False, explanation=f"runtime error: {exc}")

    then = dsl.get("then", {})
    return RuleEvalResult(
        triggered=triggered,
        action=str(then.get("action", "flag")),
        severity=str(then.get("severity", "medium")),
        message=str(then.get("message", "")),
        explanation=("rule matched" if triggered else "rule not matched"),
    )


def sandbox_run(dsl: dict, sample: list[dict]) -> dict:
    """Run a rule against a sample of documents — used by the visual builder
    "Test" button. Returns aggregate stats + per-doc rows."""
    try:
        validate_dsl(dsl)
    except DSLValidationError as exc:
        return {
            "ok": False, "error": str(exc), "rows": [],
            "triggered_count": 0, "sample_size": len(sample),
        }

    rows = []
    triggered_count = 0
    for doc in sample:
        result = _eval_condition(dsl["when"], doc)
        if result:
            triggered_count += 1
        rows.append({
            "id":         doc.get("id") or doc.get("invoice_id") or "",
            "label":      doc.get("invoice_number") or doc.get("vendor_name") or "—",
            "triggered":  result,
        })

    return {
        "ok":             True,
        "rows":           rows,
        "triggered_count": triggered_count,
        "sample_size":    len(sample),
        "trigger_rate":   round(triggered_count / max(len(sample), 1) * 100, 1),
    }
