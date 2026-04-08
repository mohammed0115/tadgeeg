# 📊 Executive AI Report System - API Documentation

## Overview

The Executive AI Report System is a professional decision-support tool designed for C-suite executives (CFO, Managing Director) that transforms raw audit data into actionable executive reports. It supports all document types (Invoice, PO, Bank Statement, Contract, Expense Report, Journal Entry) with bilingual output (Arabic/English).

---

## 🎯 Features

✅ **7-Section Professional Reports:**
1. Executive Summary — Key metrics & decision
2. Key Findings — Strengths & critical issues
3. Risk Interpretation — Why problems matter
4. Business Impact — Financial implications
5. Decision — APPROVED / APPROVED WITH CONDITIONS / REJECTED
6. Immediate Actions — Numbered tasks with deadlines
7. Process Improvements — Document-type-specific enhancements
8. AI Insight — Pattern analysis (isolated vs systemic problem)

✅ **Bilingual Support:** Arabic formal prose (فصحى واضحة) + English

✅ **Document-Type Agnostic:** Works with any document type via Enum-based system

✅ **Risk-Driven Decision Logic:**
- Blocking rules → REJECTED
- <70% compliance → REJECTED
- 70-85% compliance → APPROVED WITH CONDITIONS
- 85%+ compliance + no blocking rules → APPROVED

---

## 📡 API Endpoints

### 1. Generate Report from Raw Data

**Endpoint:** `POST /api/v1/reports/executive-report/`

**Description:** Generate an executive report from audit data dictionary (no database needed).

**Request:**
```bash
curl -X POST http://localhost:8000/api/v1/reports/executive-report/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "document_type": "invoice",
    "document_id": "INV-2026-001",
    "document_number": "INV-2026-001",
    "company": "Acme Corp",
    "total_amount": 14400000,
    "currency": "SAR",
    "compliance_score": 78,
    "risk_score": 35,
    "risk_level": "high",
    "rules_passed": 15,
    "rules_failed": 5,
    "supplier": {
      "name": "TechSupplier Inc",
      "vat_valid": true
    },
    "zatca_compliance": 90,
    "failed_rules": [
      {
        "code": "INV-008",
        "name_ar": "مبلغ الفاتورة في النطاق",
        "name_en": "Invoice Amount Range",
        "reason": "Amount exceeds normal vendor range",
        "severity": "High",
        "blocks_approval": true,
        "impact_ar": "قد يشير إلى احتيال أو تضخيم التكاليف"
      },
      {
        "code": "VAT-002",
        "name_ar": "حساب الضريبة",
        "name_en": "VAT Calculation",
        "reason": "VAT not aligned with system calculation",
        "severity": "Medium",
        "blocks_approval": false
      }
    ],
    "auditor_name": "مدقق النظام"
  }'
```

**Response (Success):**
```json
{
  "status": "success",
  "report": {
    "executive_summary": "❌ مرفوض — المخاطرة عالية...",
    "key_findings": "✅ نسبة امتثال معقولة: 78%...",
    "risk_interpretation": "المخطط الأول: مبلغ الفاتورة...",
    "business_impact": "| السيناريو | الاحتمالية | الأثر |...",
    "decision": "❌ مرفوض — المخالفات الحرجة توجب الرفض",
    "immediate_actions": "1. رفع القضية إلى...",
    "process_improvements": "1. تحديث نطاقات المبالغ...",
    "ai_insight": "🔴 مشكلة نظامية..."
  },
  "document": {
    "type": "invoice",
    "number": "INV-2026-001",
    "amount": 14400000,
    "currency": "SAR"
  }
}
```

---

### 2. Generate Report from Database Record

**Endpoint:** `GET /api/v1/reports/{document_type}/{document_id}/executive-report/`

**Description:** Fetch document from database and auto-generate report.

**Supported Document Types:**
- `invoice` — Fully implemented
- `purchase_order` — Prepared (model integration pending)
- `bank_statement` — Prepared (model integration pending)
- `contract` — Prepared (model integration pending)

**Request:**
```bash
curl -X GET http://localhost:8000/api/v1/reports/invoice/abc-123-def/executive-report/ \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**Response:**
```json
{
  "status": "success",
  "report": { ... (same as above) ... },
  "metadata": {
    "generated_at": "2024-12-19T14:30:00Z",
    "auditor": "مدقق النظام",
    "compliance_score": 78,
    "risk_score": 35,
    "risk_level": "high"
  }
}
```

---

### 3. View Report as HTML

**Endpoint:** `GET /reports/{document_type}/{document_id}/executive-report/`

**Description:** Render full executive report in professional HTML format.

**Features:**
- Responsive design (mobile-friendly)
- Bilingual support (Arabic/English toggle)
- Print-optimized CSS
- Decision status color-coding (green/amber/red)
- Print & PDF download buttons

**Request:**
```bash
# Opens in browser at http://localhost:8000/reports/invoice/abc-123-def/executive-report/
```

---

## 📝 Request Payload Structure

### Invoice Example

```json
{
  "document_type": "invoice",
  "document_id": "unique-id-123",
  "document_number": "INV-2026-001",
  "company": "Your Company Name",
  "total_amount": 14400000,
  "currency": "SAR",
  "compliance_score": 78,
  "risk_score": 35,
  "risk_level": "high",
  "rules_passed": 15,
  "rules_failed": 5,
  "supplier": {
    "name": "Supplier Inc",
    "vat_valid": true
  },
  "zatca_compliance": 90,
  "failed_rules": [
    {
      "code": "UNIQUE_RULE_CODE",
      "name_ar": "اسم القاعدة بالعربية",
      "name_en": "Rule Name in English",
      "reason": "Why the rule failed",
      "severity": "Critical|High|Medium|Low",
      "blocks_approval": true,
      "impact_ar": "الأثر بالعربية (اختياري)",
      "impact_en": "Impact in English (optional)"
    }
  ],
  "auditor_name": "نظام التدقيق الذكي"
}
```

### Field Explanations

| Field | Type | Required | Example | Notes |
|-------|------|----------|---------|-------|
| `document_type` | string | ✓ | "invoice" | See supported types |
| `document_id` | string | ✓ | "abc-123" | Unique ID |
| `document_number` | string | ✓ | "INV-2026-001" | Display number |
| `company` | string | ✓ | "Acme Corp" | Company name |
| `total_amount` | float | ✓ | 14400000 | In currency units |
| `currency` | string | ✓ | "SAR" | ISO 4217 code |
| `compliance_score` | int | ✓ | 78 | 0-100 percentage |
| `risk_score` | float | ✓ | 35 | 0-100 risk level |
| `risk_level` | string | ✓ | "high" | critical/high/medium/low |
| `rules_passed` | int | ✓ | 15 | Count of passed rules |
| `rules_failed` | int | ✓ | 5 | Count of failed rules |
| `supplier` | object | - | {...} | Vendor info (if applicable) |
| `zatca_compliance` | int | - | 90 | 0-100 for Saudi invoices |
| `failed_rules` | array | - | [...] | See FailedRule structure |
| `auditor_name` | string | - | "System Auditor" | Display name |

---

## 🎓 Decision Logic

The system applies the following approval logic:

```
IF any_rule.blocks_approval == true:
    DECISION = "REJECTED"
ELIF compliance_score < 70:
    DECISION = "REJECTED"
ELIF compliance_score >= 85:
    DECISION = "APPROVED"
ELSE:  # 70 <= compliance_score < 85
    DECISION = "APPROVED WITH CONDITIONS"
```

---

## 🔑 Risk Levels

| Level | Color | Description |
|-------|-------|-------------|
| **critical** | 🔴 Red | Immediate action required, block approval |
| **high** | 🟠 Orange | Serious concerns, escalate to CFO |
| **medium** | 🟡 Yellow | Investigate further, conditional approval |
| **low** | 🟢 Green | Minor issues, standard approval |

---

## ✅ Testing

### Test Case 1: Clean Invoice (Auto-Approved)

```bash
curl -X POST http://localhost:8000/api/v1/reports/executive-report/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "document_type": "invoice",
    "document_id": "clean-1",
    "document_number": "INV-CLEAN-001",
    "company": "Safe Corp",
    "total_amount": 5000000,
    "currency": "SAR",
    "compliance_score": 95,
    "risk_score": 10,
    "risk_level": "low",
    "rules_passed": 18,
    "rules_failed": 0,
    "failed_rules": [],
    "zatca_compliance": 100
  }'
```

**Expected Response:** `"decision": "✅ موافق — جميع المعايير مستوفاة..."`

### Test Case 2: Risky Invoice (Conditional Approval)

```bash
curl -X POST http://localhost:8000/api/v1/reports/executive-report/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "document_type": "invoice",
    "document_id": "risky-1",
    "document_number": "INV-RISKY-001",
    "company": "Medium Corp",
    "total_amount": 10000000,
    "currency": "SAR",
    "compliance_score": 78,
    "risk_score": 45,
    "risk_level": "medium",
    "rules_passed": 12,
    "rules_failed": 3,
    "failed_rules": [
      {
        "code": "TEST-001",
        "name_ar": "اختبار",
        "name_en": "Test",
        "reason": "Sample failed rule",
        "severity": "Medium",
        "blocks_approval": false
      }
    ]
  }'
```

**Expected Response:** `"decision": "⚠️ موافق بشروط..."`

### Test Case 3: Blocked Invoice (Rejected)

```bash
curl -X POST http://localhost:8000/api/v1/reports/executive-report/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "document_type": "invoice",
    "document_id": "blocked-1",
    "document_number": "INV-BLOCKED-001",
    "company": "Risky Corp",
    "total_amount": 50000000,
    "currency": "SAR",
    "compliance_score": 45,
    "risk_score": 80,
    "risk_level": "critical",
    "rules_passed": 5,
    "rules_failed": 10,
    "failed_rules": [
      {
        "code": "INV-FRAUD-001",
        "name_ar": "اكتشاف احتيال",
        "name_en": "Fraud Detection",
        "reason": "Duplicate invoice detected",
        "severity": "Critical",
        "blocks_approval": true
      }
    ]
  }'
```

**Expected Response:** `"decision": "❌ مرفوض — ضرورة التحقيق الفوري..."`

---

## 🔐 Authentication

All endpoints require Django REST Framework authentication. Supported methods:

```bash
# Token authentication
curl -H "Authorization: Token YOUR_TOKEN" http://localhost:8000/api/v1/reports/...

# Bearer (JWT)
curl -H "Authorization: Bearer YOUR_JWT" http://localhost:8000/api/v1/reports/...
```

---

## 📂 Document Type Examples

### Purchase Order (PO)
```json
{
  "document_type": "purchase_order",
  "failed_rules": [
    {
      "code": "PO-008",
      "name_ar": "الموافقة من السلطة المختصة",
      "name_en": "Authority Approval",
      "reason": "Missing approver signature",
      "severity": "Critical",
      "blocks_approval": true
    }
  ]
}
```

### Bank Statement
```json
{
  "document_type": "bank_statement",
  "failed_rules": [
    {
      "code": "BNK-002",
      "name_ar": "عدم المطابقة مع السجلات",
      "name_en": "Record Reconciliation",
      "reason": "Amount mismatch with GL",
      "severity": "High"
    }
  ]
}
```

---

## 🛠️ Implementation Details

### Service Layer: `apps/reports/services/executive_ai_report_service.py`

**Key Classes:**
- `DocumentType` (Enum) — 6+ supported document types
- `RiskLevel` (Enum) — Critical/High/Medium/Low
- `FailedRule` (Dataclass) — Single compliance violation
- `DocumentAuditData` (Dataclass) — Complete audit context
- `ExecutiveAIReportGenerator` — Main service (8 public methods)

**Key Methods:**
```python
generator = ExecutiveAIReportGenerator()
report = generator.generate_report(audit_data)  # Returns Dict[str, str]
```

### View Layer: `apps/reports/views/executive_report_views.py`

**Key Views:**
- `generate_executive_report_api()` — POST API endpoint
- `ExecutiveReportDetailView` — GET API endpoint
- `executive_report_view()` — HTML template rendering

### Use Case Example (Python):

```python
from apps.reports.services.executive_ai_report_service import (
    ExecutiveAIReportGenerator,
    create_audit_data_from_dict
)

# Create audit data from dict
data = {
    "document_type": "invoice",
    "compliance_score": 78,
    # ... other fields ...
}
audit_data = create_audit_data_from_dict(data)

# Generate report
generator = ExecutiveAIReportGenerator()
report = generator.generate_report(audit_data)

# Access sections
print(report["executive_summary"])
print(report["decision"])
```

---

## 📋 Response Status Codes

| Code | Meaning | Example |
|------|---------|---------|
| 200 | Success (with data) | Report generated |
| 201 | Success (created) | Report saved to DB |
| 400 | Bad Request | Missing required fields |
| 401 | Unauthorized | Invalid token |
| 403 | Forbidden | Insufficient permissions |
| 404 | Not Found | Document not found |
| 500 | Server Error | Service exception |

---

## 🚀 Integration Examples

### Integrate with Django View

```python
from django.shortcuts import render
from rest_framework.views import APIView
from apps.reports.services.executive_ai_report_service import (
    ExecutiveAIReportGenerator,
    create_audit_data_from_dict
)

class MyInvoiceView(APIView):
    def get(self, request, invoice_id):
        # Fetch invoice from DB
        invoice = Invoice.objects.get(id=invoice_id)
        
        # Prepare audit data
        data = {
            "document_type": "invoice",
            "document_number": invoice.number,
            "compliance_score": invoice.compliance_score,
            # ... other fields ...
        }
        
        # Generate report
        audit_data = create_audit_data_from_dict(data)
        report = ExecutiveAIReportGenerator().generate_report(audit_data)
        
        # Return HTML
        return render(request, 'invoice_report.html', {'report': report})
```

### Integrate with Celery Task

```python
from celery import shared_task
from apps.reports.services.executive_ai_report_service import ExecutiveAIReportGenerator

@shared_task
def generate_bulk_reports(invoice_ids):
    for invoice_id in invoice_ids:
        invoice = Invoice.objects.get(id=invoice_id)
        data = prepare_audit_data(invoice)
        report = ExecutiveAIReportGenerator().generate_report(
            create_audit_data_from_dict(data)
        )
        # Save report, notify user, etc.
```

---

## 🐛 Troubleshooting

### Issue: 401 Unauthorized

**Solution:** Check your authentication token:
```bash
curl -X GET http://localhost:8000/api/v1/reports/invoice/123/executive-report/ \
  -H "Authorization: Token YOUR_CORRECT_TOKEN"
```

### Issue: 404 Document Not Found

**Solution:** Verify the document exists in the database:
```sql
SELECT * FROM invoices_invoice WHERE id = 'abc-123-def';
```

### Issue: Import Error: `executive_ai_report_service`

**Solution:** Ensure you're using the correct import path:
```python
from apps.reports.services.executive_ai_report_service import ExecutiveAIReportGenerator
```

---

## 📞 Support

For questions or issues:
1. Check this documentation
2. Review the service code comments
3. Contact the development team
4. File a GitHub issue

---

## 📅 Changelog

**v1.0 (2024-12-19)**
- ✅ Initial release
- ✅ 7-section executive report format
- ✅ Bilingual support (Arabic/English)
- ✅ All document types supported
- ✅ Decision logic implemented

---

## 📄 License

Part of Tadgeeg Platform — All Rights Reserved
