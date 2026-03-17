# Tadgeeg — API Integration Guide

**Base URL:** `https://your-domain.com/api/v1`
**Version:** v1
**Format:** JSON (UTF-8) — except PDF/CSV export endpoints
**Date:** 2026-03-17

---

## Table of Contents

1. [Authentication Flow](#1-authentication-flow)
2. [Request / Response Conventions](#2-request--response-conventions)
3. [Error Reference](#3-error-reference)
4. [Rate Limiting](#4-rate-limiting)
5. [Module: Auth](#5-module-auth)
6. [Module: Documents](#6-module-documents)
7. [Module: Invoices](#7-module-invoices)
8. [Module: Audit Cases & Sessions](#8-module-audit-cases--sessions)
9. [Module: Reports](#9-module-reports)
10. [Module: Analytics](#10-module-analytics)
11. [Module: Compliance](#11-module-compliance)
12. [Module: Health Checks](#12-module-health-checks)
13. [RBAC Permission Matrix](#13-rbac-permission-matrix)
14. [Webhook / Polling Patterns](#14-webhook--polling-patterns)

---

## 1. Authentication Flow

Tadgeeg uses **JWT (JSON Web Tokens)** via `djangorestframework-simplejwt`.

### 1.1 Login and Obtain Tokens

```http
POST /api/v1/auth/login/
Content-Type: application/json

{
  "email": "auditor@company.sa",
  "password": "SecurePassword123!"
}
```

**Success response (200 OK):**
```json
{
  "access": "<JWT access token>",
  "refresh": "<JWT refresh token>",
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "auditor@company.sa",
    "full_name": "Ahmed Al-Rashidi",
    "role": "senior_auditor",
    "organization": {
      "id": "...",
      "name": "Riyadh Financial Corp",
      "country": "SA"
    }
  }
}
```

**OTP pending response (202 Accepted)** — when email is not verified:
```json
{
  "verification_required": true,
  "masked_email": "a****@company.sa",
  "otp_expires_in_seconds": 300,
  "message": "OTP sent to your email"
}
```

### 1.2 Verify Email OTP

```http
POST /api/v1/auth/otp/verify/
Content-Type: application/json

{
  "otp_code": "483921"
}
```

Returns the same token payload as login on success.

### 1.3 Using Tokens in Requests

Add the `Authorization` header to every authenticated request:

```http
GET /api/v1/invoices/
Authorization: Bearer <access_token>
```

The access token expires after a configured TTL (default: 60 minutes).
The refresh token is long-lived (default: 7 days).

### 1.4 Refresh Access Token

```http
POST /api/v1/auth/token/refresh/
Content-Type: application/json

{
  "refresh": "<refresh_token>"
}
```

**Response (200 OK):**
```json
{
  "access": "<new_access_token>"
}
```

### 1.5 Logout

```http
POST /api/v1/auth/logout/
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "refresh": "<refresh_token>"
}
```

The refresh token is blacklisted immediately — both tokens are invalidated.

### 1.6 Google OAuth Login

```http
POST /api/v1/auth/google/
Content-Type: application/json

{
  "id_token": "<Google ID token from Google Sign-In>"
}
```

Returns identical token payload as standard login.

---

## 2. Request / Response Conventions

### Headers (required on all authenticated requests)

| Header | Value |
|--------|-------|
| `Authorization` | `Bearer <access_token>` |
| `Content-Type` | `application/json` (or `multipart/form-data` for file uploads) |
| `Accept` | `application/json` |

### Pagination

List endpoints return paginated results:

```json
{
  "count": 150,
  "next": "https://your-domain.com/api/v1/invoices/?page=2",
  "previous": null,
  "results": [ ... ]
}
```

Use query parameter `?page=N` to navigate pages. Default page size: **20**.

### Filtering

Most list endpoints support query filters:

```
GET /api/v1/invoices/?status=flagged&risk_level=high&date_from=2026-01-01&date_to=2026-03-31
```

### Multi-tenancy

All data is scoped to the authenticated user's **organization**. You cannot access or mutate data belonging to another organization. Attempting to do so returns `404 Not Found` (not 403, to avoid information leakage).

---

## 3. Error Reference

### Error Response Shape

```json
{
  "error": "validation_failed",
  "message": "Invalid VAT number format",
  "details": {
    "vendor_vat_number": ["Must be exactly 15 digits starting with 3"]
  }
}
```

### Standard HTTP Status Codes

| Code | Meaning | When returned |
|------|---------|---------------|
| `200 OK` | Success | GET, PATCH, POST returning existing data |
| `201 Created` | Resource created | POST (new record created) |
| `202 Accepted` | Processing | OTP required; async task queued |
| `400 Bad Request` | Validation error | Missing required field, invalid value |
| `401 Unauthorized` | Not authenticated | Missing or expired token |
| `403 Forbidden` | Insufficient role | Correct user, wrong permission level |
| `404 Not Found` | Resource missing | ID not found, or cross-org access attempt |
| `409 Conflict` | Duplicate | Resource already exists |
| `415 Unsupported Media Type` | Wrong content type | Sending JSON to a multipart endpoint |
| `429 Too Many Requests` | Rate limited | See section 4 |
| `500 Internal Server Error` | Server error | Unexpected failure |

### Common Validation Errors

| Field | Error | Reason |
|-------|-------|--------|
| `email` | `Enter a valid email address` | Malformed email |
| `vendor_vat_number` | `Must be 15 digits` | ZATCA requires 15-digit VAT numbers |
| `files` | `Unsupported file type` | Extension not in allowed list |
| `action` | `action must be 'approve' or 'reject'` | Invoice approve endpoint |
| `password` | `At least 8 characters required` | Weak password |

---

## 4. Rate Limiting

Rate limiting is enforced **per organization** via `OrgRateLimitMiddleware`.

| Tier | Limit | Window |
|------|-------|--------|
| Default | 1,000 requests | 1 hour |
| Upload endpoints | 100 requests | 1 hour |
| AI/Analytics | 50 requests | 1 hour |

When exceeded, the response is:
```http
HTTP 429 Too Many Requests
Retry-After: 3600

{
  "error": "rate_limit_exceeded",
  "message": "Rate limit reached. Retry after 3600 seconds."
}
```

---

## 5. Module: Auth

**Base path:** `/api/v1/auth/`

### POST `/register/` — Register User

Creates a new user account. An OTP email is sent for verification.

**Request:**
```json
{
  "email": "new.user@company.sa",
  "password": "SecurePassword123!",
  "full_name": "Sara Al-Otaibi"
}
```

**Response (201):**
```json
{
  "verification_required": true,
  "masked_email": "n****@company.sa",
  "otp_expires_in_seconds": 300,
  "needs_org": true
}
```

---

### POST `/otp/resend/` — Resend OTP

```json
{}
```

**Response (200):**
```json
{
  "message": "OTP sent",
  "masked_email": "n****@company.sa",
  "otp_expires_in_seconds": 300,
  "resend_cooldown_seconds": 60,
  "attempts_remaining": 4
}
```

---

### GET/PATCH `/me/` — Current User Profile

**GET Response:**
```json
{
  "id": "uuid",
  "email": "user@company.sa",
  "full_name": "Ahmed Al-Rashidi",
  "role": "senior_auditor",
  "organization": { "id": "uuid", "name": "Riyadh FC", "country": "SA" }
}
```

**PATCH Request (partial):**
```json
{
  "full_name": "Ahmed M. Al-Rashidi"
}
```

---

### POST `/me/change-password/`

```json
{
  "old_password": "OldPass123!",
  "new_password": "NewPass456!"
}
```

---

### GET/PATCH `/organization/` — Current Organization

Returns or updates the authenticated user's organization settings.

**PATCH Request:**
```json
{
  "name": "Riyadh Financial Corp",
  "name_ar": "شركة الرياض المالية",
  "country": "SA",
  "vat_number": "300000000000003",
  "address": "King Fahd Road, Riyadh"
}
```

---

### GET/POST/PATCH `/organization/settings/`

Manages financial and notification preferences.

**Request / Response:**
```json
{
  "financial": {
    "default_currency": "SAR",
    "vat_rate": "0.15",
    "fiscal_year_start": "01-01"
  },
  "notifications": {
    "email_on_high_risk": true,
    "email_on_duplicate": true,
    "daily_digest": false
  }
}
```

---

### GET `/audit-logs/` — Audit Trail (Admin only)

Query parameters: `user_id`, `action`, `from_date`, `to_date`

**Response:**
```json
{
  "count": 450,
  "results": [
    {
      "id": "uuid",
      "user": { "id": "uuid", "email": "user@company.sa" },
      "action": "DOCUMENT_UPLOAD",
      "resource_type": "invoice_batch",
      "resource_id": "uuid",
      "timestamp": "2026-03-17T08:00:00Z",
      "changes": { "files": 12, "errors": 0 }
    }
  ]
}
```

---

## 6. Module: Documents

**Base path:** `/api/v1/documents/`

Supported file types: `PDF`, `JPG`, `PNG`, `TIFF`, `XLSX`, `XLS`, `CSV`, `JSON`, `ZIP`

### POST `/upload/` — Upload Document

```http
POST /api/v1/documents/upload/
Content-Type: multipart/form-data
Authorization: Bearer <token>

file=@invoice.pdf
document_type=invoice
notes=Q1 2026 supplier invoice
```

**Response (201):**
```json
{
  "id": "uuid",
  "original_filename": "invoice.pdf",
  "file_size": 204800,
  "mime_type": "application/pdf",
  "document_type": "invoice",
  "processing_status": "pending",
  "created_at": "2026-03-17T08:00:00Z"
}
```

Processing runs asynchronously via Celery. Poll `GET /<id>/` for status.

---

### GET `/` — List Documents

Query parameters:

| Param | Type | Example |
|-------|------|---------|
| `document_type` | string | `invoice`, `bank_statement` |
| `processing_status` | string | `pending`, `completed`, `failed` |
| `risk_level` | string | `low`, `medium`, `high`, `critical` |
| `is_duplicate` | boolean | `true` |
| `search` | string | filename or vendor name |
| `date_from` | date | `2026-01-01` |
| `date_to` | date | `2026-03-31` |

---

### POST `/<id>/analyse/` — Trigger Full AI Pipeline

Runs: classification → extraction → duplicate detection → fraud scoring → compliance → risk scoring → audit rules.

```json
{ "sync": false }
```

Set `"sync": true` for synchronous processing (waits for result — slower).

**Response (202 Accepted — async):**
```json
{
  "message": "Analysis queued",
  "document_id": "uuid",
  "status": "processing"
}
```

**Response (200 OK — sync):**
```json
{
  "message": "Analysis complete",
  "document_id": "uuid",
  "analysis": { ... },
  "processing_time_ms": 3420
}
```

---

### GET `/<id>/analysis/` — Get Analysis Result

```json
{
  "classification": {
    "document_type": "invoice",
    "confidence": 0.97,
    "method": "openai"
  },
  "extracted_fields": {
    "vendor_name": "Acme Supplies",
    "vendor_vat_number": "300000000000010",
    "invoice_number": "INV-2026-001",
    "invoice_date": "2026-03-15",
    "total_amount": "1150.00",
    "vat_amount": "150.00",
    "currency": "SAR"
  },
  "risk_score": 23,
  "risk_level": "low",
  "fraud_score": 0.12,
  "duplicate_score": 0.0,
  "is_duplicate": false,
  "compliance_score": 0.9,
  "rule_results": [
    {
      "rule_id": "R001",
      "rule_name": "Duplicate Invoice Detection",
      "result": "PASSED",
      "severity": "HIGH",
      "explanation": ""
    }
  ],
  "missing_fields": [],
  "compliance_issues": []
}
```

---

### PATCH `/<id>/validate/` — Apply Human Corrections

```json
{
  "corrections": {
    "vendor_name": "Acme Supplies LLC",
    "total_amount": "1150.00"
  },
  "validation_status": "approved"
}
```

---

## 7. Module: Invoices

**Base path:** `/api/v1/invoices/`

### POST `/upload/` — Upload Invoices

Accepts single file, multiple files, ZIP, CSV, or JSON array.
Runs all **30 ZATCA audit rules** on each invoice automatically.

```http
POST /api/v1/invoices/upload/
Content-Type: multipart/form-data

files=@invoice1.pdf
files=@invoice2.pdf
batch_name=March 2026 Batch
```

**Response (201):**
```json
{
  "batch_id": "uuid",
  "batch_name": "March 2026 Batch",
  "session_id": "uuid",
  "total_files": 2,
  "processed": 2,
  "failed": 0,
  "status": "completed",
  "results": [
    {
      "filename": "invoice1.pdf",
      "invoice_id": "uuid",
      "invoice_number": "INV-001",
      "vendor_name": "Acme Corp",
      "total_amount": "1150.00",
      "risk_score": 15,
      "risk_level": "low",
      "is_duplicate": false,
      "rules_passed": 28,
      "rules_failed": 2,
      "status": "flagged"
    }
  ],
  "errors": []
}
```

The `session_id` can be used to poll progress at `/api/v1/audit/sessions/<session_id>/progress/`.

---

### GET `/` — List Invoices

| Param | Example |
|-------|---------|
| `status` | `pending`, `approved`, `rejected`, `flagged` |
| `risk_level` | `low`, `medium`, `high`, `critical` |
| `is_duplicate` | `true` |
| `vendor_id` | UUID |
| `date_from` | `2026-01-01` |
| `date_to` | `2026-03-31` |

---

### GET `/<id>/` — Invoice Detail

```json
{
  "id": "uuid",
  "invoice_number": "INV-2026-001",
  "vendor_name": "Acme Corp",
  "vendor_vat_number": "300000000000010",
  "invoice_date": "2026-03-15",
  "total_amount": "1150.00",
  "vat_amount": "150.00",
  "subtotal": "1000.00",
  "currency": "SAR",
  "risk_score": 15,
  "risk_level": "low",
  "status": "pending",
  "is_duplicate": false,
  "validation_result": { "passed": 28, "failed": 2 },
  "audit_cases": []
}
```

---

### POST `/<id>/approve/` — Approve or Reject Invoice

**Required role:** `senior_auditor` or above.

```json
{
  "action": "approve"
}
```

Or to reject:
```json
{
  "action": "reject",
  "reason": "VAT number does not match ZATCA registry"
}
```

**Response (200):**
```json
{
  "invoice_id": "uuid",
  "status": "approved",
  "message": "Approved by Ahmed Al-Rashidi"
}
```

---

### POST `/<id>/revalidate/` — Rerun 30 Rules

Forces re-evaluation of all validation rules (e.g. after human corrections).

---

### GET `/reports/risk/` — Risk Report

Query: `date_from`, `date_to`

```json
{
  "critical_count": 2,
  "high_count": 8,
  "medium_count": 15,
  "low_count": 47,
  "high_risk_invoices": [ ... ]
}
```

---

### GET `/rules/` — 30 Validation Rules Reference

Returns all rule definitions with IDs, names, categories, and risk weights.

---

## 8. Module: Audit Cases & Sessions

**Base path:** `/api/v1/audit/`

### Audit Sessions

An **AuditSession** is created automatically on every invoice upload. It tracks processing progress through 7 states:

```
RECEIVED → EXTRACTING → NORMALIZING → VALIDATING → COMPLETED
                                                 ↘ REVIEW_REQUIRED
                                                 ↘ FAILED
```

#### GET `/sessions/<id>/progress/` — Poll Progress

Lightweight endpoint for polling (no database joins).

```json
{
  "id": "uuid",
  "state": "validating",
  "progress_pct": 67,
  "total_count": 12,
  "processed_count": 8,
  "success_count": 7,
  "failed_count": 1,
  "risk_level": "medium"
}
```

**Recommended polling interval:** 3 seconds. Stop when `state` is terminal (`completed`, `review_required`, `failed`).

#### GET `/sessions/<id>/` — Session Detail

Full session including findings:

```json
{
  "session": {
    "id": "uuid",
    "state": "completed",
    "session_name": "March 2026 Batch",
    "total_count": 12,
    "success_count": 11,
    "failed_count": 1,
    "duplicate_count": 1,
    "high_risk_count": 2,
    "risk_level": "medium",
    "executive_summary": {
      "overview": "11 of 12 invoices processed successfully...",
      "key_risks": ["2 high-risk vendors identified"],
      "recommendations": ["Review vendor INV-007"],
      "compliance_status": "compliant"
    }
  },
  "findings": [ ... ]
}
```

#### POST `/sessions/<id>/retry/` — Retry Failed Documents

Re-queues all failed documents in this session.

#### GET/POST `/sessions/<id>/summary/` — AI Executive Summary

**POST to regenerate:**
```json
{ "language": "ar" }
```

---

### Audit Findings

#### GET `/findings/` — List Findings

| Param | Example |
|-------|---------|
| `session` | UUID |
| `severity` | `critical`, `high`, `medium`, `low` |
| `status` | `open`, `in_review`, `resolved`, `dismissed` |
| `category` | `duplicate`, `fraud`, `compliance`, `anomaly` |

#### PATCH `/findings/<id>/resolve/`

```json
{ "status": "resolved" }
```

---

### Audit Cases

#### POST `/cases/` — Create Case

```json
{
  "title": "Duplicate VAT registration detected",
  "description": "Invoice INV-007 shares VAT number with INV-003",
  "case_type": "duplicate_invoice",
  "priority": "high",
  "invoice_id": "uuid"
}
```

#### PATCH `/cases/<id>/status/` — Update Status

**Required role:** `senior_auditor` or above.

```json
{
  "status": "resolved",
  "resolution_notes": "Confirmed duplicate — rejected invoice INV-007"
}
```

#### POST `/cases/<id>/assign/`

```json
{ "user_id": "uuid" }
```

---

## 9. Module: Reports

**Base path:** `/api/v1/reports/`

### POST `/generate/` — Generate Audit Report

**Required role:** `senior_auditor` or above.

```json
{
  "report_name": "Q1 2026 Audit",
  "date_from": "2026-01-01",
  "date_to": "2026-03-31",
  "include_invoices": true,
  "include_transactions": false
}
```

**Response (201):**
```json
{
  "id": "uuid",
  "report_type": "invoice_audit",
  "status": "completed",
  "download_url": "/api/v1/reports/uuid/pdf/"
}
```

---

### GET `/<id>/pdf/` — Download Report as PDF

Returns binary PDF. Requires `Authorization` header.

```http
GET /api/v1/reports/<id>/pdf/
Authorization: Bearer <token>
```

**Response:** `Content-Type: application/pdf`

**JavaScript example:**
```javascript
const token = localStorage.getItem('fin_token');
const res = await fetch(`/api/v1/reports/${id}/pdf/`, {
  headers: { Authorization: `Bearer ${token}` }
});
const blob = await res.blob();
const url = URL.createObjectURL(blob);
const a = document.createElement('a');
a.href = url;
a.download = `report-${id}.pdf`;
a.click();
```

---

## 10. Module: Analytics

**Base path:** `/api/v1/analytics/`

### POST `/detect-anomalies/` — Anomaly Detection

**Required role:** `senior_auditor` or above.

```json
{
  "date_from": "2026-01-01",
  "date_to": "2026-03-31",
  "min_amount": 10000,
  "auto_create_cases": true
}
```

**Response:**
```json
{
  "anomalies": [
    {
      "transaction_id": "uuid",
      "amount": "1500000.00",
      "anomaly_type": "amount_spike",
      "score": 0.94,
      "description": "Amount 12× above vendor average"
    }
  ],
  "message": "3 anomalies found"
}
```

---

### POST `/benford-analysis/` — Benford's Law

```json
{
  "date_from": "2026-01-01",
  "date_to": "2026-03-31"
}
```

**Response:**
```json
{
  "benford_distribution": {
    "1": 0.301, "2": 0.176, "3": 0.125
  },
  "actual_distribution": {
    "1": 0.18, "2": 0.22, "3": 0.14
  },
  "p_value": 0.002,
  "anomalies": ["Digit 1 under-represented — possible manipulation"],
  "risk_assessment": "high"
}
```

---

### POST `/forecast/cashflow/`

```json
{
  "months_forward": 6,
  "historical_periods": 12
}
```

---

### POST `/query/` — Natural Language Query

```json
{
  "query": "Top 5 vendors by total invoice amount in Q1 2026"
}
```

**Response:**
```json
{
  "results": [ ... ],
  "execution_time": 0.24,
  "filters_applied": { "date_from": "2026-01-01", "date_to": "2026-03-31" }
}
```

---

### GET `/kpis/` — Financial KPIs

```json
{
  "kpis": {
    "total_invoices": 450,
    "total_amount_sar": "4500000.00",
    "high_risk_rate": 0.08,
    "duplicate_rate": 0.02,
    "compliance_score": 0.94,
    "avg_processing_time_ms": 1820
  }
}
```

---

## 11. Module: Compliance

**Base path:** `/api/v1/compliance/`

### POST `/check/` — Run Compliance Check

**Required role:** `compliance_officer` or above.

```json
{
  "date_from": "2026-01-01",
  "date_to": "2026-03-31",
  "rule_ids": ["ZATCA-001", "VAT-002"]
}
```

**Response:**
```json
{
  "violations": [
    {
      "rule_id": "ZATCA-001",
      "description": "Invoice missing QR code",
      "severity": "high",
      "invoice_id": "uuid",
      "invoice_number": "INV-007"
    }
  ],
  "violations_saved": 3,
  "result": "non_compliant"
}
```

---

### POST `/vat/` — ZATCA VAT Compliance

```json
{
  "date_from": "2026-01-01",
  "date_to": "2026-03-31",
  "include_zero_rated": false
}
```

**Response:**
```json
{
  "compliance_score": 0.91,
  "total_vat_collected": "67500.00",
  "violations": [ ... ],
  "issues": [
    "3 invoices missing ZATCA QR code",
    "1 invoice with incorrect VAT rate (16% instead of 15%)"
  ]
}
```

---

### PATCH `/violations/<id>/resolve/`

**Required role:** `compliance_officer` or above.

```json
{
  "status": "resolved",
  "remediation_notes": "Corrected VAT rate on reissued invoice INV-007-R"
}
```

---

## 12. Module: Health Checks

**Base path:** `/health/`
No authentication required.

### GET `/` — Basic Health

```json
{
  "status": "healthy",
  "database": "ok",
  "timestamp": "2026-03-17T08:00:00Z"
}
```

### GET `/ready/` — Kubernetes Readiness

Returns `200 OK` when ready, `503` when not.

### GET `/full/` — Full Component Health

```http
GET /health/full/?heavy=true
```

```json
{
  "status": "healthy",
  "duration_ms": 142,
  "components": {
    "database": { "status": "ok", "latency_ms": 3 },
    "redis": { "status": "ok", "latency_ms": 1 },
    "celery": { "status": "ok", "worker_count": 4 },
    "tesseract": { "status": "ok", "version": "5.3.0" },
    "openai": { "status": "ok", "reachable": true }
  },
  "pipeline": {
    "stuck_documents": 0,
    "success_rate_24h": 0.98
  }
}
```

`?heavy=true` adds Tesseract and OpenAI checks (slower — use for diagnostics only, not liveness probes).

---

## 13. RBAC Permission Matrix

| Endpoint | admin | chief_audit_officer | senior_auditor | junior_auditor | compliance_officer | finance_manager | external_auditor |
|----------|:-----:|:-------------------:|:--------------:|:--------------:|:-----------------:|:---------------:|:----------------:|
| Upload documents / invoices | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| View invoices & documents | ✅ | ✅ | ✅ | ✅ (read) | ✅ | ✅ | ✅ (read) |
| Approve / reject invoices | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| Generate reports | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ |
| Run analytics / anomaly | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| Run compliance checks | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ |
| Manage audit cases | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ | ✅ (read) |
| Manage users / org | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| View audit trail logs | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |

**Permission class names used in code:**

| Class | Applies To |
|-------|-----------|
| `IsAuthenticated` | Any logged-in user |
| `IsSeniorAuditorOrAbove` | senior_auditor, chief_audit_officer, admin |
| `IsComplianceOrAbove` | compliance_officer, senior_auditor, chief_audit_officer, admin |
| `IsAdminUser` | admin only |
| `IsOwnOrganization` | Validates the record belongs to user's org |
| `IsSameUserOrAdmin` | Self or admin |

---

## 14. Webhook / Polling Patterns

### Invoice Upload → Progress Polling

```
1. POST /api/v1/invoices/upload/  →  { session_id: "uuid", batch_id: "uuid" }
2. Every 3s: GET /api/v1/audit/sessions/<session_id>/progress/
3. Stop when state ∈ { "completed", "review_required", "failed" }
4. GET /api/v1/audit/sessions/<session_id>/  →  full results + findings
```

**JavaScript example:**
```javascript
async function pollSession(sessionId, token) {
  const headers = { Authorization: `Bearer ${token}` };
  const TERMINAL = new Set(['completed', 'review_required', 'failed']);

  while (true) {
    const res = await fetch(`/api/v1/audit/sessions/${sessionId}/progress/`, { headers });
    const data = await res.json();

    updateProgressBar(data.progress_pct);

    if (TERMINAL.has(data.state)) {
      return fetchFullSession(sessionId, headers);
    }

    await new Promise(r => setTimeout(r, 3000));
  }
}
```

### Document Processing → Status Polling

```
1. POST /api/v1/documents/upload/      →  { id, processing_status: "pending" }
2. POST /api/v1/documents/<id>/analyse/ →  { status: "processing" }
3. Every 2s: GET /api/v1/documents/<id>/
4. Stop when processing_status ∈ { "completed", "failed", "needs_review" }
5. GET /api/v1/documents/<id>/analysis/ →  full AI result
```

---

## Quick Reference — All Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/v1/auth/login/` | None | Login |
| POST | `/api/v1/auth/register/` | None | Register |
| POST | `/api/v1/auth/otp/verify/` | None | Verify OTP |
| POST | `/api/v1/auth/token/refresh/` | None | Refresh token |
| POST | `/api/v1/auth/logout/` | ✅ | Logout |
| GET/PATCH | `/api/v1/auth/me/` | ✅ | User profile |
| GET/PATCH | `/api/v1/auth/organization/` | ✅ | Organization |
| POST | `/api/v1/documents/upload/` | ✅ | Upload document |
| GET | `/api/v1/documents/` | ✅ | List documents |
| GET | `/api/v1/documents/<id>/` | ✅ | Document detail |
| POST | `/api/v1/documents/<id>/analyse/` | ✅ | Trigger AI pipeline |
| GET | `/api/v1/documents/<id>/analysis/` | ✅ | Get AI results |
| PATCH | `/api/v1/documents/<id>/validate/` | ✅ | Apply corrections |
| POST | `/api/v1/invoices/upload/` | ✅ | Upload invoices |
| GET | `/api/v1/invoices/` | ✅ | List invoices |
| GET | `/api/v1/invoices/<id>/` | ✅ | Invoice detail |
| POST | `/api/v1/invoices/<id>/approve/` | ✅ Senior | Approve/reject |
| POST | `/api/v1/invoices/<id>/revalidate/` | ✅ | Rerun 30 rules |
| GET | `/api/v1/audit/sessions/<id>/progress/` | ✅ | Poll session |
| GET | `/api/v1/audit/sessions/<id>/` | ✅ | Session detail |
| POST | `/api/v1/audit/sessions/<id>/retry/` | ✅ | Retry failed |
| GET/POST | `/api/v1/audit/sessions/<id>/summary/` | ✅ | AI summary |
| GET | `/api/v1/audit/findings/` | ✅ | List findings |
| PATCH | `/api/v1/audit/findings/<id>/resolve/` | ✅ | Resolve finding |
| GET | `/api/v1/audit/cases/` | ✅ | List cases |
| POST | `/api/v1/audit/cases/` | ✅ | Create case |
| POST | `/api/v1/reports/generate/` | ✅ Senior | Generate report |
| GET | `/api/v1/reports/<id>/pdf/` | ✅ | Download PDF |
| POST | `/api/v1/analytics/detect-anomalies/` | ✅ Senior | Anomaly detection |
| POST | `/api/v1/analytics/benford-analysis/` | ✅ Senior | Benford's law |
| GET | `/api/v1/analytics/kpis/` | ✅ | KPIs dashboard |
| POST | `/api/v1/compliance/check/` | ✅ Compliance | Compliance check |
| POST | `/api/v1/compliance/vat/` | ✅ Compliance | ZATCA VAT check |
| GET | `/health/` | None | Basic health |
| GET | `/health/full/` | None | Full health |

---

*Auto-generated from codebase — 2026-03-17*
*Interactive docs available at: `/api/docs/` (Swagger UI) and `/api/redoc/` (ReDoc)*
