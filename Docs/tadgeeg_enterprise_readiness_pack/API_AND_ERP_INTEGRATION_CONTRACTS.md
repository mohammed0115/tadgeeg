# Tadgeeg API and ERP Integration Contracts

## 1. Purpose
Define the API and ERP integration architecture for Tadgeeg to connect with accounting systems, ERP platforms, POS systems, and enterprise data sources.

## 2. Principles
- Versioned API under `/api/v1/`.
- JSON response envelope.
- Tenant-aware access.
- Idempotent uploads.
- Pagination.
- Webhooks.
- Detailed error codes.
- Full audit logs.

## 3. Authentication
Supported:
- JWT for users.
- API keys for ERP/server integration.
- OAuth2 where required.
- Signed webhooks.

API keys must be scoped, rotatable, expirable, and logged.

## 4. Endpoint Matrix
| Entity | Endpoint |
|---|---|
| Documents | `/api/v1/documents/` |
| Invoices | `/api/v1/invoices/` |
| Purchase Orders | `/api/v1/purchase-orders/` |
| GRN | `/api/v1/goods-receipts/` |
| Payment Vouchers | `/api/v1/payment-vouchers/` |
| Receipt Vouchers | `/api/v1/receipt-vouchers/` |
| Cash Vouchers | `/api/v1/cash-vouchers/` |
| Bank Statements | `/api/v1/bank-statements/` |
| Journal Entries | `/api/v1/journal-entries/` |
| General Ledgers | `/api/v1/general-ledgers/` |
| Ledgers | `/api/v1/ledgers/` |
| Contracts | `/api/v1/contracts/` |
| Audit Runs | `/api/v1/audit-runs/` |
| Findings | `/api/v1/findings/` |
| Reports | `/api/v1/reports/` |
| Webhooks | `/api/v1/webhooks/` |

## 5. Response Envelope
```json
{
  "success": true,
  "data": {},
  "meta": {
    "request_id": "req_123",
    "timestamp": "2026-05-10T12:00:00Z"
  },
  "errors": []
}
```

## 6. Error Format
```json
{
  "success": false,
  "data": null,
  "errors": [
    {
      "code": "VALIDATION_ERROR",
      "field": "invoice_number",
      "message": "Invoice number is required"
    }
  ]
}
```

## 7. Upload API
`POST /api/v1/documents/upload/`

Fields:
- file.
- document_type.
- branch_id.
- source_system.
- external_id.
- metadata.

Response includes:
- document_id.
- status.
- audit_status.

## 8. Bulk Upload API
`POST /api/v1/bulk-upload-jobs/`

`GET /api/v1/bulk-upload-jobs/{id}/`

`POST /api/v1/bulk-upload-jobs/{id}/retry-failed/`

Bulk upload must expose total, processed, completed, failed, and error list.

## 9. Audit API
`POST /api/v1/documents/{id}/audit/`

`GET /api/v1/audit-runs/{id}/`

Audit must be idempotent and avoid double-triggering.

## 10. Findings API
`GET /api/v1/findings/`

`PATCH /api/v1/findings/{id}/`

Finding statuses:
- open.
- accepted.
- rejected.
- resolved.
- escalated.

## 11. Reports API
`POST /api/v1/reports/`

`GET /api/v1/reports/{id}/download/`

Downloads must be protected and logged.

## 12. ERP Integration Patterns
### Pull
Tadgeeg pulls invoices, ledgers, vendors, customers, and payments periodically.

### Push
ERP pushes documents to Tadgeeg using API and idempotency keys.

### Webhook
Tadgeeg sends events:
- document.uploaded.
- audit.completed.
- finding.created.
- finding.high_risk.
- report.ready.
- zatca.validation_failed.

## 13. ERP Mapping
| Tadgeeg | SAP | Oracle | Odoo |
|---|---|---|---|
| Invoice | Billing/Vendor Invoice | AR/AP Invoice | account.move |
| Journal Entry | Accounting Document | GL Journal | account.move |
| Purchase Order | Purchase Order | Procurement PO | purchase.order |
| Sales Order | Sales Order | Order Management | sale.order |
| Payment | Payment Document | Payment | account.payment |
| Vendor/Customer | Business Partner | Supplier/Customer | res.partner |

## 14. Idempotency
All external writes must support:
`Idempotency-Key: unique-client-key`

Rules:
- Same key + same payload returns same result.
- Same key + different payload returns conflict.
- Prevent duplicate documents and audit runs.

## 15. OpenAPI Requirement
Maintain:
`openapi/tadgeeg_api_v1.yaml`

Must include schemas, examples, auth, pagination, errors, webhooks, uploads.

## 16. Integration Tests
- Upload invoice via API.
- Retry with same idempotency key.
- Push 5,000 invoices.
- Receive audit webhook.
- Download report with permission.
- Block cross-tenant API access.
- Simulate ERP timeout.
- Verify integration logs.
