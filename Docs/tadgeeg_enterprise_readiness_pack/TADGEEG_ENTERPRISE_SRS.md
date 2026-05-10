# Tadgeeg Enterprise Software Requirements Specification

## 1. Executive Summary
Tadgeeg is an AI-powered financial auditing and compliance platform. It reads invoices and financial documents, extracts structured data, validates VAT and accounting rules, detects anomalies and duplicates, generates reports, supports Arabic/English, and integrates with ERP systems.

The platform must be treated as an enterprise audit intelligence layer, not only an OCR tool.

## 2. Product Goals
- Reduce manual financial audit effort.
- Detect fraud, anomalies, duplicate payments, VAT errors, and compliance gaps.
- Support ZATCA Phase 2 and GCC VAT rules.
- Generate audit reports, VAT reports, risk reports, and executive dashboards.
- Integrate with SAP, Oracle, Odoo, Daftra-like systems, POS systems, and custom ERPs.
- Support high-volume enterprise clients with many branches and millions of financial records.

## 3. User Roles
| Role | Responsibility |
|---|---|
| Platform Super Admin | Manages platform, tenants, global settings |
| Organization Admin | Manages users, branches, permissions, integrations |
| Finance Manager | Reviews dashboards, reports, approvals |
| Auditor | Reviews findings, evidence, exceptions |
| Accountant | Uploads files, corrects extracted data |
| Compliance Officer | Reviews VAT/ZATCA compliance |
| Executive | Views KPIs, risk, ROI, branch performance |
| API Client | ERP/POS server-to-server integration |

## 4. Core Modules
1. Authentication and tenant isolation.
2. Organization and branch management.
3. Document upload and ingestion.
4. OCR and structured parsing.
5. Document normalization.
6. Rule engine.
7. AI anomaly and fraud detection.
8. VAT/ZATCA compliance validation.
9. Reports and exports.
10. Executive dashboards.
11. ERP/API integrations.
12. Audit logs and workflow.

## 5. Supported Upload Modes
- Single document upload.
- Multiple documents.
- ZIP upload.
- Bulk Excel upload.
- Bulk CSV upload.
- JSON/JSONL upload.
- API upload.
- Mobile camera upload.

## 6. Supported Document Types
| Document Type | Priority |
|---|---|
| Sales invoice | P0 |
| Purchase invoice | P0 |
| Purchase order | P0 |
| Goods receipt note | P0 |
| Payment voucher | P0 |
| Receipt voucher | P1 |
| Cash voucher | P1 |
| Bank statement | P0 |
| Payroll sheet | P1 |
| Expense report | P1 |
| VAT return | P0 |
| Journal entry | P0 |
| General ledger | P0 |
| Ledger | P0 |
| Contract | P1 |
| Supplier statement | P1 |
| Customer statement | P1 |
| Sales order | P1 |
| Quotation | P2 |
| Proforma invoice | P2 |

## 7. OCR and Extraction Requirements
The system shall:
- Extract Arabic and English invoice data.
- Extract from PDF, image, scanned documents, Excel, CSV, JSON, and camera uploads.
- Provide confidence score per field.
- Preserve raw extracted text.
- Allow human correction.
- Route low-confidence documents to manual review.

Core extracted fields:
- Document number.
- Date.
- Supplier/customer.
- VAT number.
- Currency.
- Subtotal.
- VAT amount.
- Total amount.
- Line items.
- QR/TLV data where available.

## 8. Normalization Requirements
Every document must be normalized before audit:
```json
{
  "document_id": "uuid",
  "document_type": "purchase_invoice",
  "organization_id": "uuid",
  "document_number": "INV-1001",
  "document_date": "2026-05-10",
  "currency": "SAR",
  "total_amount": 1150,
  "tax_amount": 150,
  "parties": {},
  "line_items": [],
  "accounting_entries": [],
  "metadata": {},
  "validation_errors": []
}
```

## 9. Rule Engine Requirements
The system shall use one canonical audit pipeline:
Upload → Extract → Normalize → Rule Engine → Risk Score → Findings → Report → Dashboard.

Every active rule must have:
- rule_id.
- name.
- document_type.
- severity.
- implementation class.
- input schema.
- output schema.
- tests.
- expected finding.

No active production rule may point to a missing or fake implementation.

## 10. AI Requirements
AI capabilities:
- OCR field extraction.
- Handwritten receipt recognition.
- Duplicate detection.
- Benford analysis.
- Outlier detection.
- Vendor/customer risk scoring.
- Cash-flow forecasting.
- AI-generated audit explanations.

AI must be explainable and supported by evidence. High-risk AI findings require human review.

## 11. Compliance Requirements
The system shall:
- Validate VAT calculations.
- Validate invoice mandatory fields.
- Validate QR/TLV where applicable.
- Support ZATCA Phase 2 architecture.
- Store compliance evidence.
- Generate compliance reports.
- Support configurable GCC VAT profiles.

## 12. Reporting Requirements
Required reports:
- Audit summary.
- Detailed findings.
- VAT compliance.
- ZATCA compliance.
- Duplicate invoice.
- Vendor risk.
- Customer risk.
- Branch KPI.
- P&L.
- Balance sheet.
- Cash-flow forecast.
- General ledger integrity.
- Three-way matching.

Formats: HTML, PDF, Excel, CSV, JSON API.

## 13. Non-Functional Requirements
| Area | Requirement |
|---|---|
| Security | RBAC, tenant isolation, private files, encryption |
| Performance | Async processing, scalable workers, optimized dashboards |
| Availability | Target 99.9% only after monitoring/HA readiness |
| Localization | Arabic/English, RTL/LTR reports |
| Auditability | Full audit trail for actions and findings |
| Integration | API, webhooks, ERP sync, idempotency |

## 14. Enterprise Acceptance Criteria
- P0 document types work end-to-end.
- Rule catalog validation passes.
- Celery/Redis production deployment works.
- No public exposure of financial files.
- Bulk upload handles 5,000+ rows.
- ZATCA sandbox evidence exists before compliance claim.
- AI claims have validation reports.
- Tenant isolation tests pass.
- Reports render correctly in Arabic and English.
- Monitoring, backup, and incident response are enabled.
