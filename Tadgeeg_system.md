# Tadgeeg — Living System Documentation
> Auto-generated gap audit. Last updated: 2026-03-23.

---

## 1. System Overview

**Tadgeeg** is a multi-tenant AI-powered financial auditing SaaS for Arabic-speaking organizations.
It processes invoices and financial documents, applies 34+ rule-based compliance checks, and produces bilingual (AR/EN) audit reports.

### Key Concepts
| Concept | Description |
|---------|-------------|
| **Organization** | Top-level tenant; every model scoped by `organization` FK |
| **Invoice** | Core financial document; linked to `InvoiceValidationResult` (34 boolean fields) |
| **Document** | Non-invoice typed doc (PO, payroll, VAT return, etc.) — 8 types |
| **Rule Engine** | 34 rules across 6 categories (header, duplicate, VAT, anomaly, control, document) |
| **Report** | Saved JSON snapshot of any report; type stored in `Report.report_type` |
| **AuditSession** | Groups a batch of uploaded invoices for one audit cycle |

---

## 2. Application Map

```
apps/
├── authentication/     User, Organization, subscription
├── invoices/           Invoice, InvoiceValidationResult, vendor profiles
├── documents/          Document (8 typed sub-models), typed views/serializers
├── auditing/           AuditDocument pipeline (OCR → parse → validate → AI)
├── audit/              AuditCase, AuditSession, AuditFinding
├── compliance/         ComplianceRule, ComplianceViolation
├── reports/            Report model + 4 service layers + templates
│   ├── services/
│   │   └── invoice_audit_service.py   ← InvoiceAuditReportService (v2)
│   ├── invoice_report_views.py        ← /api/v1/reports/invoice-audit/*
│   ├── document_views.py              ← /api/v1/reports/document/* + executive/*
│   ├── invoice_serializers.py         ← DRF DTOs for invoice audit report
│   ├── document_serializers.py        ← DRF DTOs for document/executive reports
│   └── templatetags/report_filters.py ← custom |replace filter
├── transactions/       Transaction model
├── analytics/          AnalyticsEvent
└── frontend/           Page views (SSR Django templates)
```

---

## 3. Report System — Endpoints

### Invoice Audit Report v2 (new service layer)
| Method | URL | Name |
|--------|-----|------|
| POST | `/api/v1/reports/invoice-audit/` | `invoice-audit-generate` |
| GET | `/api/v1/reports/invoice-audit/<pk>/` | `invoice-audit-detail` |
| GET | `/api/v1/reports/invoice-audit/<pk>/html/` | `invoice-audit-html` |
| GET | `/api/v1/reports/invoice-audit/<pk>/pdf/` | `invoice-audit-pdf` |
| GET | `/api/v1/reports/invoice-audit/<pk>/high-risk/` | `invoice-audit-high-risk` |
| GET | `/api/v1/reports/invoice-audit/<pk>/failed-rules/` | `invoice-audit-failed-rules` |
| GET | `/api/v1/reports/invoice-audit/<pk>/supplier-analysis/` | `invoice-audit-supplier-analysis` |
| GET | `/api/v1/reports/invoice-audit/<pk>/compliance/` | `invoice-audit-compliance` |

### Executive Report
| Method | URL | Name |
|--------|-----|------|
| POST | `/api/v1/reports/executive/` | `executive-report-generate` |
| GET | `/api/v1/reports/executive/latest/` | `executive-report-latest` |
| GET | `/api/v1/reports/executive/<pk>/html/` | `executive-report-html` |
| GET | `/api/v1/reports/executive/<pk>/pdf/` | `executive-report-pdf` |

### Document Report
| Method | URL | Name |
|--------|-----|------|
| POST | `/api/v1/reports/document/` | `document-report-generate` |
| GET | `/api/v1/reports/document/<pk>/` | `document-report-detail` |
| GET | `/api/v1/reports/document/<pk>/html/` | `document-report-html` |
| GET | `/api/v1/reports/document/<pk>/pdf/` | `document-report-pdf` |

---

## 4. Templates Map

| Template | Used By | Status |
|----------|---------|--------|
| `reports/invoice_audit_report_v2.html` | `InvoiceAuditReportHTMLView`, `InvoiceAuditReportPDFView` | ✅ Created |
| `reports/document_audit_report.html` | `DocumentReportHTMLView`, `DocumentReportPDFView` | ✅ Created (uses `report_filters`) |
| `reports/executive_report.html` | `ExecutiveReportHTMLView`, `ExecutiveReportPDFView` | ✅ Created |
| `reports/index.html` | `/reports/` dashboard | ✅ Updated (wired to v2 endpoints) |
| `reports/invoice_audit_report.html` | Legacy `/reports/invoice-audit/` page | ⚠️ Legacy — uses old data format |
| `reports/invoice_audit_report_pdf.html` | Legacy PDF download | ⚠️ Legacy |

---

## 5. Rule Engine — 34 Rules

| Group | Rules | Inverted? |
|-------|-------|-----------|
| Header (HDR-001–008) | Invoice #, Date, Vendor Name, VAT #, Amount, Currency, Amount>0, No VAT without base | No |
| Duplicate (DUP-001–005) | Number dup, Vendor+Number dup, Vendor+Amount+Date dup, File hash dup, Cross-month dup | **Yes** (True = problem) |
| VAT (VAT-001–005) | Rate correct, Calculation correct, Subtotal correct, VAT number present, QR code valid | No |
| Anomaly (ANO-001–006) | High amount, New vendor, Many same-day, Price change, Year-end surge, Vendor dominates | **Yes** (True = anomaly) |
| Control (CTL-001–006) | Cost center, Account code, Within budget, No edit after approve, Has approver, Audit trail | No |
| Document (DOC-001–004) | Document clear, Appears genuine, No alterations, QR present | No |

Risk thresholds: **Safe ≥ 85**, **Review ≥ 60**, **High Risk < 60**

---

## 6. Security — Multi-Tenant Isolation

- **ORM**: Every queryset filtered by `organization=request.user.organization`
- **Admin**: All `ModelAdmin` classes override `get_queryset()` to filter by org
- **Report access**: `_TenantReportMixin` returns 404 (not 403) on cross-tenant access
- **File uploads**: `organization` injected server-side, never trusted from client
- **JWT auth**: Cookie-based; `JWTCookieAuthentication` as default DRF authenticator

---

## 7. Gap Audit — Status

### ✅ Fixed Gaps

| # | Gap | Fix Applied |
|---|-----|-------------|
| G-001 | `TemplateSyntaxError: Invalid filter: 'replace'` in `document_audit_report.html` | Created `apps/reports/templatetags/report_filters.py` with custom `replace` filter; added `{% load report_filters %}` |
| G-002 | Missing `templates/reports/invoice_audit_report_v2.html` | Created full professional bilingual template |
| G-003 | Dashboard `generate()` for `invoice_audit` still called old `/reports/generate/` endpoint | Updated `index.html`: `invoice_audit` now calls `POST /api/v1/reports/invoice-audit/` (v2 service) |
| G-004 | `fullReportUrl` for `invoice_audit` pointed to legacy frontend page | Updated to `/api/v1/reports/invoice-audit/<id>/html/` |
| G-005 | `AttributeError: 'RuleDefinitionTranslation' object has no attribute 'name_ar'` in `views.py:439` | Fixed translation lookup to use `name` field + `language` field pattern |
| G-006 | `VariableDoesNotExist` in `executive_report.html` VAT section | Removed broken `{% with %}` expression; replaced with safe `widthratio` |

### ⚠️ Known Remaining Items

| # | Item | Priority | Notes |
|---|------|----------|-------|
| R-001 | Legacy `/reports/invoice-audit/` frontend page uses old data format | Low | Keep for backwards compat; old reports still readable |
| R-002 | Test coverage at 17% (required: 45%) | High | Need to add tests for `InvoiceAuditReportService`, new views, and template rendering |
| R-003 | No Celery task for async report generation (large orgs may timeout) | Medium | Current: sync inside request cycle; add `generate_invoice_audit_report.delay()` |
| R-004 | `InvoiceAuditReportService._build_anomalies()` dominant-supplier threshold hardcoded at 40% | Low | Move to `RISK_THRESHOLDS` or settings |
| R-005 | `WeasyPrint` PDF fallback silently returns HTML — client gets wrong `Content-Type` | Medium | Log warning; consider returning 500 + JSON error instead |
| R-006 | `HighRiskInvoicesView` default limit is 25 but service `_build_high_risk_invoices(limit=25)` already slices | Low | Double-slicing is harmless but misleading |
| R-007 | `report_filters.replace` filter only replaces with space (no target arg) — non-obvious API | Low | Acceptable for current single use-case |

---

## 8. Recommended Next Actions (Priority Order)

1. **[HIGH] Add tests** for `InvoiceAuditReportService` (unit) and new API views (integration) to raise coverage above 45%
2. **[HIGH] Connect `invoice_audit` report type in Celery** — offload `build()` to a task for large datasets
3. **[MEDIUM] Fix WeasyPrint PDF silent fallback** — return structured error so clients know PDF failed
4. **[LOW] Migrate legacy invoice audit page** — redirect `/reports/invoice-audit/?report_id=<id>` to `/api/v1/reports/invoice-audit/<id>/html/` if `Report.report_type == "invoice_audit"`

---

## 9. Data Flow — Invoice Audit Report (v2)

```
Dashboard POST /api/v1/reports/invoice-audit/
  → InvoiceAuditReportGenerateView
    → InvoiceAuditReportService.build(date_from, date_to, language)
      → 3 bulk queries:
          Invoice.objects.filter(org).select_related("validation")
          + dict(InvoiceValidationResult by invoice_id)
          + dict(VendorProfile by vendor_name)
      → 10 sections assembled:
          report_header, summary, executive_summary, compliance_engine,
          high_risk_invoices, failed_rules_analysis, supplier_analysis,
          risk_analysis, anomalies, actions_and_recommendations
    → Report.objects.create(report_type="invoice_audit", data=<dict>)
  → 201 Created + full JSON
  → Dashboard redirects to /api/v1/reports/invoice-audit/<id>/html/
    → InvoiceAuditReportHTMLView
      → _build_template_context(report.data)
      → render invoice_audit_report_v2.html
      → 200 text/html
```
