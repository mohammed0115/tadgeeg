"""One door onto the three audit apps — a Facade, not a merge.

`apps.audit`, `apps.auditing` and `apps.audit_engine` overlap in name and not
in job. Merging them was recommendation 9 of the platform assessment and it is
the wrong trade: between them they own 43 models on live tables, so a merge is
a data migration on tenant rows bought purely with readability. The names cost
a developer minutes; the migration risks records that an audit firm is legally
required to keep.

What actually costs more than the names is underneath them, and this package
fixes that instead.

**The real defect.** `RuleStatus` is defined twice, with different members and
different values:

    apps.auditing …enums.RuleStatus   passed  failed  warning
                                      not_applicable  insufficient_data
    apps.audit.rules.base_rule        PASSED  FAILED  ERROR  SKIPPED

`auditing.RuleStatus.PASSED == audit.RuleStatus.PASSED` is **False** — one
holds `'passed'`, the other `'PASSED'`. A caller comparing a result from one
engine against the other's enum gets a quiet mismatch: no exception, no log,
the branch simply never runs. And `WARNING` does not exist on the audit side at
all, so `status == RuleStatus.WARNING` against that import can never be true.

Nothing crosses the two today — each stack is self-consistent. That makes this
a trap rather than a bug, and traps of this shape are what the rest of this
codebase kept turning out to be: a green signal standing in for something that
never happens.

**How the patterns land here**

* **Facade** — `apps.audit_platform` is the one import path. Callers stop
  reaching into `apps.audit.rules.base_rule`; the three apps keep their tables.
* **DRY** — one definition of "which outcomes exist" (`status.RuleOutcome`),
  with adapters translating each engine's native enum into it. The engines keep
  their own vocabularies; the *shared* concept is defined once.
* **Dependency inversion** — callers depend on this package's names, not on a
  concrete engine module. Swapping or adding an engine touches one adapter.
* **Interface segregation** — three narrow ports rather than one object with
  everything on it. Code that only reads documents does not import the
  engagement API.
* **Open/closed** — a fourth engine means a new adapter, not edits to callers.
* **KISS** — this covers the seam that is actually crossed. It does not wrap 43
  models behind a hand-written interface; that would be a second codebase to
  keep in sync, which is how facades become the problem they were meant to fix.

**What this package deliberately does NOT do**: re-export models. Importing a
model through a facade breaks `related_name` reasoning, migration detection and
`select_related` autocompletion, and buys nothing — a model is already a single
name from a single app.
"""

from apps.audit_platform.status import (  # noqa: F401
    RuleOutcome,
    RuleSeverity,
    from_audit_engine_status,
    from_auditing_status,
    to_storage_value,
)

__all__ = [
    "RuleOutcome",
    "RuleSeverity",
    "from_auditing_status",
    "from_audit_engine_status",
    "to_storage_value",
]
