"""Pin the URL invariants that three "IMPORTANT" comments currently protect.

finai_backend/urls.py mounts the frontend at the root with 150 patterns
(line 107) and registers eight API groups AFTER it. Three comments in that file
warn about the ordering. A comment cannot fail, and the failures it warns about
are silent: the wrong ordering does not raise, it just resolves somewhere else.

The most dangerous one is /dashboard/. The frontend declares `dashboard/` as an
EXACT path and vendor_dashboard mounts on the same prefix afterwards, so the
two coexist by luck of ordering. Turning the frontend's entry into an include,
or adding `dashboard/<...>` to it, hides the organisation dashboard entirely —
no error, no exception, just pages that stop existing.

Every route below was measured with resolve() before being asserted, not copied
from the documentation. One documented route (/api/v1/audit/run/) does not
exist and is recorded in the report rather than asserted into a guard.
"""

import pytest
from django.urls import Resolver404, resolve


def _app(path):
    """(app_name, url_name) for a path, or a clear failure."""
    match = resolve(path)
    return match.app_name or "", match.url_name or ""


# ── Invariant 1: /dashboard/ splits between two apps ─────────────────────────

def test_dashboard_splits_between_two_apps():
    """The exact path belongs to the frontend; anything under it does not.

    If someone converts the frontend's `dashboard/` to an include, or adds
    `dashboard/<...>`, the second assertion starts resolving into the frontend
    and the organisation dashboard disappears without raising anything.
    """
    app, name = _app("/dashboard/")
    assert app == "frontend", f"/dashboard/ resolved into {app!r}, not frontend"
    assert name == "dashboard"

    app, _name = _app("/dashboard/files/")
    assert app == "vendor_dashboard", (
        f"/dashboard/files/ resolved into {app!r}, not vendor_dashboard — the "
        f"frontend has swallowed the prefix and the organisation dashboard is "
        f"unreachable"
    )


# ── Invariant 2: API groups are not shadowed by the catch-all ───────────────

@pytest.mark.parametrize("path,expected_name", [
    ("/api/v1/invoices/", "invoice-list"),
    ("/api/v1/reports/", "report-list"),
])
def test_api_routes_are_not_shadowed_by_the_catch_all(path, expected_name):
    """These are registered after the frontend's root mount (line 107).

    They survive only because the frontend declares `api/` as an exact path.
    Any new prefix pattern there beginning with `api/` takes all of them.
    """
    app, name = _app(path)
    assert app != "frontend", f"{path} was captured by the frontend catch-all"
    assert name == expected_name


def test_the_rule_engine_api_is_reachable():
    app, _name = _app("/api/v1/rule-engine/runs/")
    assert app != "frontend", "the rule-engine API was captured by the frontend"


def test_the_audit_api_is_reachable():
    """Measured, not assumed: the audit API mounts at api/v1/audit/ and its
    routes are cases/ and <uuid:pk>/. The documented /api/v1/audit/run/ does
    not exist — asserting it would pin a route nobody serves."""
    app, _name = _app("/api/v1/audit/cases/")
    assert app != "frontend", "the audit API was captured by the frontend"


# ── Invariant 3: platform-admin precedes the catch-all ──────────────────────

def test_platform_admin_precedes_the_catch_all():
    app, _name = _app("/platform-admin/")
    assert app == "platform_admin", (
        f"/platform-admin/ resolved into {app!r} — it is now behind the "
        f"frontend catch-all"
    )


def test_the_marketing_api_page_still_resolves_to_frontend():
    """`/api/` is a marketing page, not an API root. It must stay exact: making
    it a prefix is what would shadow the eight API groups above."""
    app, name = _app("/api/")
    assert app == "frontend"
    assert name == "api_page"


# ── The guard, seen failing ──────────────────────────────────────────────────

def test_this_guard_can_fail():
    """Reorder the URLConf so the frontend comes first, and confirm the
    assertions above stop holding. urls.py is not edited — the resolver is
    rebuilt from a reordered pattern list in memory.
    """
    from django.urls.resolvers import URLResolver

    from finai_backend import urls as root_urls

    patterns = list(root_urls.urlpatterns)

    def _is_frontend_root(pattern):
        return (isinstance(pattern, URLResolver)
                and str(pattern.pattern) == ""
                and "frontend" in str(getattr(pattern, "urlconf_name", "")))

    frontend = [p for p in patterns if _is_frontend_root(p)]
    assert frontend, (
        "no root-mounted frontend resolver found — the shape of urls.py "
        "changed and this guard needs rewriting rather than deleting"
    )

    reordered = frontend + [p for p in patterns if p not in frontend]
    resolver = URLResolver(root_urls.urlpatterns[0].pattern.__class__(""), reordered)

    # With the frontend first, a path it does not define raises rather than
    # reaching the API group that would have served it.
    with pytest.raises(Resolver404):
        resolver.resolve("/api/v1/invoices/")
