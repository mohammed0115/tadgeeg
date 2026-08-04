"""Views may not grow more query logic. A ratchet, not a rewrite.

`apps/frontend/page_views.py` reached 6,081 lines with 130 ORM calls in it.
Logic that lives in a view cannot be reused by an API or a Celery task without
copying it, cannot be tested without an HTTP client, and grows until nobody
reads the file whole.

Rewriting six thousand lines in one change is not a fix, it is a fresh set of
regressions on a codebase that just shipped. So this caps instead: the count
per module may fall and may not rise. New query logic goes in a selector or a
service; existing code moves when someone is already in there for another
reason.

The same shape as the silent-exception budget and the untranslated-string
budget in this suite. A ceiling that only ratchets down turns "we should
refactor that someday" into a number that cannot get worse.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

#: The measurement, taken after moving the dashboard aggregation into
#: apps/frontend/selectors/dashboard.py. Lower a number when you improve it —
#: the test tells you to. Never raise one: add a selector instead.
QUERY_BUDGET = {
    "apps/frontend/page_views.py": 114,
    "apps/reports/views.py": 35,
    "apps/invoices/views.py": 31,
    "apps/vendor_dashboard/api_views.py": 27,
    "apps/assistant/views.py": 26,
    "apps/audit/views.py": 24,
    "apps/platform_admin/api_views.py": 24,
    "apps/analytics/views.py": 22,
    "apps/compliance/views.py": 14,
    "apps/documents/typed_views.py": 14,
}

#: Everything not named above, in one number. Prevents the budget being dodged
#: by spreading new query logic across small view modules.
OTHER_MODULES_TOTAL = 314

MARKERS = (".objects.", "aggregate(", "annotate(")


def _view_modules():
    for path in sorted(REPO.glob("apps/**/*.py")):
        rel = str(path.relative_to(REPO))
        if "__pycache__" in rel or "/tests/" in rel or "migrations" in rel:
            continue
        if "view" not in path.name:
            continue
        yield rel, path


def _count(path):
    source = path.read_text(encoding="utf-8")
    return sum(source.count(marker) for marker in MARKERS)


@pytest.mark.parametrize("module,budget", sorted(QUERY_BUDGET.items()))
def test_no_view_module_grows_more_query_logic(module, budget):
    path = REPO / module
    if not path.exists():
        pytest.skip(f"{module} no longer exists — remove it from QUERY_BUDGET")

    actual = _count(path)
    assert actual <= budget, (
        f"{module} now has {actual} ORM calls, budget {budget}. Put the new "
        f"query in a selector or a service — a view should parse the request, "
        f"call something, and render the answer."
    )


@pytest.mark.parametrize("module,budget", sorted(QUERY_BUDGET.items()))
def test_the_budget_is_not_left_stale_after_an_improvement(module, budget):
    """If a module improves, the ceiling has to follow it down.

    A budget left above the real number silently buys room for a regression:
    the next person can add back exactly what was removed and stay green.
    """
    path = REPO / module
    if not path.exists():
        pytest.skip(f"{module} no longer exists")

    actual = _count(path)
    assert actual >= budget, (
        f"{module} is down to {actual} ORM calls (budget {budget}) — good. "
        f"Lower QUERY_BUDGET['{module}'] to {actual} so the gain is locked in."
    )


def test_unlisted_view_modules_do_not_absorb_the_difference():
    """Otherwise the budget is dodged by putting the logic somewhere smaller."""
    listed = set(QUERY_BUDGET)
    total = sum(
        _count(path) for rel, path in _view_modules() if rel not in listed
    )
    assert total <= OTHER_MODULES_TOTAL, (
        f"view modules outside QUERY_BUDGET now hold {total} ORM calls "
        f"(ceiling {OTHER_MODULES_TOTAL})"
    )


def test_the_dashboard_aggregation_left_the_view_module():
    """The extraction this budget was measured after.

    It was already written as pure aggregation — "caller owns caching +
    render" — and was simply in the wrong file, where only a view could reach
    it and only an HTTP client could test it.
    """
    from apps.frontend.selectors import dashboard

    assert hasattr(dashboard, "_build_dashboard_payload")
    assert hasattr(dashboard, "_dashboard_evidence_counts")

    page_views = (REPO / "apps/frontend/page_views.py").read_text(encoding="utf-8")
    assert "def _build_dashboard_payload" not in page_views, (
        "the definition is back in the view module"
    )
    assert "from apps.frontend.selectors.dashboard import" in page_views, (
        "existing callers need the re-export"
    )


def test_selectors_take_plain_arguments_not_a_request():
    """A selector that takes a request is a view with extra steps: it still
    cannot be called from a Celery task or an API serializer."""
    import inspect

    from apps.frontend.selectors import dashboard

    for name in ("_build_dashboard_payload", "_dashboard_evidence_counts"):
        params = inspect.signature(getattr(dashboard, name)).parameters
        assert "request" not in params, f"{name}() takes a request"
