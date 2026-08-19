"""A fault must never render as a missing feature.

Twice on production a swallowed exception cost hours in the wrong direction:

  · `entrypoint.sh` caught everything in its MySQL wait loop and printed
    "Database unavailable", so a *file permission* error looked like a database
    outage;
  · `billing/context_processors.py` answered every exception with the empty
    namespace used for logged-out visitors, so unapplied migrations looked like
    the الفوترة والاشتراك menu had been removed.

Neither raised. Neither logged. Both were `except Exception:` followed by a
fallback value.

A repo-wide ban is not honest here — 287 such handlers predate this work, many
of them fine (an optional import, a best-effort cache read). A permanently red
test is a test people learn to ignore. So the gap is measured instead: it may
exist, it may not GROW. New code has to log, re-raise, or narrow the catch.

The rule for the handlers that remain: if the fallback value is
indistinguishable from a legitimate empty result, the failure has to be in the
log. Otherwise nobody can tell "no data" from "broken".
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

#: Measured after AuditEngine deletion. The AST scanner found 11 fewer silent
#: handlers than the pre-delete tree (282 -> 271), all inside deleted legacy
#: rule modules; the remaining code's count was unchanged. This 284 -> 273
#: reduction records that deletion rather than creating new budget headroom.
#: Lowering this number is the only permitted direction.
SILENT_HANDLER_BUDGET = 261

_BROAD = {"Exception", "BaseException"}
_HANDLED = ("'exception'", "'error'", "'warning'", "'critical'",
            "Raise", "capture_exception")


def _scan():
    """Broad handlers whose body neither logs nor re-raises."""
    silent = []
    for pattern in ("apps/**/*.py", "core/**/*.py", "navigation/*.py"):
        for path in REPO.glob(pattern):
            rel = str(path.relative_to(REPO))
            if "/migrations/" in rel or "/tests/" in rel:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ExceptHandler):
                    continue
                caught = node.type
                broad = caught is None or (
                    isinstance(caught, ast.Name) and caught.id in _BROAD
                )
                if not broad:
                    continue
                body = ast.dump(ast.Module(body=node.body, type_ignores=[]))
                if not any(marker in body for marker in _HANDLED):
                    silent.append(f"{rel}:{node.lineno}")
    return silent


def test_silent_exception_handlers_do_not_grow():
    silent = _scan()
    worst = Counter(entry.rsplit(":", 1)[0] for entry in silent).most_common(5)
    assert len(silent) <= SILENT_HANDLER_BUDGET, (
        f"silent broad `except` handlers grew to {len(silent)} "
        f"(budget {SILENT_HANDLER_BUDGET}).\n"
        f"Log it, re-raise it, or catch the specific exception you mean.\n"
        f"Largest files:\n  "
        + "\n  ".join(f"{count:3}  {name}" for name, count in worst)
    )


def test_the_budget_is_kept_honest():
    """If the count falls, the budget must follow it down.

    Otherwise the guard quietly gains slack and stops catching anything, which
    is how a ratchet becomes decoration.
    """
    silent = _scan()
    assert len(silent) >= SILENT_HANDLER_BUDGET - 10, (
        f"only {len(silent)} silent handlers remain (budget "
        f"{SILENT_HANDLER_BUDGET}). Lower SILENT_HANDLER_BUDGET to "
        f"{len(silent)} so the gap cannot silently reopen."
    )


# ── The two handlers that caused real outages stay fixed ─────────────────────

def test_the_billing_context_processor_logs_and_keeps_the_nav():
    source = (REPO / "apps/billing/context_processors.py").read_text(encoding="utf-8")
    assert "logger.exception" in source
    assert "show_billing_nav=show_nav" in source, (
        "the failure path must keep the menu visible — hiding it is what made "
        "a database fault look like a removed feature"
    )


def test_the_isa_calculation_failures_are_logged():
    """Materiality (ISA 320) and sampling (ISA 530) render blank on failure.

    A blank panel is indistinguishable from "not calculated yet", so an auditor
    cannot tell a bad benchmark from a broken feature. The log is the only
    place that distinction survives.
    """
    source = (REPO / "apps/frontend/page_views.py").read_text(encoding="utf-8")
    for needle in ("materiality calculation failed",
                   "sampling failed",
                   "error projection failed"):
        assert needle in source, f"missing log line: {needle}"


def test_optional_imports_catch_ImportError_and_not_Exception():
    """`except Exception` around an import also swallows faults *inside* it.

    A module that raises while being imported — a bad migration state, a
    misconfigured setting — then presents as "the app isn't installed", and the
    page renders as if there were simply no data.
    """
    source = (REPO / "apps/frontend/page_views.py").read_text(encoding="utf-8")
    for service in ("FindingFeedbackService", "AIValidationRun"):
        block = source.split(f"import {service}")[1][:160]
        assert "except ImportError" in block, (
            f"the optional import of {service} catches too much"
        )
