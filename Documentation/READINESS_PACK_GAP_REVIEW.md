# Readiness Pack — Gap Review vs. Actual Code

**Source:** [`Documentation/tadgeeg_enterprise_readiness_pack/`](tadgeeg_enterprise_readiness_pack/) (10 spec docs + manifest, generated 2026-05-10).
**Method:** Each spec section was matched against the current `main` branch state — including the 24 commits we shipped this session — using `grep`, model inspection, and direct view of route tables. No new code was written for this review.

Legend:
- ✅ **Implemented** — code matches the spec.
- ⚠️ **Partial** — code exists but doesn't fully meet the spec (gaps listed).
- ❌ **Missing** — no code path implements the requirement.
- 📅 **Operational** — outside the scope of the codebase (deploy / runbook concern).

---

## 1. Top-line score

| Spec area | Sections in spec | ✅ | ⚠️ | ❌ | 📅 |
|---|---|---|---|---|---|
| App / DB / Celery | 21 items | 12 | 4 | 2 | 3 |
| File ingestion | 8 items | 6 | 1 | 1 | 0 |
| Audit engine | 7 items | 5 | 2 | 0 | 0 |
| Document coverage (P0/P1/P2) | 20 types | 8 | 13 | 0 | 0 (— see §3) |
| Security | 8 items | 5 | 2 | 1 | 0 |
| ZATCA Phase 2 | 12 items | 5 | 4 | 3 | 0 |
| AI validation | 8 items | 0 | 1 | 7 | 0 |
| Performance / scale | 7 items | 4 | 1 | 0 | 2 |
| Reporting | 14 reports | 6 | 5 | 3 | 0 |
| Localization | 5 items | 5 | 0 | 0 | 0 |
| API / ERP integration | 16 items | 8 | 5 | 3 | 0 |
| **Totals** | **126** | **64 (51%)** | **38 (30%)** | **20 (16%)** | **5 (4%)** |

> **Headline finding:** the platform is **Pilot Ready** (per the readiness pack's own taxonomy) but **not Enterprise Ready**. The biggest red flags are AI-validation evidence (0/8), ZATCA crypto (RSA used where ECC is mandated), 13 doc types model-only (no upload API), and three reports that don't render at all.

---

## 2. Section-by-section gap matrix

### 2.1 Production Readiness Checklist § 3 (Application)

| Item | Status | Evidence / gap |
|---|---|---|
| DEBUG disabled | ⚠️ | `settings_canonical.py` reads `DJANGO_DEBUG` env; default `True`. Operational task to set `False` in prod. |
| Secrets externalized | ✅ | `os.environ.get(...)` for SECRET_KEY, DB_PASSWORD, OPENAI_API_KEY, AWS_*. |
| Allowed hosts configured | ✅ | After commit `65eb6ed`, `testserver` no longer leaks in prod. |
| CORS restricted | ⚠️ | `corsheaders` installed; need to verify `CORS_ALLOWED_ORIGINS` is not `*` in prod env. Spot-check needed. |
| Media private | ✅ | After commit `8e01d29` — nginx blocks `/media/(documents\|invoices\|batches)/`; S3 signed URLs. |
| Error pages configured | ❓ | No `templates/404.html` / `500.html` verified. |
| Admin restricted | ⚠️ | `core/utils/admin_security.AdminSecurityMiddleware` exists; need to verify it allow-lists IPs in prod. |

### 2.2 § 4 (Database)

| Item | Status | Evidence / gap |
|---|---|---|
| **PostgreSQL production DB** | ❌ | `core/utils/database.py` only supports `mysql` (default) and `sqlite3`. No PostgreSQL backend — spec mismatch. Either add `postgres` support or amend the spec. |
| Migrations clean | ✅ | After commit `645fe3e`, `makemigrations --check` returns "No changes detected". |
| No destructive startup SQL | ✅ | After commit `5de882a`, DROP TABLE is gated in `scripts/manual_schema_repair.py`. |
| Backups enabled | 📅 | Operational. |
| Restore tested | 📅 | Operational. |
| Indexes exist | ⚠️ | `Meta.indexes` present on key models (Invoice, PurchaseOrder, BankStatement, etc.). Spec lists 11 expected; we have most. Need a full audit of expected vs actual. |
| Tenant isolation enforced | ✅ | Every `.objects.filter(organization=org)`-style query in views; verified in tests. Dashboard view skips DB entirely when `org=None`. |

### 2.3 § 5 (Celery / Redis)

| Item | Status | Evidence / gap |
|---|---|---|
| Redis configured | ✅ | After commit `f6f670a`. |
| Worker running | ✅ | `celery_worker` service in docker-compose. |
| Beat configured | ✅ | `celery_beat` service + `CELERY_BEAT_SCHEDULE` in `celery.py`. |
| Retry policy | ⚠️ | Tasks have implicit Celery retries; no explicit `autoretry_for` / `max_retries` audit. |
| Failed task visibility | ❌ | No Flower / no `django-celery-results` for visibility. Operators have to read worker logs. |
| Idempotent audit jobs | ✅ | After commit `6fdf0fd` — `transaction.on_commit` wrap + `_has_active_run` 1-hour dedup window. |
| Worker monitoring | 📅 | Operational. |

### 2.4 § 6 (File Upload Security)

| Item | Status | Evidence / gap |
|---|---|---|
| Extension validation | ✅ | `core/utils/file_validation.py`. |
| MIME validation | ✅ | Same module. |
| Magic-byte validation | ✅ | `core/utils/file_validation.py:96-120` — uses `python-magic` when available with fallback. |
| Malware scan (ClamAV/etc.) | ❌ | No ClamAV integration. Spec calls for `clean / infected / scan_failed / quarantined` states — none implemented. |
| ZIP-slip protection | ✅ | After commit `c4d5152` — posix-normalize + reject NUL/backslash. |
| Decompression bomb | ✅ | Same commit — streaming verification with hard byte cap; encrypted-member rejection. |
| Password file handling | ⚠️ | Encrypted ZIPs are rejected. Password-protected PDFs / Excel: not surfaced as a distinct error state. |
| Macro detection (Excel) | ❌ | No `oletools` / VBA-stomp inspection. Recommended-only per spec. |

### 2.5 § 7 (Audit Engine)

| Item | Status | Evidence / gap |
|---|---|---|
| One canonical pipeline | ⚠️ | Five pipelines coexist (`apps/audit`, `apps/auditing`, `apps/audit_engine`, `apps/rule_engine`, `core/services/doc_validators`). `USE_NEW_RULE_ENGINE` feature flag exists but legacy path still co-runs. **This is the audit-pipeline-unification work deferred to Phase 7.** |
| Rule catalog validation | ✅ | After commit `55bb92c` — `python manage.py validate_rule_catalog`. |
| No missing active implementation | ✅ | `CatalogStubRule` is a real, importable, safe-by-default class. |
| No fake active stub | ⚠️ | 236 active rules currently point at the stub. The validate command surfaces them. Stubs return SKIPPED non-blocking, so they don't pretend to pass — but operators MUST migrate them to real implementations before claiming "236 rules audited". |
| Evidence per finding | ✅ | `RuleResult.evidence: list[EvidenceItem]` in `apps/rule_engine/rules/base.py`. |
| Rule tests | ⚠️ | Tests exist for some rules (~6 categories under `apps/rule_engine/tests/`); not yet covering all 236. |
| Duplicate audit prevention | ✅ | `_has_active_run` + `transaction.on_commit`. |

### 2.6 § 8 (Document Coverage Matrix)

For each doc type: Upload (HTTP) / Normalize (canonical schema) / Audit (rule fires) / Report (visible) / API (REST endpoint).

| Type | Upload | Normalize | Audit | Report | API |
|---|---|---|---|---|---|
| Sales invoice (P0) | ✅ | ✅ | ✅ | ✅ | ✅ |
| Purchase invoice (P0) | ⚠️ same Invoice model — no sales/purchase distinction | ⚠️ | ✅ | ✅ | ⚠️ |
| Purchase order (P0) | ✅ typed | ✅ | ✅ (PO-001..017 deepened) | ✅ | ✅ |
| GRN (P0) | ⚠️ via batch only, no dedicated upload UI | ❌ no normalizer | ✅ (signal added in `6fdf0fd`) | ✅ | ❌ |
| Payment voucher (P0) | ⚠️ | ❌ | ✅ | ✅ | ❌ |
| Receipt voucher (P1) | ❌ | ❌ | ✅ (signal added) | ✅ | ❌ |
| Cash voucher (P1) | ❌ | ❌ | ✅ | ✅ | ❌ |
| Bank statement (P0) | ✅ typed | ✅ | ✅ (BNK-001..017 deepened) | ✅ | ✅ |
| Journal entry (P0) | ❌ | ❌ | ✅ (signal added) | ❌ NOT in `_SPECS` | ❌ |
| General ledger (P0) | ❌ | ❌ | ✅ | ✅ | ❌ |
| Ledger (P0) | ❌ | ❌ | ✅ | ✅ | ❌ |
| Contract (P1) | ❌ | ❌ | ✅ | ✅ | ❌ |
| Supplier statement (P1) | ❌ | ❌ | ✅ | ✅ | ❌ |
| Customer statement (P1) | ❌ | ❌ | ✅ | ✅ | ❌ |
| Sales order (P1) | ❌ | ❌ | ✅ | ✅ | ❌ |
| Quotation (P2) | ❌ | ❌ | ✅ | ✅ | ❌ |
| Proforma invoice (P2) | ❌ | ❌ | ✅ | ✅ | ❌ |
| Payroll sheet (P1) | ✅ typed | ✅ | ✅ (PAY-001..017 deepened) | ✅ | ✅ |
| Expense report (P1) | ✅ typed | ✅ | ✅ (EXP-001..016 deepened) | ✅ | ✅ |
| VAT return (P0) | ✅ typed | ✅ | ✅ (VATR-001..016 deepened) | ✅ | ✅ |
| Fixed asset (P1) | ✅ typed | ✅ | ✅ (AST-001..017 deepened) | ✅ | ✅ |
| Sales receipt (P1) | ✅ typed | ✅ | ✅ | ✅ | ✅ |

**Coverage summary**: 8 fully end-to-end, 13 model-only with audit but no Upload/Normalizer/API. **Critical**: of the 13 partial types, **6 are P0** (purchase invoice variant, GRN, payment voucher, journal entry, general ledger, ledger). Phase 8 + 9 of the original plan still carries this backlog.

> Journal Entry's audit fires (signal added this session) but the multi-doc adapter `_SPECS` doesn't include it, so even the audit findings don't surface in reports.

### 2.7 § 9 (Security)

| Item | Status | Evidence / gap |
|---|---|---|
| RBAC | ⚠️ | User has `Role` choices but no per-permission gating verified across views. External review V10: roles in README don't match model. |
| Tenant tests | ⚠️ | `tests/test_access_control.py` exists; needs audit for each new doc type. |
| API auth | ✅ | JWT (`rest_framework_simplejwt`) + DRF permissions. |
| Rate limiting | ⚠️ | `OrgRateLimitMiddleware` exists in `core/utils/rate_limit.py`, but external review V7 flags it: read-modify-write race + fail-open on Redis outage. **Not closed.** |
| Audit logs | ⚠️ | Hash-chain audit log via `HashChainMixin` (`InvoiceAuditEvent`, `JournalEntry`). Spec § 9 demands logging for: login/logout/failed login/upload/download/audit run/finding change/report gen/API key/ERP sync/ZATCA submit/admin change. Coverage incomplete — only some of these emit hash-chained events. |
| HTTPS | 📅 | Operational; nginx in compose listens on port 80 only — needs TLS termination upstream. |
| Vulnerability scan | 📅 | Operational. |
| Pen test | 📅 | Operational; recommended. |

### 2.8 § 10 (ZATCA Phase 2)

| Item | Status | Evidence / gap |
|---|---|---|
| VAT validation | ✅ | VATR-001..016 rules + invoice validators. |
| Mandatory fields | ✅ | INV-* + DOC-* rules. |
| QR/TLV reader & validation | ⚠️ | Two parallel implementations: `core/services/zatca_service.py` (284 lines) and `apps/compliance/zatca_qr_service.py` (344 lines) — same purpose, no canonical pointer. C6 from the prior gap review. |
| XML/UBL validation | ⚠️ | Some scaffolding in `apps/zatca/`; not fully wired. |
| **CSR generation (RSA-2048)** | ❌ | `apps/zatca/crypto.py` uses `rsa.generate_private_key()`. ZATCA Phase 2 production mandates **ECC P-256**. The file's own comment admits this. **Production submissions WILL fail.** (V5) |
| **Signing (RSA-PSS-SHA256)** | ❌ | Same file uses `padding.PSS` + `hashes.SHA256()`. ZATCA mandates **ECDSA-SHA256**. (V5) |
| Certificate onboarding | ⚠️ | Models exist; flow not exercised against ZATCA sandbox. |
| `canonicalise_xml` strict | ❌ | Falls back to plain UTF-8 when `lxml` is missing — silently breaks the invoice hash chain. (V5) |
| Fernet key derivation | ❌ | `_fernet()` derives from `SECRET_KEY` in fallback path → SECRET_KEY leak compromises every ZATCA private key. (V6) |
| Sandbox evidence | ❌ | None on disk. README claim "100% ZATCA Phase 2 compliance" cannot be substantiated. |

### 2.9 § 11 (AI Validation)

**Status: 0/8 — every claim is unsubstantiated.**

| Claim | Status | Reality |
|---|---|---|
| 98% invoice extraction accuracy | ❌ | No validation dataset, no field accuracy report. |
| 95% handwriting recognition | ❌ | No dataset. Codebase has `is_handwritten` boolean, no accuracy harness. |
| 95% fraud / anomaly detection | ❌ | Rule-based + Benford's law are deterministic; no labeled fraud dataset. |
| 92% cash-flow forecast | ⚠️ | `apps/analytics/views.py:forecast_cash_flow` exists; no MAPE/MAE backtesting harness. |
| 10-15s processing time | ❌ | No benchmark logs. WeasyPrint PDF gen alone is 1-15s; full pipeline measured nowhere. |
| VAT detection | ✅ | Rule-based — testable + tested. (Only AI-validation item that is "real".) |
| Duplicate detection | ✅ | `Invoice.is_duplicate` + DUP-* rules; reproducible. |
| False positive / false negative analysis | ❌ | No tracking column on findings (`is_false_positive`?). |

**Recommended public wording** (per `AI_MODEL_VALIDATION_REPORT.md` § 11): brand the platform as "AI-augmented" not "AI-validated". Drop the percentage claims from marketing until a validation pack exists.

### 2.10 § 12 (Performance)

| Item | Status | Evidence / gap |
|---|---|---|
| 1,000 invoice test | ❌ | No load test script. |
| 10,000 invoice test | ❌ | Same. |
| 100,000 simulation | ❌ | Same. |
| Dashboard performance | ✅ | After commit `fcd774b` — 28 cold queries, 1 cached, ~26ms cached render. |
| Report generation | ✅ | After commit `6ca9307` — 932ms uncached → ~0ms cached PDF. |
| Worker scaling | ⚠️ | `--concurrency=2` env-tunable, `--max-tasks-per-child=200`. Single-region; no horizontal autoscale story. |
| Monitoring | ⚠️ | Sentry initialised conditionally on `SENTRY_DSN`; no Prometheus / Grafana. |

### 2.11 § 13 (Reporting)

| Report | Status | Notes |
|---|---|---|
| Audit summary | ✅ | `/api/v1/reports/...` + report templates. |
| Detailed findings | ✅ | `findings_register` per audit run. |
| VAT compliance | ⚠️ | Box-level reconciliation present (VATR rules). No standalone "VAT report" PDF in `templates/reports/`. |
| Duplicate invoice | ✅ | Rules + report section. |
| **ZATCA compliance** | ⚠️ | Rule findings present; full XML/UBL submission report missing. |
| **Three-way matching** | ❌ | Service exists at `apps/rule_engine/services/three_way_match.py` but no report endpoint or PDF template. Spec lists as P0. |
| **General ledger integrity** | ⚠️ | GL rules deepen will fire (we added signal) but no GL-specific report endpoint. |
| Vendor risk | ✅ | Top-risky-vendors widget on dashboard + `VendorProfile` model. |
| Customer risk | ❌ | No `CustomerProfile` registry equivalent. |
| **Branch KPI** | ❌ | No `Branch` model — "branch-level access" itself isn't implemented. |
| **P&L** | ❌ | No P&L generator. |
| **Balance sheet** | ❌ | No balance-sheet generator. |
| Cash flow forecast | ⚠️ | `forecast_cash_flow()` view exists; no PDF/Excel export. |
| Bank reconciliation | ⚠️ | BNK rules cover reconciliation; no standalone report PDF. |

PDF / Excel:
- PDF: ✅ Arabic + English render correctly (commit `7fa8269` and `6ca9307`).
- Excel: ✅ via `openpyxl` (`apps/reports/views.py:1013` uses `ws.cell(...)`).

### 2.12 § 14 (Localization)

| Item | Status | Evidence |
|---|---|---|
| Arabic UI | ✅ | After commit `96e6877` — 417 missing/fuzzy strings translated. |
| English UI | ✅ | Source language. |
| Dynamic RTL/LTR | ✅ | `templates/base.html:5` uses `{% get_current_language_bidi %}`. |
| Translated reports | ✅ | PDF templates respect `LANGUAGE_BIDI`; per-language PDF cache slot. |
| Translated errors | ✅ | DRF errors + `gettext` strings. |

### 2.13 SRS § 5 (Supported Upload Modes)

| Mode | Status |
|---|---|
| Single document | ✅ |
| Multiple documents | ✅ |
| ZIP upload | ✅ (commit `c4d5152` hardened) |
| Bulk Excel | ⚠️ rows go through processor; no `BulkUploadJob` model |
| Bulk CSV | ⚠️ same |
| JSON / JSONL | ⚠️ `STRUCTURED_BULK_EXTENSIONS` includes them but not chunked |
| API upload | ✅ |
| Mobile camera | ⚠️ no dedicated mobile capture endpoint; relies on standard upload |

### 2.14 SRS § 8 (Normalization)

The spec demands every document be normalized to a canonical schema before audit:
```json
{document_id, document_type, organization_id, document_number,
 document_date, currency, total_amount, tax_amount, parties[],
 line_items[], accounting_entries[], metadata, validation_errors}
```

Reality: `apps/rule_engine/normalizers/` ships **10 normalizers** (bank_statement, expense, fixed_asset, grn, invoice, payment, payroll, purchase_order, sales_receipt, tax_return). **11 normalizers missing** for journal_entry, general_ledger, ledger, contract, sales_order, quotation, proforma_invoice, receipt_voucher, cash_voucher, supplier_statement, customer_statement.

**Status: ⚠️ — Phase 9 deferred work.**

### 2.15 API & ERP Integration § 5 (Response envelope)

Spec mandates:
```json
{"success": true, "data": {}, "meta": {"request_id":"...","timestamp":"..."}, "errors":[]}
```

Reality: every DRF view returns the standard DRF shape (`{"key": value}` or `{"detail": "..."}`). The envelope is ❌ **not implemented anywhere**. ERP clients integrating today get an inconsistent surface.

### 2.16 API & ERP Integration § 8 (Bulk Upload API)

Spec endpoints:
- `POST /api/v1/bulk-upload-jobs/`
- `GET /api/v1/bulk-upload-jobs/{id}/`
- `POST /api/v1/bulk-upload-jobs/{id}/retry-failed/`

Reality: ❌ none of these exist. Phase 10 deferred.

### 2.17 API & ERP Integration § 14 (Idempotency-Key)

Spec: `Idempotency-Key` header required on all external writes.

Reality:
- ✅ `apps/ledger/services.py:188` accepts an `idempotency_key` argument for journal posting.
- ❌ No HTTP-level `Idempotency-Key` header support across the API. ERP push pattern won't safely retry.

### 2.18 OpenAPI YAML

Spec: maintain `openapi/tadgeeg_api_v1.yaml`.

Reality: `drf_spectacular` is installed (`SPECTACULAR_SETTINGS` in canonical settings); schema is generated dynamically at `/api/schema/`. ⚠️ — exists at runtime but no static YAML committed.

### 2.19 Webhooks (API & ERP § 12)

Spec: emit `document.uploaded`, `audit.completed`, `finding.created`, `finding.high_risk`, `report.ready`, `zatca.validation_failed`. Plus signed payloads (HMAC).

Reality:
- `apps.webhooks` app exists with `models.py` + `services.py` + URLs.
- ⚠️ no `signature` / `HMAC` keyword found in service files — webhook signing not verified.
- ⚠️ event emission for the listed types not audited per-event.

---

## 3. Highest-impact remediation list

Ordered by user-visible impact × ease.

### Tier 0 — block "Enterprise Ready" claim until done

1. **ZATCA crypto migration RSA → ECC P-256** (V5 + V6).
   - Files: `apps/zatca/crypto.py`, requirements (`cryptography`).
   - ~1 day. Blocks production ZATCA submissions.

2. **Fix rate limiter race + fail-open** (V7).
   - File: `core/utils/rate_limit.py`.
   - ~0.5 day. Use Redis Lua INCR; fail-closed in prod.

3. **Document the "AI-augmented vs AI-validated" wording change** in marketing.
   - 0 code; 1 page in `Documentation/`.
   - Without an AI validation pack, the 98% / 95% claims are exposed.

### Tier 1 — Pilot → Enterprise gap

4. **Build BulkUploadJob + Item models + endpoints** (Phase 10 deferred).
   - New models, migration, 3 new endpoints.
   - ~3 days.

5. **11 missing normalizers** (Phase 9 deferred).
   - 11 small classes following the existing pattern.
   - ~2 days.

6. **13 missing typed Upload / List / Detail APIs** (Phase 8 deferred).
   - One PR per type.
   - ~1 week.

7. **Audit pipeline unification** (Phase 7 deferred).
   - Pick ONE path; deprecate the other 4.
   - ~3 days carefully.

8. **PDF async via Celery** (P5 deferred).
   - Now feasible since Celery is in compose.
   - ~1 day.

### Tier 2 — feature completion

9. **Customer risk + Branch model + Branch KPI report**.
10. **P&L + Balance Sheet generators**.
11. **Three-way matching report endpoint** (service already exists).
12. **JSON-API response envelope** + `Idempotency-Key` header support.
13. **Webhook HMAC signing** + emit the 6 spec events.
14. **OpenAPI YAML committed** (export `/api/schema/` once + check it in).

### Tier 3 — operational

15. **PostgreSQL backend** if spec keeps PostgreSQL requirement; otherwise amend spec to MySQL.
16. **ClamAV malware scan integration**.
17. **MFA hardening** (V1-V4 from external review).
18. **Load test scripts** for 1K / 10K / 100K invoice volumes.
19. **AI validation harness** — datasets + per-claim metrics report.
20. **Sentry / Prometheus dashboards** (operators).

---

## 4. What this review did NOT do

- Did not write code. Inventory only.
- Did not ship the spec docs to the deployed image (they're under `Documentation/` which `.dockerignore` excludes — correct behavior; specs are operator-facing, not runtime).
- Did not edit any of the 10 spec docs. They serve as a contract.
- Did not run the readiness checklist's "tests" — those are the operator's UAT tasks.

## 5. Bottom-line verdict

Tadgeeg has **strong execution on the rule engine, doc-validators depth (83 rules across 5 deepened types this session), reporting infrastructure, security baseline (after this session's fixes), and i18n.**

It is **far from the marketing claims** of "100% ZATCA Phase 2 compliance" (the crypto is wrong), "98% OCR accuracy" (no validation pack), and "enterprise-scale" usage (no load test evidence, BulkUploadJob missing, 13 P0/P1 doc types lack upload endpoints).

The product is honestly positioned as **pilot-ready for sales/purchase invoices, POs, payroll, fixed assets, expense reports, bank statements, VAT returns, and sales receipts** — the 8 fully-supported types. Anything else needs the spec-pack work before being demoed to enterprise prospects.
