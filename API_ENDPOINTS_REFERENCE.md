# Tadgeeg API Endpoints Reference
## Complete REST API Specification

**Date:** March 2026  
**Version:** 2.0  
**Status:** Production

---

## Table of Contents
1. [Invoice Management](#invoice-management)
2. [Audit Cases & Sessions](#audit-cases--sessions)
3. [Document Processing](#document-processing)
4. [Reports](#reports)
5. [Error Response Codes](#error-response-codes)
6. [Soft-Delete Pattern](#soft-delete-pattern)
7. [Authentication & Permissions](#authentication--permissions)
8. [Pagination & Filtering](#pagination--filtering)

---

## INVOICE MANAGEMENT

### Resource: Invoice

**Primary Model:** `Invoice`  
**Key Fields:** invoice_number, invoice_date, due_date, vendor_name, total_amount, risk_score, status

#### 1. Upload Invoices (POST)
```
POST /api/v1/invoices/upload/
```
**View Class:** `InvoiceUploadView` (APIView)

**Features:**
- Single file, multiple files, ZIP archive
- Supports: PDF, JPG, PNG, TIFF, ZIP, XLSX, XLS, JSON, CSV, TSV
- Runs 30 validation rules (Groups: INV, DUP, VAT, ANO, CTL, DOC)
- Full processing pipeline: OCR → AI Extraction → Risk Analysis → Audit Rules

**Request:**
```json
{
  "files": ["file1.pdf", "file2.jpg"],
  "batch_name": "Monthly Invoices - Feb 2026"
}
```

**Response:** 201 CREATED
```json
{
  "batch_id": "uuid",
  "audit_session_id": "uuid",
  "batch_name": "...",
  "total_files": 10,
  "processed": 9,
  "failed": 1,
  "status": "partial|completed|failed",
  "results": [
    {
      "invoice_id": "uuid",
      "filename": "...",
      "success": true,
      "validation_score": 92.5,
      "rules_failed": ["DUP-001"],
      "risk_level": "medium",
      "is_duplicate": false,
      "fraud_score": 0.15,
      "status": "validated|flagged|approved",
      "processing_ms": 2345
    }
  ],
  "errors": [{"filename": "...", "error": "..."}]
}
```

**Permissions:** `IsAuthenticated`  
**Parsers:** `MultiPartParser`, `FormParser`

---

#### 2. List Invoices (GET)
```
GET /api/v1/invoices/
```
**View Class:** `InvoiceListView` (generics.ListAPIView)

**Query Parameters:**
- `status` - Filter: pending, processing, validated, flagged, approved, rejected
- `risk_level` - Filter: low, medium, high, critical
- `vendor_name` - Partial match filter
- `is_duplicate` - Boolean filter
- `date_from`, `date_to` - Date range (YYYY-MM-DD)
- `min_amount`, `max_amount` - Amount range
- `search` - Full-text: vendor_name, invoice_number, notes, vat_number
- `batch_id` - Filter by batch

**Response:** 200 OK
```json
{
  "count": 150,
  "next": "...",
  "previous": "...",
  "results": [
    {
      "id": "uuid",
      "invoice_number": "INV-2026-001",
      "invoice_date": "2026-01-15",
      "vendor_name": "ACME Corp",
      "vendor_vat_number": "310123456700003",
      "total_amount": "5000.00",
      "vat_amount": "750.00",
      "currency": "SAR",
      "status": "approved",
      "risk_level": "low",
      "risk_score": 15.5,
      "is_duplicate": false,
      "ocr_confidence": 95.2,
      "language": "ar",
      "has_qr_code": true,
      "uploaded_by_name": "Ahmed Ali",
      "original_filename": "invoice_001.pdf",
      "created_at": "2026-01-15T10:30:00Z",
      "audit_session_id": "uuid"
    }
  ]
}
```

**Serializer:** `InvoiceListSerializer`  
**Permissions:** `IsAuthenticated`  
**Soft-Delete:** Excludes `is_deleted=True` records

---

#### 3. Get Invoice Detail (GET)
```
GET /api/v1/invoices/{id}/
```
**View Class:** `InvoiceDetailView` (generics.RetrieveUpdateAPIView + DestroyModelMixin)

**Response:** 200 OK
```json
{
  "id": "uuid",
  "invoice_number": "INV-2026-001",
  "invoice_date": "2026-01-15",
  "due_date": "2026-02-15",
  "vendor_name": "ACME Corp",
  "vendor_name_ar": "شركة أكمي",
  "vendor_vat_number": "310123456700003",
  "vendor_cr_number": "1010123456",
  "vendor_address": "...",
  "vendor_phone": "...",
  "customer_name": "...company...",
  "customer_vat_number": "...",
  "invoice_number": "INV-2026-001",
  "currency": "SAR",
  "subtotal": "4285.71",
  "vat_rate": 15.0,
  "vat_amount": "750.00",
  "discount": "0.00",
  "total_amount": "5000.00",
  "line_items": [
    {"description": "Service A", "qty": 1, "unit_price": "1000", "total": "1000"}
  ],
  "status": "approved",
  "risk_level": "low",
  "risk_score": 15.5,
  "is_duplicate": false,
  "duplicate_of_id": null,
  "is_handwritten": false,
  "is_clear": true,
  "has_alterations": false,
  "has_qr_code": true,
  "qr_code_valid": true,
  "qr_code_image": "base64|url",
  "qr_code_data": "{zatca_qr}",
  "language": "ar",
  "ocr_confidence": 95.2,
  "ai_summary": "Standard invoice, no red flags",
  "raw_text": "...",
  "extracted_data": {
    "file_hash": "...",
    "normalized": {...},
    "_extraction_method": "pdfplumber"
  },
  "ai_recommendations": ["Review vendor history"],
  "processing_error": null,
  "file": "/api/v1/invoices/{id}/download/",
  "original_filename": "invoice_001.pdf",
  "file_size": 245632,
  "mime_type": "application/pdf",
  "created_at": "2026-01-15T10:30:00Z",
  "updated_at": "2026-01-15T10:35:00Z",
  "uploaded_by": "uuid",
  "uploaded_by_name": "Ahmed Ali",
  "approved_by": null,
  "approved_by_name": null,
  "approved_at": null,
  "rejected_reason": null,
  "notes": "...",
  "deleted_at": null,
  "deleted_by": null,
  "is_deleted": false,
  "audit_session_id": "uuid",
  "batch_id": "uuid",
  "validation": {
    "validation_score": 92.5,
    "passed_rules": ["INV-001", "INV-002"],
    "failed_rule_codes": ["DUP-001"],
    "validation_details": {...}
  },
  "findings": [
    {
      "id": "uuid",
      "code": "DUP-001",
      "severity": "high",
      "description": "Duplicate invoice detected",
      "status": "open"
    }
  ],
  "audit_trail": [
    {
      "event_type": "uploaded",
      "description": "Uploaded: invoice_001.pdf",
      "timestamp": "2026-01-15T10:30:00Z",
      "user_full_name": "Ahmed Ali",
      "ip_address": "192.168.1.1"
    }
  ],
  "review": {
    "fields": [
      {
        "field": "vendor_name",
        "label": "Vendor Name",
        "type": "text",
        "current": "ACME Corp",
        "normalized": "ACME Corp",
        "ai": "ACME Corporation",
        "manual": null
      }
    ],
    "raw_text": "...",
    "normalized": {...},
    "ai_extracted": {...},
    "manual_review": {...},
    "last_review_event": null
  }
}
```

**HTTP Methods:**
- **GET:** Retrieve full invoice detail with validation, findings, audit trail
- **PATCH:** Update invoice fields (except computed fields like risk_score, status)
- **DELETE:** Soft-delete (GDPR Article 17)

**Serializer:** `InvoiceDetailSerializer`  
**Permissions:** `IsAuthenticated`, `IsOwnOrganization`  
**Authentication:** `JWTAuthentication`, `SessionAuthentication`

---

#### 4. Download Invoice (GET)
```
GET /api/v1/invoices/{id}/download/
```
**View Class:** `InvoiceDownloadView` (APIView)

**Response:** 200 OK (binary file)  
**Serializer:** N/A

---

#### 5. Manual Review & Correction (POST)
```
POST /api/v1/invoices/{id}/review/
```
**View Class:** `InvoiceManualReviewView` (APIView)

**Request:**
```json
{
  "corrections": {
    "vendor_name": "Corrected Vendor Name",
    "total_amount": "5100.00",
    "invoice_date": "2026-01-20"
  },
  "note": "Manual review: corrected vendor spelling",
  "revalidate": true
}
```

**Response:** 200 OK
```json
{
  "invoice_id": "uuid",
  "status": "validated|flagged",
  "applied_fields": {"vendor_name": "Corrected...", ...},
  "review": {...review_payload...},
  "validation": {...if_revalidate_true...}
}
```

**Error Codes:**
- `400` - Validation error (invalid date format, amount parsing)
- `404` - Invoice not found

**Permissions:** `IsAuthenticated`, `IsSeniorAuditorOrAbove`  
**Authentication:** `JWTAuthentication`, `SessionAuthentication`

---

#### 6. Approve/Reject Invoice (POST)
```
POST /api/v1/invoices/{id}/approve/
```
**View Class:** `InvoiceApproveView` (APIView)

**Request:**
```json
{
  "action": "approve",
  "reason": "Approved by controller"
}
```
or
```json
{
  "action": "reject",
  "reason": "Duplicate invoice detected"
}
```

**Response:** 200 OK
```json
{
  "invoice_id": "uuid",
  "status": "approved|rejected",
  "message": "Approved by Ahmed Ali"
}
```

**Error Codes:**
- `400` - Invalid action or missing reason (rejection)
- `403` - Not a senior auditor
- `404` - Invoice not found

**Permissions:** `IsAuthenticated`, `IsSeniorAuditorOrAbove`

---

#### 7. Revalidate Invoice (POST)
```
POST /api/v1/invoices/{id}/revalidate/
```
**View Class:** `InvoiceRevalidateView` (APIView)

**Response:** 200 OK
```json
{
  "validation_score": 92.5,
  "passed_rules": ["INV-001"],
  "failed_rule_codes": ["DUP-001"],
  "validation_details": {...},
  "findings_summary": {...}
}
```

**Permissions:** `IsAuthenticated`

---

### Resource: InvoiceBatch

#### 8. List Batches (GET)
```
GET /api/v1/invoices/batches/
```
**View Class:** `InvoiceBatchListView` (generics.ListAPIView)

**Response:** 200 OK
```json
{
  "results": [
    {
      "id": "uuid",
      "batch_name": "Monthly Invoices - Feb 2026",
      "status": "completed|partial|failed",
      "total_files": 100,
      "processed_files": 98,
      "failed_files": 2,
      "uploaded_by_name": "Ahmed Ali",
      "created_at": "2026-02-01T09:00:00Z",
      "completed_at": "2026-02-01T09:45:00Z",
      "audit_session_id": "uuid",
      "audit_session_status": "completed"
    }
  ]
}
```

**Serializer:** `InvoiceBatchSerializer`  
**Permissions:** `IsAuthenticated`

---

#### 9. Get Batch Detail (GET)
```
GET /api/v1/invoices/batches/{id}/
```
**View Class:** `InvoiceBatchDetailView` (APIView)

**Response:** 200 OK
```json
{
  "batch": {
    "id": "uuid",
    "batch_name": "...",
    "status": "completed",
    "total_files": 100,
    "processed_files": 98,
    "failed_files": 2,
    "created_at": "2026-02-01T09:00:00Z",
    "completed_at": "2026-02-01T09:45:00Z"
  },
  "audit_session_id": "uuid",
  "stats": {
    "total_amount": "500000.00",
    "avg_score": 88.5,
    "flagged": 12,
    "approved": 80,
    "duplicates": 3,
    "critical": 2
  },
  "invoices": [
    {
      "id": "uuid",
      "original_filename": "invoice_001.pdf",
      "vendor_name": "ACME Corp",
      "invoice_number": "INV-2026-001",
      "total_amount": "5000.00",
      "currency": "SAR",
      "invoice_date": "2026-01-15",
      "status": "approved",
      "risk_level": "low",
      "risk_score": 15.5,
      "is_duplicate": false,
      "ocr_confidence": 95.2
    }
  ]
}
```

---

### Reports: Invoice-Related

#### 10. Risk Report (GET)
```
GET /api/v1/invoices/reports/risk/
```
**View Class:** `InvoiceRiskReportView` (APIView)

**Query Parameters:**
- `date_from`, `date_to` - Date range
- `risk_level` - low, medium, high, critical (default: high, critical)

**Response:** 200 OK
```json
{
  "report_type": "risk_report",
  "generated_at": "2026-02-20T14:30:00Z",
  "stats": {
    "count": 45,
    "total": "225000.00",
    "avg_risk": 72.5
  },
  "invoices": [
    {
      "id": "uuid",
      "invoice_number": "...",
      "vendor_name": "...",
      "total_amount": "...",
      "currency": "SAR",
      "invoice_date": "...",
      "risk_level": "high",
      "risk_score": 78.5,
      "ai_summary": "...",
      "is_duplicate": false,
      "status": "flagged",
      "ai_recommendations": [...]
    }
  ]
}
```

**Permissions:** `IsAuthenticated`

---

#### 11. Duplicate Report (GET)
```
GET /api/v1/invoices/reports/duplicates/
```
**View Class:** `DuplicateInvoiceReportView` (APIView)

**Response:** 200 OK - Same structure as above

---

#### 12. Vendor Risk Report (GET)
```
GET /api/v1/invoices/reports/vendors/
```
**View Class:** `VendorRiskReportView` (APIView)

**Response:** 200 OK
```json
{
  "report_type": "vendor_risk_report",
  "generated_at": "2026-02-20T14:30:00Z",
  "vendors": [
    {
      "vendor_name": "ACME Corp",
      "vendor_vat_number": "310123456700003",
      "invoice_count": 45,
      "total_amount": "225000.00",
      "avg_invoice_amount": "5000.00",
      "max_invoice_amount": "25000.00",
      "flagged_count": 3,
      "duplicate_count": 2,
      "is_new": false,
      "first_seen": "2025-01-15",
      "last_seen": "2026-02-20"
    }
  ]
}
```

---

#### 13. Spend Analysis Report (GET)
```
GET /api/v1/invoices/reports/spend/
```
**View Class:** `SpendAnalysisReportView` (APIView)

**Query Parameters:**
- `date_from`, `date_to`

**Response:** 200 OK
```json
{
  "report_type": "spend_analysis",
  "generated_at": "2026-02-20T14:30:00Z",
  "overall": {
    "grand_total": "2500000.00",
    "total_vat": "375000.00",
    "total_invoices": 500,
    "avg_invoice": "5000.00",
    "flagged_total": "150000.00"
  },
  "by_vendor": [
    {
      "vendor_name": "ACME Corp",
      "total": "225000.00",
      "count": 45,
      "avg": "5000.00",
      "flagged": 3
    }
  ],
  "by_currency": [{"currency": "SAR", "total": "2500000.00", "count": 500}],
  "monthly_trend": [
    {
      "month": "2026-01",
      "total_amount": "500000.00",
      "invoice_count": 100,
      "flagged_count": 25,
      "duplicate_count": 5
    }
  ]
}
```

---

#### 14. Validation Rules List (GET)
```
GET /api/v1/invoices/rules/
```
**View Class:** `ValidationRulesListView` (APIView)

**Response:** 200 OK
```json
{
  "total_rules": 30,
  "rule_groups": {
    "Group 1 — Invoice Validation": {
      "INV-001": "Invoice number is present and unique",
      "INV-002": "Invoice date is valid and not in future"
    },
    "Group 2 — Duplicate Detection": {
      "DUP-001": "Invoice not duplicate of recent invoices",
      "DUP-002": "Invoice amount consistent with vendor history"
    },
    "Group 3 — VAT Validation": {
      "VAT-001": "VAT calculation correct (rounded)",
      "VAT-002": "VAT rate compliant with ZATCA (0%, 5%, 15%)"
    },
    "Group 4 — Anomaly Detection": {
      "ANO-001": "Amount within vendor typical range",
      "ANO-002": "No suspicious patterns detected"
    },
    "Group 5 — Financial Controls": {
      "CTL-001": "All mandatory fields present",
      "CTL-002": "Currency matches organization default"
    },
    "Group 6 — Document Quality": {
      "DOC-001": "Document is clear and readable",
      "DOC-002": "No visible alterations detected"
    }
  }
}
```

---

## AUDIT CASES & SESSIONS

### Resource: AuditCase

#### 1. List Cases (GET)
```
GET /api/v1/audit/cases/
```
**View Class:** `AuditCaseListCreateView` (generics.ListCreateAPIView)

**Query Parameters:**
- `status` - open, in_progress, resolved, closed
- `priority` - low, medium, high, critical
- `case_type` - fraud, duplicate, compliance, data_quality, other
- `assigned_to` - UUID of assignee

**Response:** 200 OK
```json
{
  "count": 45,
  "results": [
    {
      "id": "uuid",
      "case_number": "CASE-2026-001",
      "case_type": "duplicate",
      "priority": "high",
      "status": "open",
      "severity": "high",
      "title": "Duplicate invoice detected",
      "description": "Invoice INV-2026-001 is duplicate",
      "assigned_to_id": "uuid",
      "assigned_to": "uuid",
      "assigned_to_name": "Ahmed Ali",
      "created_by": "uuid",
      "created_by_name": "System",
      "created_at": "2026-02-20T10:00:00Z",
      "resolved_at": null,
      "resolved_by": null,
      "resolution_notes": null,
      "is_deleted": false
    }
  ]
}
```

**Serializer:** `AuditCaseSerializer`  
**Permissions:** `IsAuthenticated`  
**Soft-Delete:** Excludes `is_deleted=True`

---

#### 2. Create Case (POST)
```
POST /api/v1/audit/cases/
```

**Request:**
```json
{
  "case_type": "duplicate",
  "priority": "high",
  "title": "...",
  "description": "...",
  "assigned_to_id": "uuid"
}
```

**Response:** 201 CREATED

---

#### 3. Get Case Detail (GET)
```
GET /api/v1/audit/cases/{id}/
```
**View Class:** `AuditCaseDetailView` (generics.RetrieveUpdateAPIView)

**Response:** 200 OK (same structure as list item with additional fields)

---

#### 4. Update Case Status (PATCH)
```
PATCH /api/v1/audit/cases/{id}/status/
```
**View Class:** `UpdateCaseStatusView` (APIView)

**Request:**
```json
{
  "status": "resolved",
  "resolution_notes": "Duplicate invoice deleted"
}
```

**Response:** 200 OK
```json
{
  "id": "uuid",
  "status": "resolved",
  "resolution_notes": "...",
  "resolved_at": "2026-02-20T14:30:00Z",
  "resolved_by": "uuid"
}
```

**Error Codes:**
- `400` - Invalid status value
- `404` - Case not found

**Permissions:** `IsAuthenticated`, `IsSeniorAuditorOrAbove`

---

#### 5. Bulk Case Actions (POST)
```
POST /api/v1/audit/cases/bulk/
```
**View Class:** `BulkCaseActionView` (APIView)

**Request:**
```json
{
  "ids": ["uuid1", "uuid2", "uuid3"],
  "action": "resolve|close|archive|assign",
  "note": "Bulk resolution",
  "assigned_to": "uuid"
}
```

**Response:** 200 OK
```json
{
  "updated": 3,
  "action": "resolve"
}
```

**Permissions:** `IsAuthenticated`, `IsSeniorAuditorOrAbove`

---

#### 6. Case Comments (GET/POST)
```
GET /api/v1/audit/cases/{id}/comments/
POST /api/v1/audit/cases/{id}/comments/
```
**View Class:** `CaseCommentView` (APIView)

**GET Response:**
```json
[
  {
    "id": "uuid",
    "case_id": "uuid",
    "author": "uuid",
    "author_name": "Ahmed Ali",
    "text": "Review this duplicate with accounting dept",
    "is_internal": false,
    "created_at": "2026-02-20T11:00:00Z"
  }
]
```

**POST Request:**
```json
{
  "text": "Comment text",
  "is_internal": false
}
```

**POST Response:** 201 CREATED

---

#### 7. Assign Case (POST)
```
POST /api/v1/audit/cases/{id}/assign/
```
**View Class:** `AssignCaseView` (APIView)

**Request:**
```json
{
  "user_id": "uuid"
}
```

**Response:** 200 OK
```json
{
  "id": "uuid",
  "assigned_to": "uuid",
  "assigned_to_id": "uuid",
  "assigned_to_name": "Ahmed Ali"
}
```

**Permissions:** `IsAuthenticated`, `IsSeniorAuditorOrAbove`

---

### Resource: AuditSession

#### 8. Session Detail (GET)
```
GET /api/v1/audit/sessions/{id}/
```
**View Class:** `AuditSessionDetailView` (APIView)

**Response:** 200 OK
```json
{
  "session": {
    "id": "uuid",
    "name": "Monthly Invoices - Feb 2026",
    "organization": "uuid",
    "created_by": "uuid",
    "created_at": "2026-02-01T09:00:00Z",
    "status": "completed",
    "total_count": 100,
    "processed_count": 100,
    "error_count": 2
  },
  "batch": {
    "id": "uuid",
    "batch_name": "...",
    "status": "completed"
  },
  "stats": {
    "total_amount": "500000.00",
    "avg_score": 88.5,
    "flagged": 12,
    "approved": 80,
    "duplicates": 3,
    "critical": 2
  },
  "summary": {
    "total_reviewed": 100,
    "compliant": 85,
    "flagged": 12,
    "critical": 3,
    "recommendations": "..."
  },
  "finding_totals": {
    "critical": 3,
    "high": 8,
    "medium": 15,
    "low": 20
  },
  "findings": [...20_findings...],
  "invoices": [...]
}
```

**Permissions:** `IsAuthenticated`

---

#### 9. Session Progress (GET)
```
GET /api/v1/audit/sessions/{id}/progress/
```
**View Class:** `AuditSessionProgressView` (APIView)

**Response:** 200 OK
```json
{
  "id": "uuid",
  "status": "completed",
  "total_count": 100,
  "processed_count": 100,
  "error_count": 2,
  "ready_for_summary": true
}
```

---

#### 10. Session Findings (GET)
```
GET /api/v1/audit/sessions/{id}/findings/
```
**View Class:** `AuditSessionFindingsView` (APIView)

**Query Parameters:**
- `severity` - critical, high, medium, low
- `status` - open, resolved, dismissed

**Response:** 200 OK
```json
{
  "count": 46,
  "results": [
    {
      "id": "uuid",
      "code": "DUP-001",
      "invoice_id": "uuid",
      "invoice_number": "INV-2026-001",
      "severity": "high",
      "status": "open",
      "description": "Duplicate detected",
      "first_detected_at": "2026-02-01T09:30:00Z",
      "last_detected_at": "2026-02-01T09:30:00Z",
      "resolution": null
    }
  ]
}
```

---

### Audit Dashboard

#### 11. Dashboard Overview (GET)
```
GET /api/v1/audit/dashboard/overview/
```
**View Class:** `AuditDashboardOverviewView` (APIView)

**Response:** 200 OK
```json
{
  "recent_sessions": [
    {
      "id": "uuid",
      "name": "May Invoices",
      "status": "completed",
      "created_at": "...",
      "open_findings": 12,
      "critical_findings": 2
    }
  ],
  "latest_summary": {...},
  "finding_totals": {
    "critical": 15,
    "high": 45,
    "medium": 120,
    "low": 200
  },
  "recent_findings": [...6_findings...],
  "rule_groups": [
    {
      "code": "INV",
      "label": "Invoice Header",
      "color": "#2563eb",
      "pct": 94.5,
      "passed": 387,
      "failed": 23,
      "total": 410
    }
  ]
}
```

---

#### 12. Big Four Compliance (GET)
```
GET /api/v1/audit/big-four/
```
**View Class:** `BigFourComplianceView` (APIView)

**Response:** 200 OK
```json
{
  "overall_pass_rate": 88.5,
  "overall_status": "at_risk",
  "firms": [
    {
      "firm": "KPMG",
      "label": "KPMG — Invoice Completeness & Accuracy",
      "description": "...",
      "standard": "ISA 500 — Audit Evidence",
      "pass_rate": 92.3,
      "passed": 145,
      "failed": 12,
      "total": 157,
      "status": "compliant",
      "groups": [
        {"code": "INV", "passed": 145, "failed": 12, "total": 157, "pass_rate": 92.3}
      ]
    }
  ]
}
```

---

#### 13. Custom Rules (CRUD)
```
GET    /api/v1/audit/rules/
POST   /api/v1/audit/rules/
GET    /api/v1/audit/rules/{id}/
PATCH  /api/v1/audit/rules/{id}/
DELETE /api/v1/audit/rules/{id}/
POST   /api/v1/audit/rules/{id}/test/
```
**View Classes:** `CustomRuleListCreateView`, `CustomRuleDetailView`, `CustomRuleTestView`

**Permissions:** `IsAuthenticated` (list), `IsSeniorAuditorOrAbove` (update/delete)

---

## DOCUMENT PROCESSING

### Resource: Document (7 Typed Models)

Typed documents: PurchaseOrder, BankStatement, PayrollSheet, ExpenseReport, VATReturn, FixedAsset, SalesReceipt

#### 1. Upload Document (POST)
```
POST /api/v1/documents/upload/
POST /api/v1/documents/upload/typed/
```
**View Class:** `DocumentUploadView`, `TypedDocumentUploadView`

**Request:**
```
multipart/form-data:
  file: <binary>
  document_type: "purchase_order|bank_statement|payroll|expense_report|vat_return|fixed_asset|sales_receipt"
  notes: "Optional notes"
```

**Response:** 201 CREATED
```json
{
  "id": "uuid",
  "organization": "uuid",
  "uploaded_by": "uuid",
  "file": "/api/v1/documents/{id}/download/",
  "original_filename": "...",
  "file_size": 245632,
  "mime_type": "application/pdf",
  "document_type": "purchase_order",
  "processing_status": "pending",
  "language": null,
  "page_count": 1,
  "notes": "",
  "created_at": "2026-02-20T14:30:00Z"
}
```

**Permissions:** `IsAuthenticated`, `RequiresOrganization`  
**Parsers:** `MultiPartParser`, `FormParser`

---

#### 2. List Documents (GET)
```
GET /api/v1/documents/
```
**View Class:** `DocumentListView` (generics.ListAPIView)

**Query Parameters:**
- `document_type` - Filter by type
- `status` - pending, processing, completed, needs_review, failed
- `language` - Filter by language
- `risk_level` - Filter by analysis risk
- `is_duplicate` - Boolean filter
- `search` - Filename search
- `date_from`, `date_to`

**Response:** 200 OK
```json
{
  "count": 150,
  "results": [
    {
      "id": "uuid",
      "original_filename": "PO-2026-001.pdf",
      "document_type": "purchase_order",
      "processing_status": "completed",
      "file_size": 245632,
      "language": "en",
      "page_count": 2,
      "uploaded_by_name": "Ahmed Ali",
      "created_at": "2026-02-20T14:30:00Z"
    }
  ]
}
```

**Serializer:** `DocumentListSerializer`

---

#### 3. Get Document Detail (GET)
```
GET /api/v1/documents/{id}/
```
**View Class:** `DocumentDetailView` (generics.RetrieveDestroyAPIView)

**Response:** 200 OK (full document with extracted data and analysis)

---

#### 4. Download Document (GET)
```
GET /api/v1/documents/{id}/download/
```
**View Class:** `DocumentDownloadView` (APIView)

---

#### 5. Analyse Document (POST)
```
POST /api/v1/documents/{id}/analyse/
```
**View Class:** `DocumentAnalyseView` (APIView)

**Request:**
```json
{
  "sync": false
}
```

**Response:** 202 ACCEPTED
```json
{
  "message": "Analysis queued",
  "document_id": "uuid",
  "status": "queued"
}
```

or (if sync=true and file < 1 MB):
```json
{
  "message": "Analysis complete",
  "document_id": "uuid",
  "analysis": {...full_analysis...},
  "processing_time_ms": 2345
}
```

---

#### 6. Get Analysis Result (GET)
```
GET /api/v1/documents/{id}/analysis/
```
**View Class:** `DocumentAnalysisResultView` (APIView)

**Response:** 200 OK
```json
{
  "id": "uuid",
  "document_id": "uuid",
  "document_type": "purchase_order",
  "extracted_fields": {
    "po_number": "PO-2026-001",
    "vendor_name": "ACME Corp",
    "total_amount": "5000.00",
    "currency": "SAR"
  },
  "classification": {
    "confidence": 0.95,
    "predicted_type": "purchase_order"
  },
  "risk_level": "low",
  "risk_score": 12.5,
  "is_duplicate": false,
  "findings": [...],
  "processing_time_ms": 2345
}
```

---

#### 7. Typed Document Endpoints

**Purchase Orders:**
```
GET    /api/v1/documents/purchase-orders/
GET    /api/v1/documents/purchase-orders/{id}/
POST   /api/v1/documents/purchase-orders/{id}/approve/
```
**Views:** `PurchaseOrderListView`, `PurchaseOrderDetailView`, `PurchaseOrderApproveView`

**Bank Statements:**
```
GET    /api/v1/documents/bank-statements/
GET    /api/v1/documents/bank-statements/{id}/
```

**Payroll:**
```
GET    /api/v1/documents/payroll/
GET    /api/v1/documents/payroll/{id}/
```

**Expense Reports:**
```
GET    /api/v1/documents/expense-reports/
GET    /api/v1/documents/expense-reports/{id}/
```

**VAT Returns:**
```
GET    /api/v1/documents/vat-returns/
GET    /api/v1/documents/vat-returns/{id}/
```

**Fixed Assets:**
```
GET    /api/v1/documents/fixed-assets/
GET    /api/v1/documents/fixed-assets/{id}/
```

**Sales Receipts:**
```
GET    /api/v1/documents/sales-receipts/
GET    /api/v1/documents/sales-receipts/{id}/
```

---

#### 8. Document Statistics (GET)
```
GET /api/v1/documents/stats/
```
**View Class:** `DocumentStatsView` (APIView)

**Response:** 200 OK
```json
{
  "total_documents": 500,
  "by_type": {
    "purchase_order": 120,
    "bank_statement": 100,
    "payroll": 80,
    "expense_report": 100,
    "vat_return": 50,
    "fixed_asset": 30,
    "sales_receipt": 20
  },
  "processing_status": {
    "pending": 10,
    "processing": 5,
    "completed": 480,
    "failed": 5
  }
}
```

---

## REPORTS

### Comprehensive Report Generation

#### 1. Generate Invoice Audit Report (POST)
```
POST /api/reports/invoice-audit/
```
**View Class:** `InvoiceAuditReportGenerateView`

**Request:**
```json
{
  "date_from": "2026-01-01",
  "date_to": "2026-02-28",
  "include_sections": ["overview", "invoices", "compliance", "findings"],
  "format": "json|html|pdf"
}
```

**Response:** 201 CREATED
```json
{
  "id": "uuid",
  "report_type": "invoice_audit",
  "generated_at": "2026-02-20T15:00:00Z",
  "period_from": "2026-01-01",
  "period_to": "2026-02-28",
  "status": "completed"
}
```

---

#### 2. Get Report Detail (GET)
```
GET /api/reports/invoice-audit/{id}/
GET /api/reports/invoice-audit/{id}/html/
GET /api/reports/invoice-audit/{id}/pdf/
```
**View Classes:** `InvoiceAuditReportDetailView`, `InvoiceAuditReportHTMLView`, `InvoiceAuditReportPDFView`

---

#### 3. Report Sub-Endpoints (GET)
```
GET /api/reports/invoice-audit/{id}/high-risk/?limit=20
GET /api/reports/invoice-audit/{id}/failed-rules/?category=DUP&limit=10
GET /api/reports/invoice-audit/{id}/supplier-analysis/?risk_tier=high&limit=15
GET /api/reports/invoice-audit/{id}/compliance/
```
**View Classes:** `HighRiskInvoicesView`, `FailedRulesView`, `SupplierAnalysisView`, `ComplianceEngineView`

---

#### 4. Executive Report (POST/GET)
```
POST /api/reports/executive/
GET  /api/reports/executive/latest/
GET  /api/reports/executive/{id}/pdf/
GET  /api/reports/executive/{id}/html/
```
**View Classes:** `ExecutiveReportGenerateView`, `ExecutiveReportLatestView`, `ExecutiveReportPDFView`, `ExecutiveReportHTMLView`

---

## ERROR RESPONSE CODES

| Code | Meaning | Example |
|------|---------|---------|
| **200** | OK | GET /invoices/ |
| **201** | Created | POST /invoices/upload/ |
| **202** | Accepted | POST /documents/{id}/analyse/?sync=false |
| **204** | No Content | - |
| **400** | Bad Request | Invalid query param, validation error |
| **403** | Forbidden | Not IsSeniorAuditorOrAbove |
| **404** | Not Found | Invoice not found |
| **409** | Conflict | Document already being processed |
| **422** | Unprocessable | Validation error (field-level) |

**Response Format (Error):**
```json
{
  "error": "Invoice not found.",
  "detail": "Optional detailed message"
}
```

---

## SOFT-DELETE PATTERN

**Implementation:** Fields `is_deleted`, `deleted_at`, `deleted_by` on Invoice, AuditCase, AuditSession, Document

**Features:**
1. DELETE requests set `is_deleted = True` (no hard delete)
2. List/Detail views exclude soft-deleted records by default
3. Audit trail entry created with event type DELETED
4. GDPR Article 17 compliance documented

**Example:**
```
DELETE /api/v1/invoices/{id}/
```
→ Sets `invoice.is_deleted = True`, `invoice.deleted_at = now()`, `invoice.deleted_by = request.user`

---

## PAGINATION & FILTERING

### Pagination (Django REST Framework Standard)
```
GET /api/v1/invoices/?page=2&page_size=50
```

**Response Includes:**
```json
{
  "count": 500,
  "next": "https://api.tadgeeg.com/api/v1/invoices/?page=3",
  "previous": "https://api.tadgeek.com/api/v1/invoices/?page=1",
  "results": [...]
}
```

### Filtering
**Backend:** `DjangoFilterBackend`, `SearchFilter`, `OrderingFilter`

**Examples:**
```
GET /api/v1/invoices/?status=approved&risk_level=low
GET /api/v1/invoices/?search=ACME&ordering=-created_at
GET /api/v1/documents/?date_from=2026-01-01&date_to=2026-02-28
```

---

## AUTHENTICATION & PERMISSIONS

### Authentication Classes
- **`JWTAuthentication`** - Bearer token from `/api/auth/token/`
- **`SessionAuthentication`** - Django session (optional)

### Permission Classes
- **`IsAuthenticated`** - User must be logged in
- **`IsOwnOrganization`** - User must belong to resource's organization
- **`IsSeniorAuditorOrAbove`** - User role ≥ Senior Auditor
- **`RequiresOrganization`** - User must have organization assigned

### Example Authorization Header
```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

---

## SUMMARY TABLE

| Feature | Endpoint | HTTP | View | Status |
|---------|----------|------|------|--------|
| **Invoices** | | | | |
| Upload | `/invoices/upload/` | POST | InvoiceUploadView | ✓ |
| List | `/invoices/` | GET | InvoiceListView | ✓ |
| Detail | `/invoices/{id}/` | GET/PATCH/DELETE | InvoiceDetailView | ✓ |
| Download | `/invoices/{id}/download/` | GET | InvoiceDownloadView | ✓ |
| Review | `/invoices/{id}/review/` | POST | InvoiceManualReviewView | ✓ |
| Approve | `/invoices/{id}/approve/` | POST | InvoiceApproveView | ✓ |
| Revalidate | `/invoices/{id}/revalidate/` | POST | InvoiceRevalidateView | ✓ |
| Batch List | `/invoices/batches/` | GET | InvoiceBatchListView | ✓ |
| Batch Detail | `/invoices/batches/{id}/` | GET | InvoiceBatchDetailView | ✓ |
| Reports | `/invoices/reports/risk/` | GET | InvoiceRiskReportView | ✓ |
| **Audit** | | | | |
| Cases List | `/audit/cases/` | GET/POST | AuditCaseListCreateView | ✓ |
| Cases Detail | `/audit/cases/{id}/` | GET/PATCH | AuditCaseDetailView | ✓ |
| Cases Bulk | `/audit/cases/bulk/` | POST | BulkCaseActionView | ✓ |
| Case Status | `/audit/cases/{id}/status/` | PATCH | UpdateCaseStatusView | ✓ |
| Comments | `/audit/cases/{id}/comments/` | GET/POST | CaseCommentView | ✓ |
| Assign | `/audit/cases/{id}/assign/` | POST | AssignCaseView | ✓ |
| Sessions | `/audit/sessions/{id}/` | GET | AuditSessionDetailView | ✓ |
| Dashboard | `/audit/dashboard/overview/` | GET | AuditDashboardOverviewView | ✓ |
| **Documents** | | | | |
| Upload | `/documents/upload/` | POST | DocumentUploadView | ✓ |
| List | `/documents/` | GET | DocumentListView | ✓ |
| Detail | `/documents/{id}/` | GET/DELETE | DocumentDetailView | ✓ |
| Analyse | `/documents/{id}/analyse/` | POST | DocumentAnalyseView | ✓ |
| Analysis Result | `/documents/{id}/analysis/` | GET | DocumentAnalysisResultView | ✓ |

---

**Last Updated:** March 25, 2026  
**API Version:** 2.0 (Production)
