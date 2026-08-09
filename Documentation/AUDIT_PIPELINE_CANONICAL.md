# Audit Pipeline — Canonical Path

This document defines the **single canonical audit pipeline** for Tadgeeg, the explicit deprecation path for the four parallel pipelines that historically coexisted, and the safety guards (idempotency + transaction.on_commit) that protect it.

This is the answer to "Phase 7" from the readiness gap review.

---

## 1. The canonical pipeline

```
Upload (HTTP / signal / Celery)
   │
   ▼
Document / Invoice ORM row saved (inside a transaction)
   │
   ▼  transaction.on_commit(_dispatch)
Idempotency check  ← _has_active_run(doc_id, doc_type, org_id) within 1 h window
   │
   ▼  if no recent active run
run_audit_task.delay(document_id, document_type, organization_id, ...)
   │
   ▼  Celery worker picks up
apps.rule_engine.executors.audit_pipeline.AuditPipeline.run(...)
   │
   ▼
NormalizedDocument          ← apps/rule_engine/normalizers/
   │
   ▼
RuleAssignment matching     ← apps/rule_engine/selectors/
   │
   ▼
Rule execution loop          ← apps/rule_engine/rules/*  (each implementation_class)
   │
   ▼
AuditRun + Findings persisted
   │
   ▼
Risk scoring + report aggregation
```

**One pipeline. One Celery task. One source of truth.**

---

## 2. The four parallel paths that existed — and what they are now

| # | Path | Status as of this commit | Why kept (if any) |
|---|---|---|---|
| 1 | `apps/audit/audit_engine.py::run_audit()` (sync) | **DEPRECATED**, no longer called when `USE_NEW_RULE_ENGINE=True` (default). Carries an explicit banner in its docstring. Removal scheduled after 2 release cycles of clean V2 operation. | Rollback escape hatch. Flip the flag to recover. |
| 2 | `apps/rule_engine/tasks/audit_tasks.py::run_audit_task` (Celery) | **CANONICAL.** Every upload, signal, and explicit re-audit goes here. | — |
| 3 | `apps/audit/tasks.py::LegacyAuditEngineAdapter` | Compat shim only. Triggered by manual re-audit re-runs; not in the upload path. | Maintained until #1 is removed. |
| 4 | `apps/auditing/services/ai_auditor_service.py::AIAuditorService` | **NOT a dispatch pipeline.** Per-document OpenAI call invoked during ingestion (extraction). It writes `ai_summary`, `ai_recommendations`, `anomalies_found` on the model. The rule engine consumes those columns; it does not call AIAuditorService. | — |
| 5 | `core/services/doc_validators/doc_validators.py` (+ `_v2`) | **NOT a separate pipeline.** This is the rule-IMPLEMENTATION layer the rule engine calls into for deterministic per-type rules (PO-001..PO-017, BNK-001..017, etc.). | — |

Net: five "audit pipelines" were really one dispatch pipeline (#1 + #2 running side by side) plus three layers that are NOT dispatch (ai_auditor + doc_validators) or are admin-only (#3). After this commit, only #2 dispatches in the production hot path.

---

## 3. Safety guards on the canonical path

Three guards protect the unified path from regressions seen during this audit:

### 3.1 `transaction.on_commit` wrap

Without it, a fast Celery worker can pick up the task before the writing transaction commits and SELECT zero rows; if the writer rolls back, a phantom audit task fires against a row that never existed.

Applied at:
- `apps/documents/signals.py::_dispatch_audit` — all 20 typed-doc post_save handlers (commit `6fdf0fd`).
- `apps/invoices/services/processor.py` Step 7b — invoice upload path (this commit).

### 3.2 Idempotency guard

`apps/documents/signals.py::_has_active_run(doc_id, doc_type, org_id)` checks for any `PENDING`/`RUNNING`/`COMPLETED` `AuditRun` against the same `(document_id, document_type, organization_id)` within the last 1 hour. If one exists, dispatch is skipped.

This prevents the classic "signal + processor + manual re-audit" triple-dispatch scenario.

### 3.3 Feature flag — `USE_NEW_RULE_ENGINE`

Default: **`True`**. Lives in `finai_backend/settings_canonical.py:152`.

| Flag value | Behavior |
|---|---|
| `True` (production) | Legacy `run_audit()` skipped. Only V2 dispatch runs. |
| `False` (rollback) | Legacy `run_audit()` runs synchronously. V2 still dispatches. |

The flag is read at the start of Step 7a in `processor.py`. To roll back: set `USE_NEW_RULE_ENGINE=False` in the env, restart `web` + `celery_worker`, and the legacy engine becomes the active path. No code change needed for rollback.

---

## 4. What changed in this commit

| File | Change |
|---|---|
| `apps/invoices/services/processor.py` | Step 7a now gated by `not USE_NEW_RULE_ENGINE`. Step 7b wraps `.delay()` in `transaction.on_commit` + imports the existing `_has_active_run` dedup helper. |
| `apps/audit/audit_engine.py` | `run_audit()` docstring renamed to **DEPRECATED legacy audit pipeline**; clear pointer to this doc + removal plan. |
| `Documentation/AUDIT_PIPELINE_CANONICAL.md` | This file. |

No model edits. No migrations. No URL changes. No API breaks.

---

## 5. Verification

Smoke test (against the live `main` branch):

```text
USE_NEW_RULE_ENGINE setting: True

1) Legacy run_audit gated by USE_NEW_RULE_ENGINE flag: YES
2) V2 dispatch wrapped in transaction.on_commit: YES
3) Idempotency guard (_has_active_run) called before .delay(): YES
4) Legacy run_audit() carries DEPRECATED banner: YES
5) post_save signal still uses transaction.on_commit: YES
6) processor imports _has_active_run from signals: YES
```

`python manage.py check` — 0 issues.

---

## 6. Operational notes

### How to roll back

1. Set env: `USE_NEW_RULE_ENGINE=False` (or edit settings).
2. Restart `web` + `celery_worker`.
3. Verify legacy `apps.audit` AuditCase rows are being created again.
4. File a bug report with the symptom that motivated rollback — the goal is to make the new engine pass cleanly, not to live on the legacy path.

### How to remove the legacy engine entirely (future)

After 2 release cycles of clean operation with no rollbacks:

1. Delete `apps/audit/audit_engine.py::run_audit()` + `class AuditEngine`.
2. Delete `apps/audit/tasks.py::LegacyAuditEngineAdapter`.
3. Drop the `USE_NEW_RULE_ENGINE` flag from settings (or hardwire to `True`).
4. Delete the Step 7a branch in `processor.py`.
5. The dispatch is then unconditional — no flag check, no legacy.

### Double-dispatch detection (operational)

If you suspect a document is being audited twice, the dedup log line surfaces it:

```
[processor] Audit already in-flight for invoice=<uuid> — skipping duplicate dispatch
[Signal] Skipping duplicate dispatch: type=<type> doc=<uuid> already active
```

Search for either in the worker log. If you see one paired with a duplicate finding in `AuditRun`, it means the 1-hour dedup window let a legitimate retry through — adjust if needed.

---

## 7. Future work not in scope

- **Delete the legacy code** — after 2 clean release cycles.
- **Consolidate the rule catalog seed** so the 236 `CatalogStubRule` placeholders get real implementations one-by-one. Validate progress via `python manage.py validate_rule_catalog`.
- **Shadow-run telemetry** — `apps/rule_engine/tasks/audit_tasks.py::run_shadow_audit_task` is wired but not used in production. If enabled in staging, you can diff old vs new findings before flipping the flag in prod.
