# Phase 5 — Rule-Engine Reality Check

## What was wrong

`apps/rule_engine/management/commands/seed_document_audit_rules.py:107` set `implementation_class="apps.rule_engine.rules.generic.catalog_stub.CatalogStubRule"` for every entry in `apps.rule_engine.catalog.document_rules.ALL_RULES` — 236 rules across 21 doc types.

**The file `apps/rule_engine/rules/generic/catalog_stub.py` did not exist.** Any executor that tried to instantiate one of these rules would raise `ModuleNotFoundError` (silent in `try/except Exception`, surfacing as "audit didn't run") or hard-crash the worker.

We had to choose between:
- (a) Disable the 236 rows (`is_active=False`) until real implementations land, hiding the catalog gap from operators, OR
- (b) Build the missing class as a documented, **safe** placeholder, so the executor doesn't crash AND we have a CI gate that surfaces the placeholder as remaining work.

We chose (b).

## What changed

### `apps/rule_engine/rules/generic/catalog_stub.py` (new, 89 lines)

A real subclass of `AuditRuleBase` that:

- Always returns `RuleStatus.SKIPPED` with explanation `"informational only — no audit decision was made."`
- `default_severity = "info"` and `is_blocking = False` regardless of catalog severity. **Cannot freeze approvals.**
- Records `raw_data["stub_reason"] = "not_implemented"` and `raw_data["informational_only"] = True` so the report layer can render these distinctly (e.g., grayed-out badge: "Catalog rule — pending implementation").
- Echoes the catalog code from config (e.g. "PI-007") so reports stay traceable rather than showing the literal "CATALOG-STUB".

### `apps/rule_engine/management/commands/validate_rule_catalog.py` (new, 175 lines)

CI-friendly catalog validator. Detects:

| # | Failure mode | Default behavior |
|---|---|---|
| 1 | `implementation_class` doesn't import (`ModuleNotFoundError`/`AttributeError`) | hard failure |
| 2 | Imports but isn't a subclass of `AuditRuleBase` | hard failure |
| 3 | Active rule still pointing at `CatalogStubRule` | hard failure (downgradable to warning with `--allow-stubs`) |
| 4 | Duplicate `rule_code` rows | hard failure |
| 5 | Duplicate `(rule, document_type, organization)` `RuleAssignment` rows | hard failure |

Modes:
- `python manage.py validate_rule_catalog` — strict, exit 1 on any issue.
- `python manage.py validate_rule_catalog --allow-stubs` — useful while a milestone of real impls is in flight.
- `python manage.py validate_rule_catalog --json` — machine-readable for CI.

## Files added

| File | Purpose |
|---|---|
| `apps/rule_engine/rules/generic/catalog_stub.py` | Safe placeholder rule |
| `apps/rule_engine/management/commands/validate_rule_catalog.py` | CI gate |

## Verification

```text
$ python manage.py validate_rule_catalog
…
Active rules pointing at CatalogStubRule (blocking): 236
…
✗ 236 blocking issue(s).            # exit code 1

$ python manage.py validate_rule_catalog --allow-stubs
…
Active rules pointing at CatalogStubRule (allowed): 236
✓ catalog is clean.                 # exit code 0

$ python manage.py validate_rule_catalog --json | jq '.hard_failure_count'
236
```

```python
>>> from apps.rule_engine.rules.generic.catalog_stub import CatalogStubRule
>>> from apps.rule_engine.rules.base import AuditRuleBase
>>> issubclass(CatalogStubRule, AuditRuleBase)
True
>>> r = CatalogStubRule({"catalog_code": "PI-007"}).execute(NormalizedDocument(...))
>>> r.status
<RuleStatus.SKIPPED: 'skipped'>
>>> r.is_blocking
False
>>> r.rule_code
'PI-007'   # echoes the catalog code
```

## What's next (deferred to Tier 2 work)

- The 236 rules need real implementations. Each rule_code in `ALL_RULES` should grow a Python class (split by document type). When a real impl lands, the seed needs to point at it instead of the stub. CI should run `validate_rule_catalog` (no `--allow-stubs`) so reviewers see the count tick down.
- Wire `validate_rule_catalog` into `.github/workflows/ci-cd.yml` (or whatever CI is in use). Suggested: run with `--allow-stubs` for now (so build doesn't break), then drop the flag once stubs are below a threshold.

## Risks / things to watch

- Existing audit runs that previously failed silently for stubbed rules will now succeed-with-skipped. The downstream report layer should treat `RuleStatus.SKIPPED` differently from `PASS` so a "100% pass" claim isn't misleading. (Confirm in Phase 7.)
- If `seed_document_audit_rules` runs on a fresh DB after this change, the 236 `RuleDefinition` rows will be created with the stub class. The validator surfaces this — fine.
