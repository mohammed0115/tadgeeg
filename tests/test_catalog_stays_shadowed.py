"""`apps/rule_engine/catalog.py` stays shadowed, and stays present.

The package `apps/rule_engine/catalog/` and the module
`apps/rule_engine/catalog.py` carry the same name. The package wins, so the
module cannot be imported, and seven call sites in four apps that ask for
`resolve_rule_catalog_metadata` get an ImportError they swallow.

That is a decision, not an oversight, and it was taken after measuring what
connecting it would do — docs/CATALOG_SHADOW_IMPACT.md:

  · the resolver does not raise on a miss. It infers a category from keywords,
    infers is_blocking from (category, severity), and registers the result. So
    blocking becomes an *inferred* judgment rather than a recorded one: a rule
    blocks approval because its severity is "high", not because an auditor
    decided it should. 115 of 236 live rules would start blocking.
  · every rule code changes — 236 of 236. SI-001 becomes CMT-###, and any
    stored or exported reference to the old code stops matching. That alone
    settles it, independently of the blocking question.

And it is not deleted: RuleCategory, RuleCatalogEntry, get_rules_for_doc_type,
get_blocking_rules and get_rules_by_category have no counterpart in the
package. The package holds the data; this module holds the machinery for
querying it.

These tests exist so that connecting it is a visible decision and not a slip.
**Update them with that decision — do not delete them.** The first one is
written to fail the day someone adds the export.
"""

from __future__ import annotations

import importlib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PACKAGE = "apps.rule_engine.catalog"
RESOLVER = "resolve_rule_catalog_metadata"
SHADOWED = REPO / "apps" / "rule_engine" / "catalog.py"


def _package_exports_resolver() -> bool:
    """Ask the package the same question the seven call sites ask."""
    package = importlib.import_module(PACKAGE)
    return hasattr(package, RESOLVER)


def test_the_catalog_package_does_not_export_the_resolver():
    """Fails the day the export is added — which is the point.

    Nothing else announces it. Adding one line to catalog/__init__.py would
    connect the machinery to four apps, change 115 blocking decisions and 236
    rule codes, and produce no error, no warning and no failing test anywhere
    else in this suite.
    """
    assert not _package_exports_resolver(), (
        f"{PACKAGE} now exports {RESOLVER}. If that is deliberate, "
        f"docs/CATALOG_SHADOW_IMPACT.md is the measurement it has to be "
        f"weighed against, and this test is updated with the decision."
    )


def test_the_shadowed_module_is_still_there():
    """The other half of the decision: shadowed, not deleted."""
    assert SHADOWED.is_file(), f"{SHADOWED.name} is gone"

    source = SHADOWED.read_text(encoding="utf-8")
    for name in (
        RESOLVER,
        "get_rules_for_doc_type",
        "get_blocking_rules",
        "get_rules_by_category",
        "class RuleCategory",
        "class RuleCatalogEntry",
    ):
        assert name in source, (
            f"{name} has left {SHADOWED.name}. Seven call sites ask for the "
            f"resolver and the package defines none of this."
        )


def test_this_guard_can_fail(monkeypatch):
    """Connect it, in the test only, and watch the guard above notice.

    The export is attached to the imported package object — catalog/__init__.py
    is not edited, created or removed. The stand-in is a real function
    returning a real object built here; a mock would prove only that a mock
    returns what it was told to.
    """
    package = importlib.import_module(PACKAGE)
    assert not _package_exports_resolver(), "precondition: not exported yet"

    class _Entry:
        def __init__(self, rule_code, is_blocking):
            self.rule_code = rule_code
            self.is_blocking = is_blocking

    def _resolver(rule_identifier, **kwargs):
        return _Entry(rule_code=f"CMT-{len(str(rule_identifier)):03d}",
                      is_blocking=True)

    monkeypatch.setattr(package, RESOLVER, _resolver, raising=False)

    assert _package_exports_resolver(), (
        "the check no longer detects an exported resolver, so the guard above "
        "is not distinguishing anything"
    )
    # And the call sites would now get a live object instead of an ImportError.
    entry = getattr(package, RESOLVER)("SI-001")
    assert entry.rule_code != "SI-001", (
        "this is the code substitution the measurement counted 236 times"
    )
