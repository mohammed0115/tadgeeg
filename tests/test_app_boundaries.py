"""Apps that exist must be loaded, and tests must not cover code that cannot run.

`apps/reporting` was eighteen files and a thousand lines that Django never
loaded: absent from INSTALLED_APPS, no URLs, no database tables, no production
importer. Seven tests imported one of its modules and passed — reporting green
for a code path that could not execute. A dead app is cheap; a dead app with
passing tests is worse than either, because the coverage number counts it.

It also carried the other half of the `reports` / `reporting` name pair the
platform assessment flagged as a maintenance cost. Half of that confusion was
an app that did not exist.

These guards are about the *shape* of the problem, not that one directory:
  · every apps/* package is either installed or explicitly listed as inert
  · no test imports from a package Django will not load
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from django.apps import apps as django_apps
from django.conf import settings

REPO = Path(__file__).resolve().parent.parent
APPS_DIR = REPO / "apps"

#: Packages under apps/ that are deliberately not Django apps. Each needs a
#: reason: "we forgot to install it" and "this is a plain package" look
#: identical from here, and only one of them is fine.
NOT_DJANGO_APPS = {
    # Quarantined on purpose, and it says so at every call site: the recruitment
    # console in platform_admin is disabled behind a feature flag, and
    # api_urls.py notes that importing apps.jobs.views raises at import time.
    # A deliberate quarantine and a forgotten app look identical from a
    # directory listing, which is why this needs a name and a reason.
    "jobs": "quarantined — see core.feature_flags and platform_admin/api_urls.py",

    # View/URL packages with no models. Django does not need these in
    # INSTALLED_APPS: only models, migrations, app templates and signals
    # require registration, and these have none. Listing them keeps the check
    # above meaningful instead of noisy.
    "workflow": "views only, no models",
    "organization_settings": "views only, no models",
    "system_monitoring": "views only, no models",
    "organization_users": "views only, no models",
    "organization_admin": "views only, no models",

    # A Facade over apps.audit / apps.auditing / apps.audit_engine, not a
    # Django app: it holds a shared vocabulary and the adapters between the
    # engines, and deliberately re-exports no models. Installing it would
    # imply it owns tables, which is the opposite of the point.
    "audit_platform": "facade over the three audit apps — vocabulary only, no models",
}


def _package_dirs():
    return [
        path for path in APPS_DIR.iterdir()
        if path.is_dir() and (path / "__init__.py").exists() and path.name != "__pycache__"
    ]


def _installed_labels():
    return {config.name for config in django_apps.get_app_configs()}


def _defines_models(package_dir):
    models_py = package_dir / "models.py"
    if not models_py.exists():
        return False
    tree = ast.parse(models_py.read_text(encoding="utf-8"))
    return any(
        isinstance(node, ast.ClassDef)
        and any("Model" in ast.dump(base) for base in node.bases)
        for node in ast.walk(tree)
    )


def test_no_uninstalled_package_defines_models():
    """THE trap: models Django never sees.

    No migrations are generated for them, no tables exist, and the classes
    import fine — so the code reads as working and every query against it
    fails at runtime with "no such table". A views-only package outside
    INSTALLED_APPS is ordinary Python and perfectly fine; this check is
    narrowed to the case that actually breaks.
    """
    installed = _installed_labels()

    traps = [
        f"apps.{path.name} defines models but is not in INSTALLED_APPS"
        for path in _package_dirs()
        if f"apps.{path.name}" not in installed
        and path.name not in NOT_DJANGO_APPS
        and _defines_models(path)
    ]

    assert not traps, (
        "\n  ".join(traps)
        + "\nInstall it, delete it, or add it to NOT_DJANGO_APPS with the reason."
    )


def test_every_uninstalled_package_has_a_recorded_reason():
    """A deliberate quarantine and a forgotten app look identical from here."""
    installed = _installed_labels()

    unexplained = [
        f"apps.{path.name}"
        for path in _package_dirs()
        if f"apps.{path.name}" not in installed and path.name not in NOT_DJANGO_APPS
    ]

    assert not unexplained, (
        "packages under apps/ that Django does not load and nobody explained:\n  "
        + "\n  ".join(unexplained)
    )


def test_no_test_imports_from_an_uninstalled_app():
    """A passing test over unloadable code is a false green.

    Seven of them did exactly this, and the module they covered had no caller
    in production at all.
    """
    installed = _installed_labels()
    offenders = []

    pattern = re.compile(r"(?:from|import)\s+(apps\.[a-z_]+)")
    for test_file in (REPO / "tests").rglob("test_*.py"):
        text = test_file.read_text(encoding="utf-8")
        for match in pattern.finditer(text):
            package = match.group(1)
            label = package.split(".")[1]
            if package not in installed and label not in NOT_DJANGO_APPS:
                line = text[:match.start()].count("\n") + 1
                offenders.append(f"{test_file.relative_to(REPO)}:{line} → {package}")

    assert not offenders, (
        "tests importing from apps Django does not load:\n  " + "\n  ".join(offenders)
    )


def test_the_reports_reporting_pair_is_gone():
    """Named directly: `reports` and `reporting` differed by one character and
    did unrelated things. Only one of them was ever real."""
    assert not (APPS_DIR / "reporting").exists(), (
        "apps/reporting is back — if the audit-engine dashboard is being built, "
        "it belongs in apps/audit_engine, not in a package one character away "
        "from apps/reports"
    )
    assert (APPS_DIR / "reports").exists()


def test_the_moved_module_landed_somewhere_django_loads():
    from apps.audit_engine import dashboard_selectors

    assert hasattr(dashboard_selectors, "get_org_dashboard_metrics")
    assert "apps.audit_engine" in _installed_labels()


def test_the_moved_module_did_not_overwrite_the_existing_selectors():
    """`selectors.py` already existed in audit_engine with different functions.

    Dropping the moved file on top of it would have deleted them silently —
    both files are named for the same concept and answer different questions.
    """
    from apps.audit_engine import selectors

    for name in ("get_jobs_for_org",):
        assert hasattr(selectors, name), f"audit_engine.selectors lost {name}()"


# ── Overlapping app names that are all real ──────────────────────────────────

@pytest.mark.parametrize("label", ["apps.audit", "apps.auditing", "apps.audit_engine"])
def test_the_three_audit_apps_are_all_genuinely_installed(label):
    """audit / auditing / audit_engine remain three separate apps, deliberately.

    Unlike `reporting`, all three are installed, hold models, and own live
    tables with tenant data. Merging them is a data migration across 43 models,
    not a rename, and doing it to tidy a naming collision would risk real rows
    to buy readability. The names stay; what each owns is documented in its
    AppConfig.
    """
    assert label in _installed_labels()


def test_each_overlapping_audit_app_says_what_it_owns():
    """The confusion is cheap to fix at the point of reading.

    A developer opening apps/auditing should learn in one line why it is not
    apps/audit, instead of inferring it from 78 files.
    """
    missing = []
    for name in ("audit", "auditing", "audit_engine", "reports"):
        apps_py = APPS_DIR / name / "apps.py"
        if not apps_py.exists():
            missing.append(f"apps/{name}/apps.py is absent")
            continue
        tree = ast.parse(apps_py.read_text(encoding="utf-8"))
        if not ast.get_docstring(tree):
            missing.append(f"apps/{name}/apps.py has no module docstring")

    assert not missing, (
        "apps with overlapping names and no note saying what they own:\n  "
        + "\n  ".join(missing)
    )
