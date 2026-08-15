# Tadgeeg API Quick Reference Guide

## 📋 Overview

**API Base URL:** `/api/v1/`  
**Version:** 2.0 (Production)  
**Default Response Format:** JSON  
**Rate Limiting:** None implemented (FR-6)

---

## 🚀 Quick Start

### Authentication
```bash
# Get JWT Token
curl -X POST /api/auth/token/ \
  -H "Content-Type: application/json" \
  -d '{"username": "user", "password": "pass"}'

# Use token in all requests
curl -H "Authorization: Bearer <token>" \
  https://api.tadgeeg.com/api/v1/invoices/
```

### Upload Invoices (Most Common)
```bash
curl -X POST /api/v1/invoices/upload/ \
  -H "Authorization: Bearer <token>" \
  -F "files=@invoice1.pdf" \
  -F "files=@invoice2.jpg" \
  -F "batch_name=Feb 2026"
```

### List Invoices with Filters
```bash
curl -X GET "/api/v1/invoices/?status=approved&risk_level=low&search=ACME" \
  -H "Authorization: Bearer <token>"
```

### Get Invoice Detail
```bash
curl -X GET /api/v1/invoices/{id}/ \
  -H "Authorization: Bearer <token>"
```

### Approve Invoice
```bash
curl -X POST /api/v1/invoices/{id}/approve/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"action": "approve"}'
```

---

## 📊 API Endpoints Summary

### Invoices (11 endpoints)
| Method | Endpoint | Purpose | Status |
|--------|----------|---------|--------|
| **POST** | `/invoices/upload/` | Upload files | 201 |
| **GET** | `/invoices/` | List (with filters) | 200 |
| **GET** | `/invoices/{id}/` | Get detail | 200 |
| **PATCH** | `/invoices/{id}/` | Update fields | 200 |
| **DELETE** | `/invoices/{id}/` | Soft-delete | 204 |
| **GET** | `/invoices/{id}/download/` | Download file | 200 |
| **POST** | `/invoices/{id}/review/` | Manual corrections | 200 |
| **POST** | `/invoices/{id}/approve/` | Approve/reject | 200 |
| **POST** | `/invoices/{id}/revalidate/` | Re-run rules | 200 |
| **GET** | `/invoices/batches/` | List batches | 200 |
| **GET** | `/invoices/batches/{id}/` | Batch detail | 200 |

### Invoices Reports (4 endpoints)
| Method | Endpoint | Purpose | Status |
|--------|----------|---------|--------|
| **GET** | `/invoices/reports/risk/` | High-risk invoices | 200 |
| **GET** | `/invoices/reports/duplicates/` | Duplicate report | 200 |
| **GET** | `/invoices/reports/vendors/` | Vendor risk | 200 |
| **GET** | `/invoices/reports/spend/` | Spend analysis | 200 |
| **GET** | `/invoices/rules/` | All 30 rules | 200 |

### Audit Cases (7 endpoints)
| Method | Endpoint | Purpose | Status |
|--------|----------|---------|--------|
| **GET** | `/audit/cases/` | List cases | 200 |
| **POST** | `/audit/cases/` | Create case | 201 |
| **GET** | `/audit/cases/{id}/` | Get detail | 200 |
| **PATCH** | `/audit/cases/{id}/` | Update case | 200 |
| **POST** | `/audit/cases/bulk/` | Bulk actions | 200 |
| **PATCH** | `/audit/cases/{id}/status/` | Change status | 200 |
| **POST** | `/audit/cases/{id}/assign/` | Assign to user | 200 |
| **GET/POST** | `/audit/cases/{id}/comments/` | Comments | 200/201 |

### Audit Sessions (4 endpoints)
| Method | Endpoint | Purpose | Status |
|--------|----------|---------|--------|
| **GET** | `/audit/sessions/{id}/` | Session detail | 200 |
| **GET** | `/audit/sessions/{id}/progress/` | Progress status | 200 |
| **GET** | `/audit/sessions/{id}/findings/` | Findings list | 200 |
| **GET** | `/audit/dashboard/overview/` | Dashboard | 200 |
| **GET** | `/audit/big-four/` | Compliance compliance | 200 |

### Custom Rules (4 endpoints)
| Method | Endpoint | Purpose | Status |
|--------|----------|---------|--------|
| **GET** | `/audit/rules/` | List rules | 200 |
| **POST** | `/audit/rules/` | Create rule | 201 |
| **GET** | `/audit/rules/{id}/` | Get rule | 200 |
| **PATCH** | `/audit/rules/{id}/` | Update rule | 200 |
| **DELETE** | `/audit/rules/{id}/` | Delete rule | 204 |
| **POST** | `/audit/rules/{id}/test/` | Test rule | 200 |

### Documents (15+ endpoints)
| Method | Endpoint | Purpose | Status |
|--------|----------|---------|--------|
| **POST** | `/documents/upload/` | Upload doc | 201 |
| **GET** | `/documents/` | List docs | 200 |
| **GET** | `/documents/{id}/` | Get detail | 200 |
| **DELETE** | `/documents/{id}/` | Delete | 204 |
| **POST** | `/documents/{id}/analyse/` | Async analysis | 202 |
| **GET** | `/documents/{id}/analysis/` | Get results | 200 |
| **GET** | `/documents/stats/` | Stats | 200 |
| **GET** | `/documents/purchase-orders/` | PO list | 200 |
| **GET** | `/documents/bank-statements/` | Bank stmt list | 200 |
| **GET** | `/documents/payroll/` | Payroll list | 200 |
| **GET** | `/documents/expense-reports/` | Expenses list | 200 |
| **GET** | `/documents/vat-returns/` | VAT list | 200 |
| **GET** | `/documents/fixed-assets/` | Assets list | 200 |
| **GET** | `/documents/sales-receipts/` | Receipts list | 200 |

### Reports (10+ endpoints)
| Method | Endpoint | Purpose | Status |
|--------|----------|---------|--------|
| **POST** | `/reports/invoice-audit/` | Gen audit report | 201 |
| **GET** | `/reports/invoice-audit/{id}/` | Get report | 200 |
| **GET** | `/reports/invoice-audit/{id}/pdf/` | Download PDF | 200 |
| **GET** | `/reports/invoice-audit/{id}/html/` | View HTML | 200 |
| **GET** | `/reports/invoice-audit/{id}/high-risk/` | High-risk INVs | 200 |
| **GET** | `/reports/invoice-audit/{id}/failed-rules/` | Failed rules | 200 |
| **GET** | `/reports/invoice-audit/{id}/supplier-analysis/` | Supplier risk | 200 |
| **GET** | `/reports/invoice-audit/{id}/compliance/` | Compliance | 200 |
| **POST** | `/reports/executive/` | Executive report | 201 |
| **GET** | `/reports/executive/latest/` | Latest exec report | 200 |

---

## 🔑 Key Concepts

### Invoice Status States
```
pending → processing → validated/flagged → approved/rejected
                                  ↑
                                 rejected
```

### Risk Levels
- **low** (0-40): Safe to approve
- **medium** (40-70): Review recommended
- **high** (70-85): Manual review required
- **critical** (85-100): Block and investigate

### Validation Groups (30 Total Rules)
| Group | Code | Rules | Focus |
|-------|------|-------|-------|
| Header | INV | 5 | Invoice basic info |
| Duplicates | DUP | 4 | Duplicate detection |
| VAT | VAT | 4 | ZATCA compliance |
| Anomalies | ANO | 4 | Unusual patterns |
| Controls | CTL | 3 | Financial controls |
| Document | DOC | 6 | File quality |

---

## 📝 Common Query Patterns

### Filter by Status & Risk
```
GET /invoices/?status=flagged&risk_level=high
```

### Search by Vendor (Full-Text)
```
GET /invoices/?search=ACME
```

### Date Range
```
GET /invoices/?date_from=2026-01-01&date_to=2026-02-28
```

### Amount Range
```
GET /invoices/?min_amount=1000&max_amount=50000
```

### Complex Filters (All)
```
GET /invoices/?status=approved&risk_level=low&vendor_name=ACME&date_from=2026-01-01&offset=100&limit=50
```

### Batch Operations
```
POST /audit/cases/bulk/
{
  "ids": ["uuid1", "uuid2"],
  "action": "resolve",
  "note": "Batch resolution"
}
```

---

## ✔️ Permissions Matrix

| Endpoint | Required | Notes |
|----------|----------|-------|
| POST /invoices/upload | IsAuthenticated | Any user |
| GET /invoices/ | IsAuthenticated | Own org only |
| PATCH /invoices/{id} | IsAuthenticated | Own org, not APPROVED |
| DELETE /invoices/{id} | IsAuthenticated | Soft-delete |
| POST /invoices/{id}/approve | IsAuthenticated, IsSeniorAuditorOrAbove | Senior Auditor+ |
| PATCH /invoices/{id}/review | IsAuthenticated, IsSeniorAuditorOrAbove | Senior Auditor+ |
| POST /audit/cases/bulk | IsAuthenticated, IsSeniorAuditorOrAbove | Senior Auditor+ |
| PATCH /audit/rules/{id} | IsAuthenticated, IsSeniorAuditorOrAbove | Senior Auditor+ |
| POST /documents/upload | IsAuthenticated, RequiresOrganization | Org member |

---

## 🔴 HTTP Status Codes

| Code | Meaning | Fix |
|------|---------|-----|
| **200** | Success | ✓ Working as expected |
| **201** | Created | ✓ Resource created |
| **202** | Accepted | ⏳ Async task queued, poll for status |
| **204** | No Content | ✓ Deleted successfully |
| **400** | Bad Request | ❌ Check request format/validation |
| **401** | Unauthorized | ❌ Missing/invalid auth token |
| **403** | Forbidden | ❌ Missing permission (Senior Auditor?) |
| **404** | Not Found | ❌ Resource doesn't exist or deleted |
| **409** | Conflict | ❌ State conflict (already processing) |
| **422** | Unprocessable | ❌ Validation error (business logic) |
| **500** | Server Error | 📞 Contact support with request ID |

---

## 🔒 Authentication Methods

### JWT (Bearer Token)
```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### Session (Browser)
```
Cookie: sessionid=abc123...
```

### Scope: Multi-Tenant
- All queries filtered by `request.user.organization`
- Soft-deleted records hidden (is_deleted=False)
- User can only access their organization's data

---

## 📦 Soft-Delete Pattern

**Models:** Invoice, AuditCase, AuditSession, Document

**Fields:**
- `is_deleted: bool` - Logical delete flag
- `deleted_at: datetime` - When deleted
- `deleted_by: User` - Who deleted it

**Behavior:**
- DELETE request → Sets is_deleted=True (no permanent loss)
- Audit trail entry created
- GET returns 404 (soft-deleted not shown)
- Data preserved in database (GDPR Article 17)

**Example:**
```bash
DELETE /api/v1/invoices/{id}/
# Response: 204 No Content
# Database: is_deleted=True, deleted_by=Ahmed, deleted_at=now()
```

---

## 🔄 Async Operations Pattern

**Endpoints:** Document analysis, report generation

**Flow:**
```
POST /documents/{id}/analyse/    → 202 Accepted
       ↓
       Async task queued
       ↓
GET /documents/{id}/analysis/    → 200 OK (if ready)
                                 → 202 (if processing)
                                 → 500 (if failed)
```

**Polling Strategy:**
```bash
# 1. Submit async request
curl -X POST /api/v1/documents/{id}/analyse/ \
  -H "Authorization: Bearer <token>" \
  -d '{"sync": false}'
# Response: 202 Accepted

# 2. Poll for status (every 2 seconds)
curl -X GET /api/v1/documents/{id}/analysis/ \
  -H "Authorization: Bearer <token>"
# Response: 200 OK with results (when ready)
```

---

## 📊 Invoice Processing Pipeline

```
1. Upload File
   ↓
2. MIME Detection → Route to parser (PDF/Image/Excel/JSON)
   ↓
3. OCR/Text Extraction → Tesseract + OpenAI upgrade
   ↓
4. AI Field Extraction → GPT-4o ZATCA extraction
   ↓
5. Normalization → Canonical format (amounts, dates, currency)
   ↓
6. Financial AI Analysis → Classification, fraud, duplicate, risk
   ↓
7. Run 30 Validation Rules → 6 groups (INV, DUP, VAT, ANO, CTL, DOC)
   ↓
8. Audit Engine → Modular rules (R001-R006)
   ↓
9. Risk Assessment → Merge validation + AI scores
   ↓
10. Persist to DB → Invoice + Validation + Audit Trail
   ↓
11. Response → Results + Findings + Recommendations
```

---

## 🎯 Common Tasks

### Upload & Approve Batch
```bash
# 1. Upload
curl -X POST /api/v1/invoices/upload/ \
  -H "Authorization: Bearer <token>" \
  -F "files=@*.pdf" \
  -F "batch_name=Feb 2026"

# 2. Get batch ID from response
batch_id="..."

# 3. List invoices in batch
curl -X GET "/api/v1/invoices/?batch_id=$batch_id" \
  -H "Authorization: Bearer <token>"

# 4. Review flagged invoices
curl -X GET "/api/v1/invoices/?batch_id=$batch_id&risk_level=high" \
  -H "Authorization: Bearer <token>"

# 5. Approve specific invoice
curl -X POST "/api/v1/invoices/{id}/approve/" \
  -H "Authorization: Bearer <token>" \
  -d '{"action": "approve"}'
```

### Manual Field Correction
```bash
curl -X POST /api/v1/invoices/{id}/review/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "corrections": {
      "vendor_name": "Corrected Name",
      "total_amount": "5100.00",
      "invoice_date": "2026-01-20"
    },
    "note": "Fixed vendor name spelling",
    "revalidate": true
  }'
```

### Create & Assign Audit Case
```bash
# 1. Create case
curl -X POST /api/v1/audit/cases/ \
  -H "Authorization: Bearer <token>" \
  -d '{
    "case_type": "duplicate",
    "priority": "high",
    "title": "Duplicate invoice",
    "assigned_to_id": "<user_uuid>"
  }'

# 2. Get case list
curl -X GET "/api/v1/audit/cases/?status=open&assigned_to=<user_uuid>" \
  -H "Authorization: Bearer <token>"

# 3. Update status
curl -X PATCH "/api/v1/audit/cases/{id}/status/" \
  -H "Authorization: Bearer <token>" \
  -d '{"status": "resolved", "resolution_notes": "..."}'
```

### Generate Executive Report
```bash
# 1. Generate
curl -X POST /api/v1/reports/executive/ \
  -H "Authorization: Bearer <token>" \
  -d '{"date_from": "2026-01-01", "date_to": "2026-02-28"}'

# 2. Download PDF
curl -X GET /api/v1/reports/executive/{id}/pdf/ \
  -H "Authorization: Bearer <token>" \
  -o report.pdf
```

---

## 🆘 Troubleshooting

| Issue | Solution |
|-------|----------|
| 401 Unauthorized | Missing/invalid Bearer token |
| 403 Forbidden | User role < Senior Auditor (for approval endpoints) |
| 404 Not Found | Resource soft-deleted or invalid ID |
| 409 Conflict | Document already processing (wait or retry) |
| 400 Bad Request | Invalid date format (use YYYY-MM-DD) or amount |
| 422 Unprocessable | Business logic validation failed (see error detail) |
| Invoice stuck in PROCESSING | Check logs for OCR/AI errors, revalidate |
| Duplicate not detected | May need manual review or vendor history update |

---

## 📚 Related Documentation

1. **API_ENDPOINTS_REFERENCE.md** - Complete endpoint specifications
2. **API_MODELS_SERIALIZERS.md** - Model schemas and response formats
3. **API_ERROR_HANDLING_PATTERNS.md** - Error codes and validation rules
4. **validation_rules_30.json** - All 30 rules with metadata

---

## 🔗 Test Credentials

**Demo User:**
- Username: `demo@tadgeeg.com`
- Password: `DemoPassword123!`
- Role: Senior Auditor
- Organization: Demo Org

**Test Invoice Files:** `/tests/fixtures/invoices/`

**Postman Collection:** `Tadgeeg_API.postman_collection.json`

---

## 📞 Support

- **API Issues:** Development Team
- **Business Logic:** Product Team
- **Infrastructure:** DevOps

**Slack Channels:**
- #api-support
- #bugs-and-issues
- #deployments

---

**Last Updated:** March 25, 2026  
**Version:** 2.0 (Production)  
**Next Review:** June 25, 2026

