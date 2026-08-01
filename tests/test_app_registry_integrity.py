"""Installed apps must never import from uninstalled ones.

This bug class has reached this codebase twice:

1. ``storage_management`` / ``audit_engine`` / ``file_management`` / ``leads`` /
   ``cms`` — recorded in the ``TADGEEG-DEPLOY-FIX`` comment in
   ``finai_backend/settings_canonical.py``. It surfaced in production as
   "table doesn't exist" 500s on a fresh Docker/MySQL deploy.
2. ``apps.jobs`` — five import sites, one of them transitive. Because
   ``apps/jobs/models.py`` declares no ``app_label``, the import raises
   ``RuntimeError`` immediately, and since ``include()`` imports a URLConf
   while the URL tree is built, it prevented the process from booting at all.
   See ``docs/adr/0003-quarantine-apps-jobs.md``.

Analysis is static (``ast``), never ``importlib``: importing the offending
module is precisely what explodes, so a dynamic check would fail with a
confusing traceback instead of a useful report.
"""

from __future__ import annotations

import ast
from pathlib import Path

from django.apps import apps as django_apps
from django.conf import settings


APPS_ROOT = Path(settings.BASE_DIR) / "apps"


def _installed_app_dirs() -> set[str]:
    """Directory names under apps/ that are registered in INSTALLED_APPS."""
    return {
        cfg.name.split(".", 1)[1]
        for cfg in django_apps.get_app_configs()
        if cfg.name.startswith("apps.")
    }


def _on_disk_app_dirs() -> set[str]:
    return {
        p.name
        for p in APPS_ROOT.iterdir()
        if p.is_dir() and not p.name.startswith("__")
    }


def _module_target(node: ast.AST) -> list[tuple[str, bool]]:
    """Return [(dotted_module, imports_models)] for an import node."""
    out: list[tuple[str, bool]] = []
    if isinstance(node, ast.ImportFrom):
        if node.level:                      # relative import — same package
            return out
        mod = node.module or ""
        if mod.startswith("apps."):
            # `from apps.jobs.models import X`  → models import
            # `from apps.jobs import models`    → models import
            imports_models = (
                ".models" in mod
                or any(a.name == "models" for a in node.names)
            )
            out.append((mod, imports_models))
    elif isinstance(node, ast.Import):
        for a in node.names:
            if a.name.startswith("apps."):
                out.append((a.name, ".models" in a.name))
    return out


def _violations() -> list[str]:
    installed = _installed_app_dirs()
    uninstalled = _on_disk_app_dirs() - installed

    problems: list[str] = []
    for app in sorted(installed):
        for py in sorted((APPS_ROOT / app).rglob("*.py")):
            if "migrations" in py.parts or "__pycache__" in py.parts:
                continue
            try:
                tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
            except SyntaxError as exc:            # pragma: no cover
                problems.append(f"{py}: unparseable ({exc})")
                continue

            # Map every node to its enclosing function, so we can tell a
            # module-level import from a deferred one.
            deferred: set[int] = set()
            for fn in ast.walk(tree):
                if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for inner in ast.walk(fn):
                        deferred.add(id(inner))

            for node in ast.walk(tree):
                if not isinstance(node, (ast.Import, ast.ImportFrom)):
                    continue
                for dotted, imports_models in _module_target(node):
                    target_app = dotted.split(".")[1] if "." in dotted else ""
                    if target_app not in uninstalled:
                        continue
                    is_deferred = id(node) in deferred
                    rel = py.relative_to(Path(settings.BASE_DIR))
                    if not is_deferred:
                        problems.append(
                            f"{rel}:{node.lineno}: module-level import of "
                            f"'{dotted}' — apps.{target_app} is NOT in "
                            f"INSTALLED_APPS. This breaks process startup if "
                            f"the module is reachable from the URLConf."
                        )
                    elif imports_models:
                        problems.append(
                            f"{rel}:{node.lineno}: deferred import of models "
                            f"from '{dotted}' — apps.{target_app} is NOT in "
                            f"INSTALLED_APPS. This raises at request time."
                        )
    return problems


def test_no_installed_app_imports_an_uninstalled_app():
    problems = _violations()
    assert not problems, (
        "Installed apps must not import from apps missing from INSTALLED_APPS.\n"
        "Either register the app (and run its migrations) or route the call "
        "through a feature flag — see core/feature_flags.py and "
        "docs/adr/0003-quarantine-apps-jobs.md.\n\n"
        + "\n".join(problems)
    )


def test_detector_actually_detects():
    """Guard the guard.

    A checker that silently matches nothing looks identical to a clean tree.
    apps.jobs is on disk and deliberately uninstalled, so the machinery must
    at minimum classify it as uninstalled.
    """
    installed = _installed_app_dirs()
    on_disk = _on_disk_app_dirs()
    assert "jobs" in on_disk, "apps/jobs/ should still exist (ADR 0003: retained)"
    assert "jobs" not in installed, "apps.jobs should remain unregistered (ADR 0003)"
    assert "billing" in installed, "sanity: apps.billing is registered"
