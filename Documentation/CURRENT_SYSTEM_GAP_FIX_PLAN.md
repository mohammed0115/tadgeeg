# Tadgeeg — Current System Gap Fix Plan

**Status:** Phase 1 audit (read-only).
**Date:** 2026-05-10.
**Scope:** Production-readiness audit before any code changes. No source files were modified during this phase.

---

## 1. Apps present under `apps/`

39 directories. Listed alphabetically; bold = referenced from `urls.py` and/or `INSTALLED_APPS`.

| # | Directory | Has `apps.py` | Has `models.py` | Has `urls.py` | Has migrations |
|---|---|---|---|---|---|
| 1 | activity_logs | ✅ | ✅ | — | ✅ |
| 2 | **alerts** | ✅ | ✅ | ✅ | ✅ |
| 3 | **analytics** | ✅ | ✅ | ✅ | ✅ |
| 4 | **api_mobile** | ✅ | ✅ | ✅ | ✅ |
| 5 | **assistant** | ✅ | ✅ | ✅ | ✅ |
| 6 | **audit** | ✅ | ✅ | ✅ | ✅ |
| 7 | audit_engine | ✅ | ✅ | ✅ | ✅ |
| 8 | **auditing** | ✅ | ✅ | ✅ | ✅ |
| 9 | **authentication** | ✅ | ✅ | ✅ | ✅ |
| 10 | **banking** | ✅ | ✅ | ✅ | ✅ |
| 11 | cms | ✅ | ✅ | — | ✅ |
| 12 | **compliance** | ✅ | ✅ | ✅ | ✅ |
| 13 | **core_engine** | ✅ | ✅ | — | ✅ |
| 14 | **data_export** | ✅ | ✅ | ✅ | ✅ |
| 15 | **documents** | ✅ | ✅ | ✅ | ✅ |
| 16 | file_management | ✅ | ✅ | ✅ | ✅ |
| 17 | **frontend** | ✅ | ✅ | ✅ | ✅ |
| 18 | **invoices** | ✅ | ✅ | ✅ | ✅ |
| 19 | jobs | ✅ | — | — | ✅ |
| 20 | leads | ✅ | ✅ | — | ✅ |
| 21 | **ledger** | ✅ | ✅ | ✅ | ✅ |
| 22 | **notifications** | ✅ | ✅ | ✅ | ✅ |
| 23 | organization_admin | ✅ | ✅ | — | ✅ |
| 24 | organization_settings | ✅ | ✅ | — | ✅ |
| 25 | organization_users | ✅ | ✅ | — | ✅ |
| 26 | platform_admin | ✅ | ✅ | — | ✅ |
| 27 | platform_management | ✅ | — | ✅ | — |
| 28 | **procurement** | ✅ | ✅ | ✅ | ✅ |
| 29 | reporting | ✅ | ✅ | — | ✅ |
| 30 | **reports** | ✅ | ✅ | ✅ | ✅ |
| 31 | **rule_engine** | ✅ | ✅ (pkg) | ✅ (api/) | ✅ |
| 32 | storage_management | ✅ | ✅ | — | ✅ |
| 33 | **streaming** | ✅ | ✅ | — | ✅ |
| 34 | system_monitoring | ✅ | ✅ | — | ✅ |
| 35 | **transactions** | ✅ | ✅ | ✅ | ✅ |
| 36 | vendor_dashboard | ✅ | ✅ | ✅ | ✅ |
| 37 | **webhooks** | ✅ | ✅ | ✅ | ✅ |
| 38 | workflow | ✅ | ✅ | — | ✅ |
| 39 | **zatca** | ✅ | ✅ | ✅ | ✅ |

---

## 2. Apps in `INSTALLED_APPS`

There are **two settings files** with **different** `LOCAL_APPS` lists:

### `finai_backend/settings.py` — active when `manage.py` runs (default)
20 apps:
```
authentication, core_engine, documents, transactions, audit, reports, analytics,
compliance, invoices, frontend, auditing, rule_engine, notifications, api_mobile,
streaming, alerts, zatca, banking, ledger, procurement
```

### `finai_backend/settings_canonical.py` — pulled into `settings/base.py` (used by `production.py` / `test.py`)
23 apps — adds `assistant`, `webhooks`, `data_export`.

> ⚠️ **Inconsistency:** depending on `DJANGO_SETTINGS_MODULE`, three apps may or may not be installed. This is fragile and is a likely source of AppNotFound errors in some environments.

---

## 3. Apps used in `urls.py` but NOT in `INSTALLED_APPS`

23 apps are referenced from `finai_backend/urls.py`. The following are **referenced but not installed** under each settings flavor:

| App | Missing in `settings.py`? | Missing in `settings_canonical.py`? | Notes |
|---|---|---|---|
| `apps.assistant` | ❌ missing | ✅ present | works under `settings/*` only |
| `apps.data_export` | ❌ missing | ✅ present | works under `settings/*` only |
| `apps.webhooks` | ❌ missing | ✅ present | works under `settings/*` only |
| `apps.platform_management` | ❌ missing | ❌ missing | **broken in both** — `urls.py:67` includes `apps.platform_management.urls` |
| `apps.vendor_dashboard` | ❌ missing | ❌ missing | **broken in both** — `urls.py:80` includes |

Also: `urls.py` imports views directly from `apps.audit`, `apps.invoices`, `apps.compliance`, `apps.authentication` — fine for code import but these apps must be installed (they are).

> Note: `python manage.py check` currently passes. Django does not require an app to be in `INSTALLED_APPS` just because its `urls.py` is included via `path("...", include("apps.x.urls"))` — it imports the URL module directly. But views referencing models on un-installed apps will fail at request time, and migrations are not run for them.

---

## 4. Audit pipelines that exist today

There are **five** parallel-ish entry points to "do an audit":

| # | Path | Style | Trigger |
|---|---|---|---|
| 1 | `apps/audit/audit_engine.py::run_audit()` | sync, structural rules + `AuditCase` | called from `invoices/services/processor.py:392` during invoice upload |
| 2 | `apps/rule_engine/tasks/audit_tasks.py::run_audit_task` | Celery, new pipeline (RuleAssignment → executor) | called from `invoices/services/processor.py:408` after every invoice upload via `.delay()` |
| 3 | `apps/audit/tasks.py` → `LegacyAuditEngineAdapter` | Celery, "legacy" rule-engine bridge | re-runs Stage 3 of upload pipeline |
| 4 | `apps/auditing/services/ai_auditor_service.py::AIAuditorService` | sync, OpenAI-based | per-document, called during ingestion |
| 5 | `core/services/doc_validators/doc_validators.py` (+ `doc_validators_v2.py`) | sync, deterministic per-type rules (PO-001..AST-017 etc.) | called by upload pipeline for typed docs (PO/Bank/Payroll/...) |

### Observations

- **Double-trigger on invoice upload:** processor calls both #1 (sync, persistent `AuditCase`) and #2 (Celery `run_audit_task.delay`). The same upload spawns two audit runs.
- **Celery is required for path #2 but not actually deployed** (see §9). Without a worker, `.delay()` either silently no-ops (eager off + no broker) or blocks (eager on).
- Path #4 (`ai_auditor_service`) is **not currently wired into the report layer**; per Session-2 commits we added `ai_narrative_service` as a separate report-time synthesizer.
- Path #5 is the source of truth for all "70+ rule code" findings shown in reports today (PO-001..017, BNK-001..017, etc. expanded in commits `c070df1..a13ab56`).

### Recommended canonical path (target after Phase 7)

```
Upload (HTTP)
  → Document/Invoice row created
  → Extract (OCR + AI)            [core/services/extraction]
  → Normalize (per-type)          [apps/rule_engine/normalizers/]
  → Rule Engine                   [apps/rule_engine/pipeline/, executors/]
  → Findings + Risk score         [persisted on AuditMixin + AuditRunV2*]
  → Reports                       [apps/reports/services/]
```

Path #1 (`audit/audit_engine`) becomes a deprecated compatibility shim that re-dispatches to the new pipeline. Path #5 (`doc_validators`) becomes the rule implementations called by executors (rather than independently).

---

## 5. Document types — **actually supported end-to-end**

Looking at: model exists → upload accepts → list/detail API → typed validator runs → reports show findings.

| Doc type | Model | Upload | List/Detail API | Validator | Reports | Status |
|---|---|---|---|---|---|---|
| invoice | ✅ `apps.invoices.Invoice` | ✅ | ✅ | ✅ (INV/VAT-*) | ✅ | **fully supported** |
| purchase_order | ✅ `PurchaseOrder` | ✅ typed | ✅ | ✅ (PO-001..017 after `c070df1` deepening) | ✅ | **fully supported** |
| bank_statement | ✅ | ✅ typed | ✅ | ✅ (BNK-001..017 after `de05726`) | ✅ | **fully supported** |
| payroll | ✅ `PayrollSheet` | ✅ typed | ✅ | ✅ (PAY-001..017 after `9e20e33`) | ✅ | **fully supported** |
| expense_report | ✅ | ✅ typed | ✅ | ✅ (EXP-001..016 after `a13ab56`) | ✅ | **fully supported** |
| vat_return | ✅ | ✅ typed | ✅ | ✅ (VATR-001..016 after `752792f`) | ✅ | **fully supported** |
| fixed_asset | ✅ | ✅ typed | ✅ | ✅ (AST-001..017 after `c070df1`) | ✅ | **fully supported** |
| sales_receipt | ✅ | ✅ typed | ✅ | ✅ (REC-*) | ✅ | **fully supported** |

8 doc types are end-to-end. Everything below is partially wired.

---

## 6. Document types — **model-only** (no API / no audit / no reports)

`apps/documents/typed_models_v2.py` defines these classes (every one inherits `AuditMixin` and has a migration):

| Doc type | Model | Upload? | List/Detail API? | Normalizer? | Validator (`v2`)? | Reports? |
|---|---|---|---|---|---|---|
| sales_order | `SalesOrder` | — | — | ❌ | ✅ `validate_sales_order` (10 rules) | ✅ via multi_doc adapter |
| quotation | `Quotation` | — | — | ❌ | ✅ (10 rules) | ✅ |
| proforma_invoice | `ProformaInvoice` | — | — | ❌ | ✅ (10 rules) | ✅ |
| receipt_voucher | `ReceiptVoucher` | — | — | ❌ | ✅ (10 rules) | ✅ |
| cash_voucher | `CashVoucher` | — | — | ❌ | ✅ (10 rules) | ✅ |
| general_ledger | `GeneralLedger` | — | — | ❌ | ✅ (12 rules) | ✅ |
| ledger | `Ledger` | — | — | ❌ | ✅ (10 rules) | ✅ |
| contract | `Contract` | — | — | ❌ | ✅ (13 rules) | ✅ |
| supplier_statement | `SupplierStatement` | — | — | ❌ | ✅ (12 rules) | ✅ |
| customer_statement | `CustomerStatement` | — | — | ❌ | ✅ (12 rules) | ✅ |
| journal_entry | `JournalEntry` | — | — | ❌ | ✅ (14 rules) | ❌ (`tax_vat_document` aliased; JE not in adapter `_SPECS`) |
| GoodsReceiptNote | `GoodsReceiptNote` | — | — | ❌ | ✅ `validate_grn` (10 rules) | ✅ |
| PaymentVoucher | `PaymentVoucher` | — | — | ❌ | ✅ `validate_payment_voucher` (12 rules) | ✅ |

> The DB shows non-trivial seed/test data for all of these (e.g. 11 SalesOrders, 8 Contracts, 6 JournalEntries). Reports surface them via `multi_doc_audit_adapter._SPECS` — that's why "Reports?" reads ✅ — but **users can't upload them through any HTTP endpoint, and no normalizer translates them into the canonical schema the new rule engine expects**.

This is the gap Phase 8 + 9 of your plan addresses.

---

## 7. Rule-engine seed referencing missing implementation_class

`apps/rule_engine/management/commands/seed_document_audit_rules.py:107` sets:

```python
"implementation_class": "apps.rule_engine.rules.generic.catalog_stub.CatalogStubRule",
```

for every rule in the catalog.

**The file `apps/rule_engine/rules/generic/catalog_stub.py` does not exist.** Confirmed by:

- `find apps/rule_engine -name "catalog_stub*"` → no results.
- `ls apps/rule_engine/rules/generic/` → currency/document_date/document_number/duplicate_file_hash/total_amount/total_greater_zero/workflow_rules. No `catalog_stub`.

**Blast radius:** 236 rules across 21 doc types would be inserted with a non-importable `implementation_class`:

| doc_type | rules | doc_type | rules |
|---|---|---|---|
| purchase_invoice | 15 | sales_invoice | 12 |
| bank_statement | 15 | purchase_order | 12 |
| journal_entry | 14 | payment_voucher | 12 |
| contract | 13 | general_ledger | 12 |
| expense_report | 13 | payroll | 12 |
| tax_vat_document | 12 | supplier_statement | 12 |
| customer_statement | 12 | sales_order | 10 |
| quotation | 10 | proforma_invoice | 10 |
| grn | 10 | receipt_voucher | 10 |
| cash_voucher | 10 | ledger | 10 |

If the seed has been run in any environment (likely production, given the `seed_canonical_fields`/`seed_rule_assignments` companion commands), then **every "audit run" attempt for those rules either fails at executor import time, or silently no-ops depending on how the executor handles ImportError**. Either way, those 236 catalog rows are not real audit rules.

---

## 8. Celery / Redis / Docker — readiness state

### Settings
- `CELERY_BROKER_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")` — defaults to localhost (no docker service).
- `CELERY_TASK_ALWAYS_EAGER = os.environ.get("CELERY_TASK_ALWAYS_EAGER", "False") == "True"` — **default off** in production.
- `CHANNEL_LAYERS` also expects `redis://...:6379/0`.
- 4 beat tasks configured: `nightly-anomaly-scan`, `weekly-kpi-report`, `weekly-summary`, `prune-audit-logs`.

### Docker
`docker-compose.yml` defines: `db` (mysql:8.4), `web` (gunicorn), `nginx`. **That's it.**

There is **no** redis service, **no** celery worker container, **no** beat container.

### Failure mode in production
- All `.delay()` / `apply_async` calls (e.g. `run_audit_task.delay()`, `process_document.delay()`) try to enqueue to `redis://localhost:6379/0` from within the `web` container — there is no redis on `localhost`.
- Symptom: connection error logged, then the trigger swallows the exception (e.g. `processor.py:414` catches `Exception` and logs a warning). User-visible: "upload succeeded" but no audit run ever appears.

### Tasks dispatched today via `.delay()`
- `apps/invoices/services/processor.py:408,688` — `run_audit_task.delay`, `process_document` task per-row.
- `apps/documents/tasks.py` — heavy doc tasks.
- `apps/notifications/`, `apps/audit/tasks.py`, etc.

This is the single biggest reason "audit looks dead" in any production-like deployment.

---

## 9. Security — media / S3 / nginx

### Local filesystem path (when `AWS_STORAGE_BUCKET_NAME` is unset)
- `MEDIA_ROOT = BASE_DIR / "media"`, `MEDIA_URL = "/media/"`.
- `docker/nginx/default.conf.template` serves `/media/` via:

  ```
  location /media/ {
      alias /vol/media/;
      expires 7d;
      add_header Cache-Control "public";
      access_log off;
  }
  ```

  **No auth, no permission check.** Anyone who guesses (or scrapes) a filename like `/media/invoices/2026/05/foo.pdf` gets the file, including financial documents containing VAT numbers, names, and totals.

### S3 path (when `AWS_STORAGE_BUCKET_NAME` is set)
- `AWS_QUERYSTRING_AUTH = False` → URLs are **unsigned** (`https://{bucket}.s3.amazonaws.com/...`). Bucket must be public-read for these to work; if it is, **every uploaded financial document is world-readable**.
- `AWS_DEFAULT_ACL = None` — relies entirely on bucket policy. If bucket policy is `public-read`, same problem.
- No `protected_media` view exists (grep: 0 hits).

### Download endpoint
- `apps/documents/views.py::DocumentDownloadView` does exist (`urls.py:18`), but it's not what the templates / the frontend link to. The user-facing URL is the bare `MEDIA_URL`.

### Other risks
- ZIP upload uses `os.path.basename(member.filename)` — that's adequate zip-slip protection. ✅
- `validate_zip_bomb` runs before extraction. ✅
- No virus / clamav scan on uploads.
- No file-level audit log on download.

---

## 10. Entrypoint — DROP TABLE on every container start

`docker/entrypoint.sh` runs three Python blocks before `migrate`:

1. Wait for MySQL.
2. **"Schema drift fix"** — if `audit_sessions.session_name` exists, runs:
   ```sql
   UPDATE invoice_batches SET audit_session_id = NULL ...
   DROP TABLE IF EXISTS audit_findings;
   DROP TABLE IF EXISTS audit_sessions;
   DELETE FROM django_migrations WHERE ...
   ```
3. **"Drop orphan tables"** — for each known orphan:
   ```sql
   DROP TABLE IF EXISTS `ledger_periods`
   DROP TABLE IF EXISTS `procurement_threeway_matches`
   DROP TABLE IF EXISTS `procurement_pr_approvals`
   DROP TABLE IF EXISTS `procurement_pr_lines`
   DROP TABLE IF EXISTS `procurement_requisitions`
   ```

Both blocks run **on every container restart**. A regression in either guard could blow away production tables. Any future "schema drift" added to this list ships data loss in a deploy.

This is exactly what your Phase 4 mandate forbids.

---

## 11. Tests — current state

- 80 `test_*.py` files (across `tests/` and `apps/*/tests/`).
- `pytest.ini` has `--cov-fail-under=45` — modest, but at least enforced.
- `python manage.py check` → **0 issues** (Django happy at import time).
- `python manage.py makemigrations --check --dry-run` → **NOT clean**: pending alterations on `rule_engine.AuditRunV2Metadata` (decision/pipeline_version/stages_skipped) + `CrossDocumentLink.link_type` + `RuleAssignment.document_type`. Migration `0007_alter_auditrunv2metadata_decision_and_more.py` would be created.

> Existing migrations are not in sync with current model definitions. If a deploy runs `migrate` against a stale state, it just no-ops; if a developer runs `makemigrations` casually, it generates surprise migrations.

---

## 12. Prioritized execution plan

Ordered by **risk × ease**: highest-risk items first; within each tier, easier ones first.

### Tier 0 — Stop the bleeding (do first, low-risk fixes)

| # | Item | Phase | Files | Risk if skipped |
|---|---|---|---|---|
| 1 | Move DROP TABLE blocks out of `docker/entrypoint.sh` into a documented `scripts/manual_schema_repair.py` that is **not** auto-invoked. Keep entrypoint = wait + `migrate --noinput` + `collectstatic`. | 4 | `docker/entrypoint.sh`, new `scripts/manual_schema_repair.py` | Data loss on next restart. |
| 2 | Reconcile `settings.py` and `settings_canonical.py` — pick ONE as canonical, deprecate the other with a comment + raise on import. Add the missing `assistant`, `webhooks`, `data_export`, `platform_management`, `vendor_dashboard` to whichever is canonical, OR disable their URL routes with `TODO`. | 2 | `finai_backend/settings.py`, `urls.py` | URL → 500 in some envs; AppNotFound on production. |
| 3 | Make media private on the local-FS path: drop the `/media/` location from nginx and route every download through a `DocumentDownloadView` that checks `request.user.organization == document.organization`. Audit-log the download. | 5 | `docker/nginx/default.conf.template`, `apps/documents/views.py` | Anyone with a filename downloads any customer's financials. |
| 4 | Make S3 path private: set `AWS_QUERYSTRING_AUTH = True`, default ACL `private`, generate signed URLs (≤ 5 min) from the download view. Document the bucket-policy requirement (no public-read). | 5 | `finai_backend/settings.py`, download view | Same as #3 but worldwide. |

### Tier 1 — Make the audit pipeline real

| # | Item | Phase |
|---|---|---|
| 5 | Add `redis` + `celery_worker` + `celery_beat` services to `docker-compose.yml`. Set `CELERY_BROKER_URL` env to `redis://redis:6379/0`. Healthchecks for redis. Restart policies. | 3 |
| 6 | Audit every `.delay()` site for `transaction.on_commit` wrap (so a failed save doesn't leave orphan tasks). Add status fields. | 3 |
| 7 | Replace `CatalogStubRule` reference with one of: (a) a real `NotImplementedRule` in `apps/rule_engine/rules/generic/catalog_stub.py` that returns `status="informational_only"` and never blocks approval, (b) downgrade the 236 seed rows to `is_active=False` until real implementations land. | 6 |
| 8 | Add `python manage.py validate_rule_catalog` — fails CI if any active rule's `implementation_class` is not importable, doc_type is not in `SupportedDocumentType`, or duplicate `rule_code` exists. | 6 |
| 9 | Unify upload-time audit dispatch: `processor.py` should call **one** path (the new `run_audit_task`); the legacy `run_audit()` becomes a sync fallback only when `USE_NEW_RULE_ENGINE=False`. Add idempotency guard keyed by `(document_id, version)`. | 7 |

### Tier 2 — Coverage completion

| # | Item | Phase |
|---|---|---|
| 10 | Build the 11 missing normalizers (journal_entry, general_ledger, ledger, contract, sales_order, quotation, proforma_invoice, receipt_voucher, cash_voucher, supplier_statement, customer_statement). Register in `normalizers/__init__.py`. | 9 |
| 11 | Add Upload + List/Detail API endpoints for the 13 phase-2 doc types. Each typed view follows the existing pattern in `apps/documents/typed_views.py`. | 8 |
| 12 | Bulk + ZIP upload: introduce `BulkUploadJob` + `BulkUploadItem` models, chunk processing via Celery, progress endpoint, retry-failed endpoint. | 10 |

### Tier 3 — Hardening

| # | Item | Phase |
|---|---|---|
| 13 | File-validation scanner integration (clamav side-car or scanner service); per-file states `clean / infected / scan_failed / quarantined`. | 11 |
| 14 | Tests: app registry health, upload→audit single-trigger, tenant isolation, private media, bulk 100 rows, ZIP mixed, Celery idempotency. Walk `cov-fail-under` 45 → 55 → 60 → 70. | 12 |
| 15 | Localization sweep on templates + reports (PDF/Excel/HTML); replace hardcoded `dir="rtl"` and inline strings. | 13 |
| 16 | `.dockerignore` cleanup — exclude `Dataset/`, `Documentation/`, `htmlcov/`, `.coverage`, `*.sqlite3`, etc. | 14 |

### Final deliverable

| # | Item |
|---|---|
| 17 | `Documentation/TADGEEG_PRODUCTION_READINESS_REPORT.md` — Before/After, Risk Register, Coverage Matrices, Deployment Checklist. |

---

## 13. Risk register (concise)

| Risk | Severity | Likelihood | Mitigation phase |
|---|---|---|---|
| `entrypoint.sh` drops production tables on restart | **Critical** | Low (per restart) but 1× = catastrophic | Phase 4 |
| Public S3 / nginx serving financial docs unauthenticated | **Critical** | High in any S3 deploy with current config | Phase 5 |
| Celery not deployed — every `.delay()` is a silent no-op | **Critical** | Certain in current docker-compose | Phase 3 |
| 236 seeded rules pointing at non-existent class | **High** | Certain after seed runs | Phase 6 |
| Two settings files diverged → AppNotFound depending on env | **High** | Certain in prod where `settings/production.py` is used | Phase 2 |
| Invoice upload triggers audit twice (sync + async) | Medium | Certain | Phase 7 |
| Pending unmade migrations on rule_engine models | Medium | Surprise migration on next `makemigrations` | Phase 6/7 |
| 13 doc-type models without HTTP API | Medium | Certain — feature gap | Phase 8 |
| 11 normalizers missing → new rule engine can't run on those types | Medium | Certain | Phase 9 |

---

## 14. What this phase did NOT touch

- No source code edits.
- No migrations created.
- No git commits in Phase 1.
- The 8 commits from the prior session (e810b70 .. a13ab56) remain local on `main` and have not been pushed.

Recommend: **start Phase 2 (settings + URL registry reconciliation)** next — it is the lowest-risk fix that unblocks every later phase by guaranteeing the same set of apps loads regardless of environment.

---

## 15. Additional findings from external review (added 2026-05-10)

A second independent code review surfaced findings that overlap with — and extend — §1–§13. Each item below was cross-checked against the actual repo. **Confirmed** items add to the risk register; **partially overstated** items are kept here for transparency but should not drive Phase 2+ work as-described.

### 15a. Confirmed (need fixes — ranked by tier)

| # | Finding | File:Line | Tier |
|---|---|---|---|
| C1 | `testserver` is unconditionally appended to `ALLOWED_HOSTS` in production. Breaks Django's Host-header injection defense. | [`finai_backend/settings.py:82-84`](finai_backend/settings.py#L82) | **0** (Phase 5 / new) |
| C2 | Prompt-injection vector: OCR text is concatenated into a user message as `f"Document text:\n\n{truncated}"` without XML fencing or instruction-isolation directives. A malicious invoice can override extraction targets. | [`core/services/ai/openai_extractor.py:196`](core/services/ai/openai_extractor.py#L196) | **0** (new) |
| C3 | ZIP validator self-defeats: reads entire archive into memory (`file_obj_or_path.read()` lines 81/87) and calls `zf.testzip()` (line 105) which decompresses everything to verify CRCs — exactly the operation a zip bomb exploits. | [`core/services/zip_validator.py:81,87,105`](core/services/zip_validator.py#L81) | **0** (Phase 11) |
| C4 | Login serializer reveals user existence: distinct error messages and timing for "no account" vs "wrong password" → username enumeration via timing or text. | `apps/authentication/serializers.py` (not yet inspected line-by-line) | **0** (new) |
| C5 | `--cov-fail-under=45` in `pytest.ini` is too lax for a financial-audit system; critical modules (`rule_engine`, `zatca`, `compliance`) need ≥80%. | `pytest.ini` | **3** (Phase 12 — already on plan) |
| C6 | Two ZATCA QR services exist in parallel: `core/services/zatca_service.py` and `apps/compliance/zatca_qr_service.py`. Same role, different code, no canonical pointer. | both files | **2** (extend Phase 7) |
| C7 | `Dockerfile` builds with `requirements.txt` (`>=`); `requirements.lock.txt` exists but is unused → non-reproducible images. | `Dockerfile`, `requirements.lock.txt` | **3** (Phase 14) |
| C8 | `Gunicorn` worker config is fixed (`--workers 3`) with no `--max-requests` / `--max-requests-jitter` → memory creep without recycling. | `docker-compose.yml:30-35` | **3** (Phase 3 add-on) |
| C9 | Dataset directory contains files with very long Arabic filenames that may exceed POSIX/ext4 NAME_MAX (255 bytes) → unreliable extraction in CI/CD. | `Dataset/imag2..imag9/` | **3** (Phase 14 — `.dockerignore` should exclude `Dataset/` anyway) |
| C10 | `effective_role` property maps DB role enum to a different string set than what's in the DB → permission checks may consult two sources of truth. | `apps/authentication/models.py` (not yet inspected line-by-line) | **2** |
| C11 | `Invoice.risk_score` and `validation_score` are `FloatField` while monetary fields are `DecimalField`. Mixing in downstream calculations (`risk_engine.py`) introduces rounding drift. | `apps/invoices/models.py:93+` | **3** |
| C12 | `vat_rate` defaults to 15 with no support for historical rates (5% pre-July-2020). Re-auditing pre-2020 invoices recomputes with wrong rate. | `apps/invoices/models.py` | **3** |
| C13 | No `password_changed_at` / `password_history` on `User` → can't enforce expiry or prevent reuse (common in financial systems). | `apps/authentication/models.py` | **3** |
| C14 | CSP allows `unsafe-inline` and `unsafe-eval` AND lists `https://api.openai.com` in `connect-src` (the browser doesn't need it). Effectively neutralizes the policy. | `core/utils/security_headers.py` | **2** |
| C15 | `apps/frontend/page_views.py` is **4,646 lines / 132 functions** — needs split. | `apps/frontend/page_views.py` | **3** (refactor; not blocking) |

### 15b. Need verification before action (claims I have not yet inspected line-by-line)

These came from the external review but I have not opened the cited files at the cited lines. They go into Phase 2+ verification, not directly into commits.

| # | Claim | Where to verify |
|---|---|---|
| V1 | `MFALoginVerifyView` does not check `user.is_locked()` before validating TOTP → lockout-bypass via valid `temp_token` | `apps/authentication/views.py` ~line 891 |
| V2 | `failed_login_attempts` increment uses read-modify-write (race condition) | `apps/authentication/serializers.py:134-137`, `views.py:946-949` |
| V3 | `mfa_secret` stored as plain `CharField(max_length=64)` (no at-rest encryption) | `apps/authentication/models.py` |
| V4 | No TOTP replay protection (same code reusable inside ±30s window) | `apps/authentication/views.py` MFA flow |
| V5 | ZATCA Phase 2: uses RSA-2048 + RSA-PSS-SHA256 instead of mandated ECC P-256 + ECDSA-SHA256; `canonicalise_xml` silently falls back to UTF-8 when `lxml` is missing | `apps/zatca/crypto.py` |
| V6 | `_fernet()` derives MFA/ZATCA encryption key from `SECRET_KEY` in fallback path → SECRET_KEY leak compromises everything | `apps/zatca/crypto.py:130-134` |
| V7 | Rate limiter has TOCTOU race (`get` then `set/incr` not atomic) and is fail-open on Redis outage; no per-login throttle; superusers exempt | `core/utils/rate_limit.py` |
| V8 | Django upload settings (`DATA_UPLOAD_MAX_MEMORY_SIZE`, `FILE_UPLOAD_MAX_MEMORY_SIZE`, `DATA_UPLOAD_MAX_NUMBER_FIELDS`) not explicitly configured | `finai_backend/settings.py` |
| V9 | `apps/audit_engine/` and `apps/auditing/services/audit_processing_service.py` may be live but unused — needs grep-confirmation before removal | both apps |

### 15c. Partially overstated (downgraded after verification)

| # | Original claim | Reality | Action |
|---|---|---|---|
| O1 | `MissingFieldsRule` is a broken DB reference seeded by migration 0001 | The string `"apps.rule_engine.rules.generic.missing_fields.MissingFieldsRule"` appears **only inside `help_text=` of a CharField definition** in [`migrations/0001_initial.py:187`](apps/rule_engine/migrations/0001_initial.py#L187) and the analogous `help_text` in [`models/rule_definition.py:66`](apps/rule_engine/models/rule_definition.py#L66). It does not create active rule rows. The actual at-risk implementation_class is the `CatalogStubRule` already covered in §7 (236 rows, real impact). | Fix wording in help_text in Phase 6; do not chase as a separate issue. |
| O2 | `app/audit_engine/` is "old but still wired" | Not currently included from `urls.py` (only `apps.audit` is). Models exist; needs grep on imports before claiming "wired." | Verify in Phase 7. |

### 15d. Net effect on the prioritized plan

The Tier-0 list grows from 4 items to **8 items**, in this order:

1. (existing #1) Move DROP TABLE blocks out of `entrypoint.sh` — Phase 4.
2. (new C1) Fix unconditional `testserver` in `ALLOWED_HOSTS` — Phase 2 / 5.
3. (existing #3+#4) Make media private (FS + S3) — Phase 5.
4. (new C2) Sandbox OCR text in OpenAI prompts — Phase 5 / 11.
5. (existing #2) Reconcile `settings.py` vs `settings_canonical.py` — Phase 2.
6. (new C3) Rewrite `zip_validator` (no `testzip`, streaming) — Phase 11.
7. (new C4) Constant-time login + uniform error message — Phase 5.
8. (existing #5) Add `redis` + `celery_*` services to `docker-compose` — Phase 3.

Verification items V1–V9 should be opened in Phase 2 (security-related ones) and Phase 7 (audit-pipeline ones) before patches land.
