# Tadgeeg API Documentation Index

## 📚 Documentation Files

This comprehensive API reference includes 4 detailed documents:

### 1. **API_QUICK_REFERENCE.md** (START HERE)
- **Purpose:** Quick lookup and examples
- **Length:** ~400 lines
- **Content:**
  - Quick start examples
  - Endpoint summary tables
  - Common query patterns
  - Permissions matrix
  - HTTP status codes
  - Common tasks & troubleshooting

### 2. **API_ENDPOINTS_REFERENCE.md** (COMPREHENSIVE)
- **Purpose:** Complete endpoint specifications
- **Length:** ~1500 lines
- **Content:**
  - Full endpoint definitions with all parameters
  - Request/response examples for every endpoint
  - Query parameters and filters
  - Error handling per endpoint
  - Serializer specifications
  - URL patterns
  - Authentication details

### 3. **API_MODELS_SERIALIZERS.md** (STRUCTURE)
- **Purpose:** Data model and schema reference
- **Length:** ~800 lines
- **Content:**
  - Invoice model structure
  - Audit case model structure
  - Document model structure
  - All serializers with field mappings
  - 30 validation rules grouped
  - Pagination and filtering backends

### 4. **API_ERROR_HANDLING_PATTERNS.md** (IMPLEMENTATION)
- **Purpose:** Error patterns and implementation guide
- **Length:** ~700 lines
- **Content:**
  - Error codes (400, 403, 404, 409, 422, 5xx)
  - Soft-delete implementation pattern
  - Validation rule engine
  - Risk scoring model
  - Implementation patterns with code
  - Common error scenarios & solutions

---

## 🏗️ API Architecture Overview

### Core Resources

```
INVOICES (11 endpoints)
├── Invoice (model)
│   ├── InvoiceValidationResult (1:1)
│   ├── InvoiceAuditEvent (1:many) — Audit trail
│   ├── InvoiceAuditFinding (1:many) — Findings
│   └── InvoiceBatch (many:1) — Parent batch
├── InvoiceBatch (2 endpoints)
├── VendorProfile (computed)
└── Reports (4 endpoints)
    ├── Risk Report
    ├── Duplicate Report
    ├── Vendor Risk
    └── Spend Analysis

AUDIT (11 endpoints)
├── AuditCase
│   ├── CaseComment (1:many)
│   ├── CustomRuleDefinition (1:many)
│   └── assignments (many:1 User)
├── AuditSession
│   ├── AuditFinding (1:many)
│   └── invoice_batches (1:many)
├── Dashboard
└── Big Four Compliance

DOCUMENTS (15+ endpoints)
├── Document
│   ├── ExtractedData (1:1)
│   ├── DocumentAnalysisResult (1:1)
│   ├── DocumentPageResult (1:many)
│   └── DocumentUploadSerializer
├── PurchaseOrder (typed model)
├── BankStatement (typed model)
├── PayrollSheet (typed model)
├── ExpenseReport (typed model)
├── VATReturn (typed model)
├── FixedAsset (typed model)
└── SalesReceipt (typed model)

REPORTS (10+ endpoints)
├── InvoiceAuditReport
├── DocumentReport
├── ExecutiveReport
└── Sub-endpoints
    ├── HighRiskInvoices
    ├── FailedRules
    ├── SupplierAnalysis
    └── ComplianceEngine
```

---

## 📊 HTTP Method Summary

| Method | Purpose | Examples | Status Codes |
|--------|---------|----------|--------------|
| **GET** | Read resource | /invoices/, /invoices/{id}/ | 200, 404 |
| **POST** | Create resource | /invoices/upload/, /audit/cases/ | 201, 202, 400 |
| **PATCH** | Update fields | /invoices/{id}/, /audit/cases/{id}/status/ | 200, 400, 409 |
| **DELETE** | Delete (soft) | /invoices/{id}/ | 204, 404 |

---

## 🔑 Authentication & Permissions

### Authentication Methods
```
JWT Bearer Token     → Authorization: Bearer <token>
Session Auth         → Cookie: sessionid=...
```

### Permission Classes
```
IsAuthenticated           → Must be logged in
IsOwnOrganization        → Must belong to org
IsSeniorAuditorOrAbove   → Role >= Senior Auditor
RequiresOrganization     → Must have org assigned
```

### Role-Based Access Control

| Role | Can Approve | Can Create Rules | Can Bulk Update | Notes |
|------|-------------|------------------|-----------------|-------|
| Auditor | ❌ | ❌ | ❌ | View-only |
| Senior Auditor | ✅ | ⚠️ | ✅ | Approval authority |
| Org Admin | ✅ | ✅ | ✅ | Full control |
| Platform Admin | ✅ | ✅ | ✅ | All orgs |

---

## 📈 Invoice Processing Pipeline

```
User Upload
    ↓
[InvoiceUploadView]
    ↓
File Processing
├── MIME Detection
├── PDF/Image Parser
├── OCR (Tesseract)
└── AI Extraction (GPT-4o)
    ↓
[_process_single_file]
    ↓
Normalization
├── Field extraction
├── Currency conversion
├── Date parsing
└── Amount rounding
    ↓
Validation
├── 30 Rules Engine (6 groups)
├── Each rule: PASS/FAIL
└── Scoring: (passed/total) × 100
    ↓
Risk Assessment
├── Validation risk
├── AI fraud score
├── Anomaly detection
└── Vendor history
    ↓
Status Assignment
├── Low risk → VALIDATED
├── Medium risk → FLAGGED (review)
├── High risk → FLAGGED (block)
└── Duplicate → FLAGGED (investigate)
    ↓
Persist to DB
├── Invoice record
├── ValidationResult
├── AuditEvent (upload log)
├── AuditFinding (issues)
└── Optional: CanonicalData
    ↓
Response
├── Summary: {invoice_id, score, risk, status}
├── Findings: [failed rules]
└── Recommendations: [actions]
```

---

## 🎯 Key Endpoints by Use Case

### Use Case: Batch Invoice Upload & Review

**Steps:**
1. Upload files
2. Monitor batch progress
3. Filter by risk level
4. Manual corrections (optional)
5. Approve/reject

**Endpoints:**
```
POST   /invoices/upload/
GET    /invoices/batches/{id}/
GET    /invoices/?batch_id=...&risk_level=high
POST   /invoices/{id}/review/
POST   /invoices/{id}/approve/
```

### Use Case: Audit Case Management

**Steps:**
1. Create case
2. Assign auditor
3. Add comments
4. Resolve
5. Bulk update status

**Endpoints:**
```
POST   /audit/cases/
POST   /audit/cases/{id}/assign/
POST   /audit/cases/{id}/comments/
PATCH  /audit/cases/{id}/status/
POST   /audit/cases/bulk/
```

### Use Case: Document Processing

**Steps:**
1. Upload document
2. Trigger analysis (async)
3. Poll for results
4. Download typed data
5. Generate report

**Endpoints:**
```
POST   /documents/upload/
POST   /documents/{id}/analyse/
GET    /documents/{id}/analysis/
GET    /documents/purchase-orders/
POST   /reports/document/
```

### Use Case: Executive Reporting

**Steps:**
1. Generate report
2. View/download
3. Email to stakeholders

**Endpoints:**
```
POST   /reports/executive/
GET    /reports/executive/latest/
GET    /reports/executive/{id}/pdf/
```

---

## 🔴 Error Response Format

### Standard Error Response
```json
{
  "error": "User-facing error message",
  "detail": "Additional detail (optional)",
  "fields": {
    "field_name": ["Field-specific error message"]
  }
}
```

### HTTP Status Code to Check

| Status | Endpoint Issue | Fix |
|--------|--------|------|
| 200 | ✓ OK | No action |
| 201 | ✓ Created | No action |
| 400 | Invalid request body | Check JSON format, date format (YYYY-MM-DD) |
| 403 | Permissions | Check IsAuthenticated, IsSeniorAuditorOrAbove |
| 404 | Not found | Invoice may be soft-deleted, verify ID |
| 409 | Conflict | Document already processing, wait 1 minute |
| 422 | Validation failure | Check invoice must not be APPROVED, amount format |

---

## 📋 Validation Rules (30 Total)

### Quick Rule Reference

**INV (5 rules):** Header validation
- INV-001: Invoice number unique
- INV-002: Date not in future
- INV-003: Due date >= invoice date
- INV-004: Vendor name present
- INV-005: Total amount > 0

**DUP (4 rules):** Duplicate detection
- DUP-001: Not duplicate (30-day window)
- DUP-002: Amount consistent with vendor history
- DUP-003: Invoice number not previously seen
- DUP-004: File hash unique

**VAT (4 rules):** ZATCA compliance
- VAT-001: VAT calculation correct
- VAT-002: Rate is 0%, 5%, or 15%
- VAT-003: Total = subtotal + VAT
- VAT-004: Currency = organization default

**ANO (4 rules):** Anomaly detection
- ANO-001: Amount within vendor range (mean ± 3σ)
- ANO-002: Frequency normal (< 10/day)
- ANO-003: Invoice recent (< 6 months old)
- ANO-004: Vendor in master data

**CTL (3 rules):** Financial controls
- CTL-001: All mandatory fields present
- CTL-002: Currency supported
- CTL-003: Not already approved

**DOC (6 rules):** Document quality
- DOC-001: Clear & readable (OCR > 60%)
- DOC-002: No alterations detected
- DOC-003: QR code valid (if present)
- DOC-004: File format supported
- DOC-005: File size ≤ 50 MB
- DOC-006: Language detected correctly

---

## 🔄 Soft-Delete Pattern

**Applies To:**
- Invoice
- AuditCase
- AuditSession
- Document

**Behavior:**
```
DELETE /invoices/{id}/
  ↓
invoice.is_deleted = True
invoice.deleted_at = now()
invoice.deleted_by = <user>
  ↓
AuditEvent created (DELETED)
  ↓
GET /invoices/{id}/ → 404 (soft-deleted not shown)
GET /invoices/ → Excluded from list
```

**Advantage:** GDPR Article 17 compliance, audit trail preservation, data recovery capability

---

## 📲 Response Pagination

### Pagination Format
```json
{
  "count": 500,
  "next": "https://api.tadgeeg.com/...?page=3",
  "previous": "https://api.tadgeeg.com/...?page=1",
  "results": [...]
}
```

### Pagination Query Parameters
```
?limit=50      # Page size (default: 20)
?offset=100    # Skip first N items
?page=2        # Page number (alternative)
```

---

## 🚀 Rate Limiting

**Status:** Not implemented (FR-6)  
**Future:** Plan for per-user/per-org limits based on load

---

## 🔗 Related Files in Repository

| File | Purpose |
|------|---------|
| `apps/invoices/views.py` | Invoice views (11 endpoints) |
| `apps/invoices/serializers.py` | Invoice serializers |
| `apps/invoices/models.py` | Invoice models |
| `apps/invoices/urls.py` | Invoice URL routing |
| `apps/audit/views.py` | Audit views (11 endpoints) |
| `apps/audit/models.py` | Audit models |
| `apps/audit/urls.py` | Audit URL routing |
| `apps/documents/views.py` | Document views |
| `apps/documents/typed_views.py` | Typed doc views |
| `apps/documents/models.py` | Document models |
| `apps/documents/urls.py` | Doc URL routing |
| `apps/reports/views.py` | Report views |
| `apps/reports/urls.py` | Report URL routing |
| `core/services/invoice_validator.py` | 30 validation rules |
| `core/services/financial_ai_engine.py` | AI analysis |
| `core/services/risk_engine.py` | Risk scoring |
| `core/services/canonical_mapper.py` | Canonical data |

---

## 📊 Statistics

| Category | Count |
|----------|-------|
| **Total Endpoints** | 60+ |
| **Invoices** | 11 |
| **Invoice Reports** | 5 |
| **Audit Cases** | 7 |
| **Audit Sessions** | 4 |
| **Custom Rules** | 4 |
| **Documents** | 15+ |
| **Reports** | 10+ |
| **Validation Rules** | 30 |
| **Error Codes** | 7 |
| **Serializers** | 20+ |
| **Models** | 15+ |

---

## 🎓 Learning Path

### Beginner
1. Read **API_QUICK_REFERENCE.md** (10 min)
2. Run basic POST /invoices/upload/ (5 min)
3. Run GET /invoices/ with filters (5 min)

### Intermediate
1. Read relevant sections of **API_ENDPOINTS_REFERENCE.md** (30 min)
2. Implement manual review flow (POST /invoices/{id}/review/) (15 min)
3. Try batch operations (/audit/cases/bulk/) (10 min)

### Advanced
1. Read **API_MODELS_SERIALIZERS.md** (30 min)
2. Understand 30 validation rules deeply (30 min)
3. Study **API_ERROR_HANDLING_PATTERNS.md** (30 min)
4. Implement custom rule (/audit/rules/) (30 min)

---

## 🔗 Quick Links

### Documentation
- Postman Collection: `Tadgeeg_API.postman_collection.json`
- OpenAPI Spec: `https://api.tadgeeg.com/api/schema/`
- Swagger UI: `https://api.tadgeeg.com/api/docs/`

### Testing
- Fixtures: `/tests/fixtures/`
- Integration tests: `/tests/api/`
- Sample data: `create_demo_user.py`

### Tools
- Django Admin: `https://tadgeeg.com/admin/`
- API Explorer: `https://api.tadgeeg.com/api/`
- Logs: `/logs/` directory

---

## 📞 Support & Escalation

| Issue Type | Team | Channel | SLA |
|------------|------|---------|-----|
| API Bug | Development | #api-support | 4 hours |
| Feature Request | Product | #feature-requests | 1 week |
| Deployment | DevOps | #deployments | 2 hours |
| Emergency | On-Call | PagerDuty | 15 min |

---

## 🔴 Status & Versions

| Component | Version | Status | Last Update |
|-----------|---------|--------|------------|
| API | 2.0 | ✅ Production | Mar 25, 2026 |
| Validation Engine | 30 rules | ✅ Production | Jan 15, 2026 |
| Risk Engine | 1.0 | ✅ Production | Feb 20, 2026 |
| OCR/AI | 1.2 | ✅ Production | Mar 1, 2026 |

---

## 📝 Change Log

### Version 2.0 (Mar 25, 2026)
- ✅ 60+ endpoints
- ✅ Soft-delete pattern (GDPR)
- ✅ 30 validation rules
- ✅ Risk scoring model
- ✅ Bulk case operations
- ✅ Custom rules (FR-9)
- ✅ Big Four compliance mapping

### Version 1.9 (Mar 1, 2026)
- ✅ Document typed models (7 types)
- ✅ Executive reporting
- ✅ Audit session tracking

### Version 1.0 (Jan 1, 2026)
- Initial release
- Basic invoice CRUD
- Batch upload
- Simple rules engine

---

## 📚 Appendix: File Organization

```
API Documentation Files (Main Directory)
├── API_QUICK_REFERENCE.md ←― START HERE
├── API_ENDPOINTS_REFERENCE.md ←― Full specs
├── API_MODELS_SERIALIZERS.md ←― Data schemas
├── API_ERROR_HANDLING_PATTERNS.md ←― Implementation
└── API_INDEX.md (this file) ←― Navigation

Source Code
├── apps/
│   ├── invoices/
│   │   ├── views.py (11 view classes)
│   │   ├── serializers.py (InvoiceListSerializer, etc.)
│   │   ├── models.py (Invoice, Batch, AuditEvent)
│   │   └── urls.py
│   ├── audit/
│   │   ├── views.py (11 view classes)
│   │   ├── serializers.py
│   │   ├── models.py (AuditCase, Session, Finding)
│   │   └── urls.py
│   ├── documents/
│   │   ├── views.py (DocumentListView, etc.)
│   │   ├── typed_views.py (PO, Bank, Payroll, etc.)
│   │   ├── models.py
│   │   └── urls.py
│   └── reports/
│       ├── views.py
│       └── urls.py
├── core/
│   ├── services/
│   │   ├── invoice_validator.py (30 rules)
│   │   ├── financial_ai_engine.py
│   │   ├── risk_engine.py
│   │   └── canonical_mapper.py
│   └── utils/
│       └── audit.py
└── tests/
    ├── api/
    ├── fixtures/
    └── integration/
```

---

**Version:** 2.0  
**Last Updated:** March 25, 2026  
**Maintained By:** Development Team  
**Next Review:** June 25, 2026

