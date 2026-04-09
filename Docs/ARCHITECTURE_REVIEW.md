# Architectural Review — Tadgeeg AI Financial Audit Platform
**Date:** 2026-04-08
**Reviewer:** Senior Software Architect (Claude Sonnet 4.6)
**Scope:** Full codebase — models, views, serializers, services, pipeline, tasks, signals, settings

---

## A. Executive Summary

**Overall Health Score: 6.2 / 10**

| Risk Dimension | Rating | Assessment |
|---|---|---|
| Architectural | HIGH | Fat views, dual pipeline, legacy ghost apps |
| Maintainability | HIGH | 1,952-line view file, logic in wrong layers |
| Scalability | MEDIUM | Good Celery setup, but missing idempotency keys & task priority |
| Testability | HIGH | Business logic in views/serializers makes unit testing expensive |
| Security | LOW | Solid: HSTS, CSP, JWT cookies, RBAC, soft delete |

**Main architectural risks:**
1. `invoices/views.py` at 1,952 lines owns HTTP, validation, risk merging, batch processing, and approval simultaneously
2. Two parallel audit engines exist without a clean deprecation path (`apps/audit_engine/`, `apps/auditing/`, `core/pipeline.py`, `rule_engine/pipeline/v2/`)
3. Business logic distributed across views, models, serializers, signals, and services with no enforced layer contract

---

## B. Critical Problems

### 1. `invoices/views.py` — 1,952 Lines (CRITICAL)
Every future invoice feature gets added here. HTTP handling, file parsing, ZIP extraction, validation orchestration, risk score merging, batch processing, and approval workflow — all in one file. Tests for any single piece require the entire Django request cycle.

### 2. Three Competing Audit Engines (CRITICAL)
`apps/audit_engine/` (legacy), `apps/auditing/services/audit_processing_service.py` (deprecated), and `apps/rule_engine/pipeline/v2/` (current) all exist with partial wiring. Bugs can be "fixed" in V2 but silently still trigger via a legacy path.

### 3. Fat `core/services/financial_ai_engine.py` — 480 Lines, 6 Responsibilities (HIGH)
Classification, extraction, normalization, duplicate detection, fraud detection, and risk scoring in one class. A change to fraud logic requires testing the entire AI engine.

### 4. No Service Layer Contract (HIGH)
No base class, interface, or protocol enforcing service return types. Callers must know the internal return structure of each service. When a service changes its return shape, callers break silently.

### 5. Business Logic in `SerializerMethodField` (MEDIUM)
`AuditRunSummarySerializer.get_pass_rate()`, `get_top_failures()` contain calculation logic that cannot be reused outside an API response.

### 6. Soft Delete Without a Manager (HIGH)
No custom `SoftDeleteManager`. Every queryset must manually add `.filter(is_deleted=False)`. One missed filter leaks deleted records.

### 7. `models_old.py` in Invoices App (MEDIUM)
A file named `models_old.py` exists in production code — a live landmine.

### 8. No Idempotency Keys on Celery Tasks (HIGH)
`process_document_task` has no deduplication guard. A double-upload or retry storm produces duplicate `ExtractedData` and `DocumentAnalysisResult` rows.

---

## C. Violations by Principle

### Clean Code Violations

| Location | Violation | Severity |
|---|---|---|
| `invoices/views.py` | `_merge_risk_assessment`, `_fallback_risk_score` are private helpers doing domain logic | Critical |
| `financial_ai_engine.py` | Class name is too broad — it is 6 services combined | High |
| `models_old.py` | Dead code in production | Medium |
| `core/services/` | 50+ files with no enforced naming convention | Medium |
| `AuditRun.error_log` | JSON array stored as text — no schema, no queryability | Medium |
| `Invoice.generate_zatca_qr()` | Crypto-level operation in model method | High |

### SOLID Violations

**SRP**
- `invoices/views.py`: HTTP + validation + batch + approval + risk scoring
- `FinancialAIEngine`: Classification + extraction + dedup + fraud + anomaly + scoring
- `process_document_task`: orchestrates entire pipeline (should delegate to a service)

**OCP**
- Adding a new document type requires modifying 5 files: normalizers, rules directory, models choices, typed serializers, classification logic

**DIP**
- `core/services/pipeline.py` directly imports `FinancialAIEngine`, `DocumentEngine`, `AuditEngine` — no injection
- `rule_engine/pipeline/stages/ai_engine.py` hardcodes `FinancialAIEngine` — cannot swap AI provider

### DRY Violations

| Duplication | Location | Impact |
|---|---|---|
| Risk score merging logic | `invoices/views.py` AND `core/services/scoring/risk_engine.py` | Two sources of truth |
| Organization filter | Every view's `get_queryset()` manually filters by organization | 20+ duplications |
| Permission check | Inline `has_role_capability()` checks scattered across views | High |
| Document status update | `document.processing_status = "completed"; document.save()` in multiple places | Medium |
| `is_deleted=False` filter | Added manually to every queryset | High |

### Separation of Concerns Violations

| What | Where it should be | Where it actually is |
|---|---|---|
| Invoice VAT calculation | Service | `Invoice` model property |
| ZATCA QR generation | `core/services/compliance/zatca_service.py` | `Invoice.generate_zatca_qr()` model method |
| Pass rate calculation | Service or model | `AuditRunSummarySerializer.get_pass_rate()` |
| Risk score aggregation | `RiskEngineStage` | Also in `invoices/views.py` helper functions |
| Organization tenant filter | Base queryset mixin | Every view manually |
| Audit log creation | Centralized service | Scattered across view methods |

### Django Architecture Violations

| Violation | Location |
|---|---|
| Fat views | `invoices/views.py` (1,952), `reports/views.py` (1,130), `authentication/views.py` (990) |
| Fat models with business logic | `Invoice`, `User` |
| Signals triggering business logic | `documents/signals.py` — triggers audit pipeline |
| No custom manager for soft delete | All soft-delete models |
| Missing `select_related`/`prefetch_related` | `reports/views.py`, `audit/views.py` |
| Single settings file | `finai_backend/settings.py` |
| No transaction boundaries | `invoices/views.py` batch processing, pipeline V2 stages |

---

## D. Refactoring Plan

### Phase 0 — Safety Net (Week 1)
Write integration tests covering critical paths before touching anything.

### Phase 1 — Quick Structural Wins (Week 1–2)
Actions 1, 3, 4, 5, 7, 11 — additive or low-risk reorganizations.

### Phase 2 — Service Extraction (Month 1–2)
Actions 2, 8, 9, 10, 13, 14 — pull business logic out of views, models, serializers.

### Phase 3 — Engine Consolidation (Month 2–3)
Actions 6, 15, 16, 17 — break AI engine, formalize pipeline, kill legacy code.

### Phase 4 — Scale Preparation (Ongoing)
Actions 12, 18, 19, 20 — idempotency, N+1 fixes, tracing.

---

## E. Proposed Target Architecture

```
tadgeeg/
├── finai_backend/
│   ├── settings/
│   │   ├── base.py
│   │   ├── production.py
│   │   └── test.py
│   ├── urls.py
│   └── wsgi.py
│
├── core/
│   ├── domain/                  ← NEW: pure domain objects (no Django)
│   │   ├── result.py            ← ServiceResult, ServiceError
│   │   └── money.py             ← Money value object
│   ├── services/
│   │   ├── ai/                  ← split FinancialAIEngine here
│   │   │   ├── classifier.py
│   │   │   ├── extractor.py
│   │   │   ├── duplicate_detector.py
│   │   │   └── fraud_analyzer.py
│   │   ├── pipeline/
│   │   ├── parsers/
│   │   ├── scoring/
│   │   └── compliance/
│   ├── mixins/                  ← NEW: reusable view mixins
│   │   ├── organization.py      ← OrganizationQuerySetMixin
│   │   └── audit_log.py
│   └── utils/
│
├── apps/
│   ├── invoices/
│   │   ├── services/            ← NEW
│   │   │   ├── invoice_validation_service.py
│   │   │   ├── batch_processor_service.py
│   │   │   └── approval_service.py
│   │   ├── views.py             ← thin, delegates to services
│   │   ├── models.py
│   │   └── managers.py          ← NEW: SoftDeleteManager
│   │
│   ├── rule_engine/
│   │   └── registry.py          ← NEW: document type → rules mapping
│   │
│   ├── audit/
│   │   └── services/
│   │       └── case_service.py
│   │
│   └── reports/
│       └── services/
│           ├── report_generation_service.py
│           └── pdf_service.py
```

---

## F. File-by-File Review

| File | Lines | Problems | Fix |
|---|---|---|---|
| `apps/invoices/views.py` | 1,952 | HTTP + validation + batch + approval mixed | Extract 3 service classes |
| `core/services/financial_ai_engine.py` | 480 | 6 responsibilities in one class | Split into 4 focused services |
| `apps/authentication/views.py` | 990 | Login + registration + user mgmt + org creation | Split into 3 ViewSets |
| `apps/reports/views.py` | 1,130 | Report generation + PDF + aggregations in views | Extract ReportGenerationService |
| `apps/invoices/models.py` | 478 | `generate_zatca_qr()`, `expected_vat`, `vat_is_correct` in model | Move to service |
| `finai_backend/settings.py` | 506 | Single file for all environments | Split to base/production/test |
| All soft-delete models | — | No SoftDeleteManager | Add manager |
| `apps/invoices/models_old.py` | ? | Dead code | Delete after confirming no imports |

---

## G. Safe Refactor Order

1. Write integration tests first (invoice pipeline, audit V2, auth)
2. Add `SoftDeleteManager` — additive, zero breakage
3. Add `OrganizationQuerySetMixin` — additive mixin
4. Split settings — pure reorganization
5. Extract `InvoiceValidationService`
6. Extract `ReportGenerationService`
7. Break `FinancialAIEngine` into 4 services
8. Remove legacy engines (`apps/audit_engine/`, `apps/auditing/services/audit_processing_service.py`)

---

## Top 20 Highest-Value Refactor Actions

| # | Action | Impact | Effort | Risk |
|---|---|---|---|---|
| 1 | Add `SoftDeleteManager` to all soft-delete models | Prevents data leaks | Low | None |
| 2 | Extract `InvoiceValidationService` from views | Enables unit testing | Medium | Low |
| 3 | Extract `BatchProcessorService` from views | Isolates batch logic | Medium | Low |
| 4 | Add `@transaction.atomic` to all multi-write operations | Prevents partial state | Low | None |
| 5 | Add `OrganizationQuerySetMixin` | Eliminates 20+ manual filters | Low | None |
| 6 | Split `FinancialAIEngine` into 4 focused services | Independent testing/swapping | High | Medium |
| 7 | Split settings into base/production/test | Prevents dev config leak | Low | None |
| 8 | Move `Invoice.generate_zatca_qr()` to `ZatcaService` | Decouples model | Low | Low |
| 9 | Move `Invoice.expected_vat`/`vat_is_correct` to service | Model should not own financial rules | Low | Low |
| 10 | Move serializer pass_rate/top_failures to model method | Makes metrics reusable | Low | None |
| 11 | Define `ServiceResult(data, error, success)` base class | Standardizes return types | Low | None |
| 12 | Add Celery idempotency keys to `process_document_task` | Prevents duplicate processing | Medium | Low |
| 13 | Extract `ReportGenerationService` from reports views | 1,130-line view becomes testable | Medium | Low |
| 14 | Split `authentication/views.py` into 3 ViewSets | Isolation of concerns | Medium | Low |
| 15 | Make `AuditPipelineV2` accept injected stages list | Enables test pipelines | Low | None |
| 16 | Create single `document_type_registry.py` | One file for new doc types | Medium | Medium |
| 17 | Remove `apps/audit_engine/` and legacy adapters | Kill dead code | Low | Medium |
| 18 | Add `select_related`/`prefetch_related` to list views | N+1 prevention | Low | None |
| 19 | Add OpenTelemetry spans to pipeline stages | Observability at scale | Medium | None |
| 20 | Write `tests/integration/test_invoice_pipeline.py` | Foundation for all refactors | High | None |

---

## Predictive Rules Roadmap (from rules.md)

The following 10 predictive rules (PRD-001 to PRD-010) are designed for the next phase.
The existing `BaseRule` architecture in `apps/rule_engine/rules/base.py` supports all of them.
Start with PRD-001 and PRD-004 as highest CFO value.

| Code | Rule | Priority |
|---|---|---|
| PRD-001 | Cash Flow Forecast — predict payments due in 30-90 days | HIGH |
| PRD-002 | Price Variance Trend — forecast vendor price increases | MEDIUM |
| PRD-003 | Delivery Delay Risk — predict late delivery from vendor history | MEDIUM |
| PRD-004 | Budget Burn Rate — predict when cost centers exhaust budget | HIGH |
| PRD-005 | Vendor Risk Scoring — dynamic risk score per vendor | MEDIUM |
| PRD-006 | Missing Invoice Prediction — detect unclosed POs | MEDIUM |
| PRD-007 | Seasonality Analysis — forecast peak spend periods | LOW |
| PRD-008 | Classification Suggestion — AI cost center prediction | MEDIUM |
| PRD-009 | Split PO Detection — detect authorization bypass | HIGH |
| PRD-010 | Procurement Efficiency — aggregate savings from PO consolidation | LOW |
