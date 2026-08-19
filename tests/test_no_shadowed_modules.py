"""No module may sit beside a directory of the same name.

`apps/reports/` held both `views.py` (78 KB, imported by its urlconf) and a
`views/` directory containing `executive_report_views.py`. Python resolves the
module, so nothing under `views/` could be imported by any path in the project.
The file was not merely unrouted — it was unloadable.

Two things followed, and the second is the reason this guard exists.

A security fix was recorded against that file. An organisation scope filter was
added to `ExecutiveReportDetailView._fetch_document_audit_data` and logged as
SEC-002, resolved. It never ran once, and could not have. The audit record that
exists to catch claims-read-as-evidence carried one.

And the tiering plan, written from the same reading, described the dead
implementation as the state of the feature — while the live one in
`document_views.py` had been correctly scoped all along.

Nothing announced any of it. No import error, no warning, no failing test: the
shadowed file simply never participated. That silence is what this guard breaks.

`tests/` is included because the first attempt to test the shadowed file failed
to collect for the same reason, in the same session.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCANNED = ("apps", "tests", "core")

#: A shadowed module is tolerated only if it declares the decision itself.
DECISION_MARKER = "محجوب عمدًا"


def _shadowed(roots) -> list[str]:
    """Every `X.py` that has a sibling directory `X/`, in either direction.

    Both orders are the same hazard. A module beside a plain directory hides the
    directory's contents; a module beside a package hides the module. Which one
    loses depends on whether an `__init__.py` happens to be present, and that is
    not a distinction anyone reading the tree will make.
    """
    found = []
    for name in roots:
        root = ROOT / name
        if not root.is_dir():
            continue
        for module in root.rglob("*.py"):
            if "__pycache__" in module.parts:
                continue
            twin = module.with_suffix("")
            if not twin.is_dir():
                continue
            # A directory that holds no importable module shadows nothing. This
            # guard reported apps/authentication/tests.py against a `tests/`
            # containing only __pycache__ — build output left behind after the
            # real file moved — and stopped a rebase on a tree that was correct.
            # A guard that blocks correct work is the failure mode this file was
            # written to avoid, not an acceptable cost of catching the real one.
            if not any(
                child.suffix == ".py" for child in twin.rglob("*.py")
                if "__pycache__" not in child.parts
            ):
                continue
            # A collision is allowed only when the shadowed file says, in
            # itself, that it is shadowed on purpose. Computed rather than
            # listed: a hand-written exception list is what let this repository
            # ship a guard that reported zero from the day it was written.
            # apps/rule_engine/catalog.py carries that marker and the decision
            # behind it — docs/CATALOG_SHADOW_IMPACT.md.
            head = module.read_text(encoding="utf-8", errors="replace")[:2000]
            if DECISION_MARKER in head:
                continue
            found.append(str(module.relative_to(ROOT)))
    return sorted(found)


def test_no_module_is_shadowed_by_a_directory_of_the_same_name():
    """Measured, not listed. One offender existed when this was written."""
    offenders = _shadowed(SCANNED)

    assert offenders == [], (
        "a module sits beside a directory of the same name; one of them is "
        "unreachable and Python will not say so. Rename one, or make the "
        "directory a package and move the module into it as __init__.py. "
        "Offenders: " + ", ".join(offenders)
    )


def test_the_check_finds_the_shape_it_is_looking_for(tmp_path):
    """Plant the collision in a throwaway tree and watch the scan report it.

    Without this, a bug in the walk — a wrong suffix, a missed rglob — would
    make the assertion above pass on any repository, including one that still
    had the defect.
    """
    app = tmp_path / "apps" / "planted"
    app.mkdir(parents=True)
    (app / "views.py").write_text("# the module that wins\n", encoding="utf-8")
    (app / "views").mkdir()
    (app / "views" / "buried.py").write_text("# unreachable\n", encoding="utf-8")

    global ROOT
    original, ROOT = ROOT, tmp_path
    try:
        found = _shadowed(["apps"])
    finally:
        ROOT = original

    assert found == ["apps/planted/views.py"]


def test_a_normal_package_is_not_reported(tmp_path):
    """The common, correct layout must not trip it."""
    app = tmp_path / "apps" / "normal"
    (app / "views").mkdir(parents=True)
    (app / "views" / "__init__.py").write_text("", encoding="utf-8")
    (app / "views" / "detail.py").write_text("", encoding="utf-8")

    global ROOT
    original, ROOT = ROOT, tmp_path
    try:
        found = _shadowed(["apps"])
    finally:
        ROOT = original

    assert found == []


@pytest.mark.parametrize("module_name", ["executive_report_views"])
def test_the_file_this_guard_was_written_for_is_importable(module_name):
    """The specific casualty, named — importing it is the proof it was freed."""
    import importlib

    module = importlib.import_module(f"apps.reports.{module_name}")
    assert hasattr(module, "ExecutiveReportDetailView")


def test_a_collision_without_the_decision_marker_is_still_reported(tmp_path):
    """The exemption is earned by the file, not granted by a list."""
    app = tmp_path / "apps" / "silent"
    app.mkdir(parents=True)
    (app / "thing.py").write_text("# no decision recorded\n", encoding="utf-8")
    (app / "thing").mkdir()
    (app / "thing" / "buried.py").write_text("# unreachable\n", encoding="utf-8")

    marked = tmp_path / "apps" / "declared"
    marked.mkdir(parents=True)
    (marked / "thing.py").write_text(
        f"# هذا الملف {DECISION_MARKER} بحزمة تحمل الاسم نفسه\n", encoding="utf-8"
    )
    (marked / "thing").mkdir()
    (marked / "thing" / "buried.py").write_text("# unreachable\n", encoding="utf-8")

    global ROOT
    original, ROOT = ROOT, tmp_path
    try:
        found = _shadowed(["apps"])
    finally:
        ROOT = original

    assert found == ["apps/silent/thing.py"], (
        "the marker must exempt only the file that carries it"
    )


def test_a_twin_directory_holding_no_module_is_not_a_collision(tmp_path):
    """The false positive that stopped a correct rebase.

    `apps/authentication/tests/` held nothing but `__pycache__` after its one
    real file moved up a level, and this guard called it a collision against
    `apps/authentication/tests.py`. Nothing was shadowed — there was no module
    inside to shadow — and the operator lost time on a tree that was right.

    Both shapes are planted: an empty directory, and one holding only build
    output. Neither may be reported; the collision with a real module beside
    them still must be.
    """
    app = tmp_path / "apps" / "leftovers"
    app.mkdir(parents=True)

    (app / "tests.py").write_text("# the real tests\n", encoding="utf-8")
    (app / "tests").mkdir()
    (app / "tests" / "__pycache__").mkdir()
    (app / "tests" / "__pycache__" / "old.cpython-312.pyc").write_bytes(b"\x00")

    (app / "empty.py").write_text("# nothing beside it\n", encoding="utf-8")
    (app / "empty").mkdir()

    (app / "real.py").write_text("# genuinely shadows\n", encoding="utf-8")
    (app / "real").mkdir()
    (app / "real" / "buried.py").write_text("# unreachable\n", encoding="utf-8")

    global ROOT
    original, ROOT = ROOT, tmp_path
    try:
        found = _shadowed(["apps"])
    finally:
        ROOT = original

    assert found == ["apps/leftovers/real.py"], (
        "only a directory that actually holds an importable module shadows one"
    )
