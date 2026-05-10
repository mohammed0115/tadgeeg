"""Validate the rule_engine catalog: importability, doc-types, duplicates, stubs.

Designed to run in CI so a broken catalog can never reach production. Failure
modes detected:

  1. RuleDefinition.implementation_class doesn't import.
  2. The class imports but isn't a subclass of AuditRuleBase.
  3. RuleDefinition.is_active=True AND implementation_class points at
     CatalogStubRule (i.e. a placeholder is being treated as a real check).
  4. Duplicate rule_code entries.
  5. Duplicate (rule_code, organization, document_type) RuleAssignment rows
     (assignment table dedup violation).

Exit code 0 = clean, 1 = at least one issue. By default fails CI on any of
the conditions above. `--allow-stubs` downgrades the active-stub case to a
warning (useful while a milestone of real impls is in flight).

Usage:
    python manage.py validate_rule_catalog
    python manage.py validate_rule_catalog --allow-stubs
    python manage.py validate_rule_catalog --json   # machine-readable output
"""
from __future__ import annotations

import importlib
import json
import sys
from collections import Counter

from django.core.management.base import BaseCommand


_STUB_PATH = "apps.rule_engine.rules.generic.catalog_stub.CatalogStubRule"


def _import_class(dotted: str):
    """Resolve a dotted import path to a class. Raises on failure."""
    if not dotted or "." not in dotted:
        raise ImportError(f"empty/invalid path: {dotted!r}")
    module_path, _, cls_name = dotted.rpartition(".")
    module = importlib.import_module(module_path)
    cls = getattr(module, cls_name, None)
    if cls is None:
        raise ImportError(f"{cls_name!r} not found in {module_path!r}")
    return cls


class Command(BaseCommand):
    help = "Validate every active rule_engine RuleDefinition: import path, base class, no stubs."

    def add_arguments(self, parser):
        parser.add_argument(
            "--allow-stubs", action="store_true",
            help="Treat active CatalogStubRule references as warnings rather than failures.",
        )
        parser.add_argument(
            "--json", action="store_true",
            help="Emit machine-readable JSON instead of human-readable text.",
        )

    def handle(self, *args, allow_stubs: bool = False, json_output: bool = False, **opts):
        # Lazy import — Django needs to be set up first.
        from apps.rule_engine.models.rule_definition import RuleDefinition
        from apps.rule_engine.models.rule_assignment import RuleAssignment
        from apps.rule_engine.rules.base import AuditRuleBase

        # Some sites pass the kw via parser dest 'json' which collides with
        # the json module — get_options uses 'json_output' but argparse may
        # also pass a 'json' key. Accept both.
        json_output = bool(json_output or opts.get("json"))

        problems = {
            "import_errors":      [],
            "wrong_base_class":   [],
            "active_stubs":       [],
            "duplicate_codes":    [],
            "duplicate_assignments": [],
        }

        # ── Per-rule import + base-class check ─────────────────────────────
        rules_qs = RuleDefinition.objects.all()
        active_total = rules_qs.filter(is_active=True).count()
        total = rules_qs.count()

        for rd in rules_qs.only("id", "rule_code", "implementation_class", "is_active"):
            path = rd.implementation_class or ""
            if not rd.is_active:
                continue
            try:
                cls = _import_class(path)
            except Exception as exc:
                problems["import_errors"].append({
                    "rule_code": rd.rule_code,
                    "implementation_class": path,
                    "error": f"{type(exc).__name__}: {exc}",
                })
                continue

            if not (isinstance(cls, type) and issubclass(cls, AuditRuleBase)):
                problems["wrong_base_class"].append({
                    "rule_code": rd.rule_code,
                    "implementation_class": path,
                    "actual_base": cls.__name__,
                })

            if path == _STUB_PATH:
                problems["active_stubs"].append({
                    "rule_code": rd.rule_code,
                    "implementation_class": path,
                })

        # ── Duplicate rule_code ─────────────────────────────────────────────
        codes = Counter(
            rd.rule_code for rd in rules_qs.only("rule_code") if rd.rule_code
        )
        for code, n in codes.items():
            if n > 1:
                problems["duplicate_codes"].append({"rule_code": code, "count": n})

        # ── Duplicate RuleAssignment (rule, document_type, organization) ───
        assigns = RuleAssignment.objects.values_list(
            "rule_id", "document_type", "organization_id"
        )
        seen: Counter = Counter()
        for triplet in assigns:
            seen[triplet] += 1
        for triplet, n in seen.items():
            if n > 1:
                problems["duplicate_assignments"].append({
                    "rule_id":         str(triplet[0]),
                    "document_type":   triplet[1],
                    "organization_id": str(triplet[2]) if triplet[2] else None,
                    "count":           n,
                })

        # ── Decide exit ─────────────────────────────────────────────────────
        hard_failures = (
            len(problems["import_errors"])
            + len(problems["wrong_base_class"])
            + len(problems["duplicate_codes"])
            + len(problems["duplicate_assignments"])
        )
        if not allow_stubs:
            hard_failures += len(problems["active_stubs"])

        # ── Emit ───────────────────────────────────────────────────────────
        if json_output:
            self.stdout.write(json.dumps({
                "total_rules":         total,
                "active_rules":        active_total,
                "problems":            problems,
                "hard_failure_count":  hard_failures,
                "stubs_allowed":       allow_stubs,
            }, indent=2, ensure_ascii=False))
        else:
            self.stdout.write(self.style.NOTICE(
                f"\nrule_engine catalog: {total} total rules ({active_total} active).\n"
            ))
            self._report_section("Import errors", problems["import_errors"], style=self.style.ERROR)
            self._report_section("Wrong base class", problems["wrong_base_class"], style=self.style.ERROR)
            self._report_section("Duplicate rule_codes", problems["duplicate_codes"], style=self.style.ERROR)
            self._report_section("Duplicate rule assignments", problems["duplicate_assignments"], style=self.style.ERROR)
            stub_style = self.style.WARNING if allow_stubs else self.style.ERROR
            self._report_section(
                f"Active rules pointing at CatalogStubRule ({'allowed' if allow_stubs else 'blocking'})",
                problems["active_stubs"],
                style=stub_style,
            )
            if hard_failures == 0:
                self.stdout.write(self.style.SUCCESS("\n✓ catalog is clean."))
            else:
                self.stdout.write(self.style.ERROR(f"\n✗ {hard_failures} blocking issue(s)."))

        sys.exit(0 if hard_failures == 0 else 1)

    def _report_section(self, title: str, items: list, *, style):
        if not items:
            return
        self.stdout.write(style(f"\n{title}: {len(items)}"))
        for item in items[:25]:
            self.stdout.write(f"  • {item}")
        if len(items) > 25:
            self.stdout.write(f"  … and {len(items) - 25} more")
