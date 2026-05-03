# Tadgeeg API Reference

REST + JSON over HTTPS. All endpoints live under `/api/v1/`.

  • **Auth.** JWT Bearer token; obtain via `POST /api/v1/auth/login/` or
    `POST /api/v1/mobile/auth/login/`. The token carries the user's
    organisation; every endpoint scopes its data by that organisation
    automatically.
  • **Tenancy.** A user with no organisation can never see another tenant's
    data — querysets default to `.none()` rather than `.all()`.
  • **Idempotency.** Mutating mobile endpoints honour an
    `Idempotency-Key` request header so flaky networks can retry safely.
  • **Schema.** Live OpenAPI 3 schema at
    `GET /api/schema/` · interactive docs at `GET /api/docs/`.

The eight categories below cover every workflow an external ERP needs
to integrate against. Each section lists the endpoints, their request
body, success response, and the failure cases that matter for
reconciliation downstream.

---

## 1. Document upload

POST a financial document (invoice, PO, bank statement, payroll, etc.)
and Tadgeeg routes it through OCR + AI extraction + the audit pipeline.

### `POST /auditor/upload/`

Multipart form. The single user-facing entry point.

| field                | type   | required | notes |
|----------------------|--------|----------|-------|
| `file`               | file   | yes      | PDF · JPG/PNG · TIFF · ZIP · XLSX/XLS · CSV/TSV · JSON/JSONL |
| `selected_doc_type`  | string | yes      | One of: `invoice`, `purchase_invoice`, `sales_invoice`, `sales_order`, `quotation`, `proforma_invoice`, `sales_receipt`, `customer_statement`, `purchase_order`, `goods_receipt_note`, `supplier_statement`, `bank_statement`, `payment_voucher`, `receipt_voucher`, `cash_voucher`, `journal_entry`, `general_ledger`, `ledger`, `vat_return`, `contract`, `payroll`, `expense_report`, `fixed_asset` |
| `doc_language`       | string | optional | `auto` / `ar` / `en` / `ar-en` |

**Response — 302** to the typed result page (`/invoices/<uuid>/`,
`/documents/<doc_type>/<uuid>/`, …). When the request carries
`X-Requested-With: XMLHttpRequest` the redirect URL is returned in
the response body instead.

**Errors.**
- `400` — unsupported extension, file > 50 MB, unknown `selected_doc_type`.
- `401` — not authenticated.

### `POST /api/v1/mobile/captures/`

Multi-photo capture from the mobile app. Server merges N photos into one
PDF and returns the relative URL.

```http
POST /api/v1/mobile/captures/
Content-Type: multipart/form-data

photos[]=<photo1.png>
photos[]=<photo2.png>
```

```json
{
  "ok": true,
  "pdf_url": "/media/mobile_captures/2026/05/capture_<uuid>.pdf",
  "filename": "capture_<uuid>.pdf",
  "page_count": 2,
  "size_bytes": 184223,
  "photo_count": 2
}
```

---

## 2. Run audit / re-validate

Audit runs automatically on every upload. To re-run on demand:

### `POST /invoices/<uuid:pk>/revalidate/`

Re-run all 18 built-in rules + every published custom-DSL rule against
an existing invoice.

**Response — 200**
```json
{
  "validation_score": 62.5,
  "rules_passed": 11,
  "rules_failed": 7,
  "failed_rule_codes": ["R001","R002","R005",...],
  "risk_level": "high",
  "risk_score": 75
}
```

### `POST /documents/<doc_type>/<uuid:pk>/run-audit/`

Re-run the audit on any typed document (PO, GRN, payroll, …).

### Custom rule builder (DSL)

```
GET    /api/v1/audit/rule-builder/                  list rules in your org
POST   /api/v1/audit/rule-builder/                  create draft (admin/CAO)
GET    /api/v1/audit/rule-builder/<pk>/             detail
PUT    /api/v1/audit/rule-builder/<pk>/             update draft
DELETE /api/v1/audit/rule-builder/<pk>/             delete draft
POST   /api/v1/audit/rule-builder/<pk>/test/        sandbox-run on last 100 invoices
POST   /api/v1/audit/rule-builder/<pk>/publish/     promote to active (admin/CAO)
POST   /api/v1/audit/rule-builder/<pk>/archive/     archive
GET    /api/v1/audit/rule-builder/dsl-schema/       fields + operators (UI helper)
```

DSL example for `POST /api/v1/audit/rule-builder/`:
```json
{
  "name": "Block large no-VAT invoices",
  "severity": "high",
  "condition_type": "dsl",
  "expression_dsl": {
    "when": {
      "all": [
        {"field": "total_amount", "op": ">", "value": 100000},
        {"field": "vendor_vat_number", "op": "is_empty"}
      ]
    },
    "then": {
      "action": "flag",
      "severity": "high",
      "message": "Large invoice with missing vendor VAT"
    }
  }
}
```

---

## 3. Retrieve audit results

### `GET /api/v1/invoices/<uuid:pk>/`

Full invoice payload — extracted fields, computed scores, line items,
QR-code metadata, validation rules. The `validation` nested object
carries every rule outcome.

### `GET /api/v1/audit/cases/`

Paginated list of `AuditCase` rows (every CRITICAL/HIGH rule failure
gets one). Filterable by `?status=open|in_progress|resolved`,
`?priority=critical|high|medium|low`.

```json
{
  "results": [
    {
      "id": "ba32358e-…",
      "case_number": "AC-2026-0103",
      "title": "[R001] Duplicate Invoice Detection",
      "description": "Near-certain duplicate detected (score=1.00) …",
      "priority": "critical",
      "status": "open",
      "ai_risk_score": 100,
      "invoice_id": "9e8b24d7-…",
      "created_at": "2026-05-04T12:11:08Z"
    }
  ],
  "count": 142
}
```

### `GET /api/v1/audit/cases/<pk>/`
### `POST /api/v1/audit/cases/<pk>/status/`
### `POST /api/v1/audit/cases/<pk>/assign/`
### `GET  /api/v1/audit/cases/<pk>/comments/`
### `POST /api/v1/audit/cases/<pk>/comments/`

### `GET /audit/integrity/`

HTML view that walks every audit hash chain in your org and reports any
break (tampered row outside the application). The same data is at
`GET /api/v1/audit/integrity/` (machine-readable JSON).

---

## 4. Retrieve reports

### Aggregate reports

| URL                                       | Description |
|-------------------------------------------|-------------|
| `GET /api/v1/invoices/reports/risk/`      | Risk-ranked invoices with vendor + score |
| `GET /api/v1/invoices/reports/duplicates/`| Duplicate-detected invoices with original counterpart |
| `GET /api/v1/invoices/reports/vendors/`   | Per-vendor risk score, blocked status, spend |
| `GET /api/v1/invoices/reports/spend/`     | Total spend, VAT total, top vendors |
| `GET /invoices/reports/<kind>/`           | Same data, HTML rendering (`risk` / `duplicates` / `vendors` / `spend`) |

### Per-invoice reports

| URL                                      | Format |
|------------------------------------------|--------|
| `GET /invoices/<pk>/`                    | HTML invoice + audit trail |
| `GET /invoices/<pk>/pdf/`                | Single-invoice audit-report PDF |
| `GET /invoices/export.csv?status=…`      | Bulk CSV |
| `GET /invoices/export.xlsx?status=…`     | Bulk Excel (styled) |

### Engagement-planning reports

| URL                              | Description |
|----------------------------------|-------------|
| `GET /audit/tools/`              | ISA 320 materiality + ISA 530 sampling page |
| `GET /working-papers/`           | List of audit working papers |
| `POST /working-papers/<pk>/action/` | submit / review_approve / review_reject / partner_sign |

---

## 5. Vendor & customer master

### `GET /api/v1/invoices/vendors/`

```json
{
  "count": 23,
  "results": [
    {
      "id": "39f3996a-…",
      "vendor_name": "ARAMCO PROCUREMENT",
      "vendor_vat_number": "300000000000003",
      "vendor_cr_number": "1010001234",
      "first_seen": "2025-09-12",
      "last_seen": "2026-05-04",
      "invoice_count": 87,
      "total_amount": 2_415_300,
      "risk_score": 14.2,
      "risk_tier": "low",
      "is_approved": true,
      "is_blocked": false
    }
  ]
}
```

### `GET /api/v1/invoices/vendors/high-risk/`

Same shape, filtered to risk-tier `high|critical`.

### `GET /api/v1/invoices/vendors/<uuid:pk>/`

Vendor 360 view — invoice history, recent flags, contracts.

The customer master surface lives implicitly inside each invoice's
`customer_*` fields and is exposed via the report endpoints (above).
A first-class customer endpoint is on the roadmap; today's integrators
use `GET /api/v1/invoices/?customer_name=…` as a search proxy.

---

## 6. Analytics & risk

### `GET /api/v1/audit/dashboard/overview/`

Org-wide audit KPIs: total documents, average risk, error counts.

### `GET /audit/streaming/`  (HTML) / `GET /api/v1/audit/streaming/metrics/`

Continuous-auditing live ops: throughput, p95 latency, error rate,
recent anomaly hits.

### `GET /api/v1/streaming/anomalies/?severity=high`

Streaming `AnomalyHit` rows surfaced by the velocity / sudden-spike /
vendor-concentration detectors.

### `GET /api/v1/audit/big-four/`

Four-firm methodology comparison view (KPMG / Deloitte / PwC / EY).

### Risk-driven alert routing

```
GET    /api/v1/alerts/rules/                 list routing rules
POST   /api/v1/alerts/rules/                 create
PUT    /api/v1/alerts/rules/<pk>/            update
POST   /api/v1/alerts/rules/<pk>/test/       send synthetic alert
POST   /api/v1/alerts/events/<pk>/ack/       acknowledge
GET    /api/v1/alerts/events/                list dispatch attempts
```

`AlertRule` body:
```json
{
  "name": "Critical anomalies → audit team",
  "trigger_type": "anomaly",
  "trigger_detector": "velocity",
  "min_severity": "high",
  "channels": [
    {"type": "email",   "to": ["audit@example.com"]},
    {"type": "slack",   "webhook_url": "https://hooks.slack.com/..."},
    {"type": "webhook", "url": "https://erp.example.com/hook", "secret": "xxx"}
  ],
  "cooldown_minutes": 30
}
```

Webhook channel sends `X-Tadgeeg-Signature: sha256=<hex>` (HMAC-SHA256
over the raw body). Verify on receipt with
`apps.alerts.channels.webhook.verify_payload(secret, body, header)`.

---

## 7. Compliance — ZATCA Phase 2 (KSA)

End-to-end e-invoicing — UBL 2.1 XML, TLV-encoded QR, hash chain,
clearance + reporting. Real network calls run when `ZATCA_LIVE_MODE=True`;
otherwise every endpoint returns a recorded mock so integration testing
runs without a Fatoora portal account.

### EGS device lifecycle

```
GET    /api/v1/zatca/devices/                  list devices
POST   /api/v1/zatca/devices/                  onboard new (admin/CAO)
POST   /api/v1/zatca/devices/<pk>/renew/       refresh CSID
```

`POST` body:
```json
{
  "common_name": "1-Tadgeeg|2-EGS|3-001",
  "serial_number": "SN-001",
  "organization_identifier": "300000000000003",
  "branch_name": "Riyadh HQ",
  "environment": "sandbox",
  "otp": "123456"
}
```

### Submit invoices

```
POST   /api/v1/zatca/submissions/submit/
GET    /api/v1/zatca/submissions/?status=…&lang=en|ar
```

`submit/` body:
```json
{
  "invoice_id": "9e8b24d7-…",
  "mode": "clearance"
}
```

Response (mock or live):
```json
{
  "id": "<uuid>",
  "zatca_uuid": "<uuid>",
  "status": "cleared",
  "chain_position": 12,
  "previous_invoice_hash": "ab12…",
  "invoice_hash": "cd34…",
  "qr_tlv_base64": "AQhBY21lIEtTQQIPMzAwMDAwMDAwMDAwMDAzAxMjAyNi0wNS0wNFQxMjowMDow…",
  "warnings": [],
  "errors": [],
  "submitted_at": "…",
  "cleared_at": "…"
}
```

### Compliance dashboard

`GET /api/v1/zatca/dashboard/` — counters (cleared/reported/rejected/
warning/pending), 30-day clearance rate, top rejection causes with
EN/AR translations + fix hints, certificate-expiry warnings, 5-step
readiness checklist.

### VAT-return support

VAT validation is enforced inline by audit rules **R002** (VAT
calculation), **R009** (KSA rate validity 0/5/15%), **R014** (TRN
format — 15 digits, 3..3), **R017** (ZATCA QR presence), **R018**
(mandatory tax-invoice fields). VAT-return documents themselves
upload through `/auditor/upload/?selected_doc_type=vat_return` and
land in `/api/v1/documents/vat-returns/`.

---

## 7b. General Ledger (Phase 7.1)

The GL is the bridge from "audit verdict" to "books." Every invoice can
be auto-posted as a balanced double-entry journal; bank reconciliations
post the cash leg automatically. Posted entries are immutable (audit
hash chain); voiding generates a compensating mirror.

### Chart of accounts

```
GET  /api/v1/ledger/accounts/                    list (28 default seeded on first call)
POST /api/v1/ledger/accounts/                    create custom account (finance/admin)
```

### Journal entries

```
GET  /api/v1/ledger/entries/?status=posted       list
POST /api/v1/ledger/entries/                     manual post (finance/admin)
GET  /api/v1/ledger/entries/<uuid>/              detail with lines
POST /api/v1/ledger/entries/<uuid>/void/         compensating reversal
POST /api/v1/ledger/post-invoice/                push an invoice into the books
```

`POST /entries/` body:
```json
{
  "entry_date": "2026-05-04",
  "description": "Supplier accrual May 2026",
  "reference":   "INV-12345",
  "currency":    "SAR",
  "idempotency_key": "supplier-accrual-2026-05",
  "lines": [
    {"account_code": "5200", "debit":  "10000.00", "description": "Office rent"},
    {"account_code": "1250", "debit":   "1500.00", "description": "VAT input"},
    {"account_code": "2100", "credit": "11500.00", "description": "AP"}
  ]
}
```

`POST /post-invoice/` body:
```json
{"invoice_id": "<uuid>", "direction": "purchase"}   // or "sale"
```

### Reports

```
GET /api/v1/ledger/trial-balance/?as_of=2026-05-04    org-wide debit/credit by account
GET /api/v1/ledger/general-ledger/<code>/?from=…&to=… per-account drilldown with running balance
```

### Multi-currency

```
GET  /api/v1/ledger/exchange-rates/                   list latest 200
POST /api/v1/ledger/exchange-rates/                   { from_currency, to_currency, rate, rate_date }
```

`get_or_create_fx_rate` walks **exact match → most-recent prior → identity
(when from == to) → fallback rate** so posting never blocks on a missing
rate. Each journal line carries both the source-currency amount (`debit`,
`credit`) and the converted reporting-currency amount (`base_debit`,
`base_credit`) for IFRS consolidation.

### Auto-posting from other apps

| Source                      | When                        | Endpoint called           |
|-----------------------------|-----------------------------|---------------------------|
| Invoice approval            | After admin approve         | `post_invoice_to_gl(...)` |
| Bank reconciliation confirm | After auditor accept        | `post_bank_payment_to_gl` |
| ZATCA cleared B2B           | (planned) on cleared receipt| `post_invoice_to_gl(sale)`|

---

## 8. ERP integration

Tadgeeg exposes three integration surfaces an ERP can wire to:

### 8.1 Outbound webhooks (Tadgeeg → ERP)

Configure under `/api/v1/alerts/rules/` with channel `type: "webhook"`.
Every audit event you opt-in to is HMAC-signed and POSTed to your URL.

```http
POST <your-url>
Content-Type: application/json
X-Tadgeeg-Signature: sha256=<hex>

{"event":"audit.alert","title":"…","severity":"high","data":{…},"ts":1714824000}
```

Recommended subscriptions:
- `audit.anomaly_detected` — streaming hits.
- `invoice.flagged` — every flagged invoice.
- `zatca.cleared` / `zatca.rejected`.
- `reconciliation.confirmed` — bank-to-invoice match.

### 8.2 Inbound REST (ERP → Tadgeeg)

The ERP submits documents, fetches results, and confirms reconciliation
via:

| Use case                       | Endpoint |
|--------------------------------|----------|
| Push a sales invoice for audit | `POST /api/v1/invoices/upload/` |
| Push a purchase invoice        | `POST /auditor/upload/?selected_doc_type=purchase_invoice` |
| Push a typed document          | `POST /api/v1/documents/typed-upload/` |
| Pull audit case backlog        | `GET  /api/v1/audit/cases/?status=open` |
| Pull invoice result            | `GET  /api/v1/invoices/<id>/` |
| Mark an invoice approved       | `POST /api/v1/invoices/<id>/approve/` |
| Bulk approve / reject / flag   | `POST /api/v1/invoices/bulk/` |
| Submit invoice to ZATCA        | `POST /api/v1/zatca/submissions/submit/` |

### 8.3 Bank-statement integration

Two paths:

```
POST /api/v1/banking/connections/                       open a live link to one of
                                                        Al Rajhi · SNB · Riyad · SAB · BSF
POST /api/v1/banking/connections/<pk>/sync/             pull accounts + transactions
POST /api/v1/banking/accounts/<pk>/statement/           fallback — upload CSV/XLSX/PDF
GET  /api/v1/banking/transactions/                      paginated list
POST /api/v1/banking/reconciliations/run/               score (transaction × invoice) pairs
GET  /api/v1/banking/reconciliations/                   queue with score + reasons
POST /api/v1/banking/reconciliations/<pk>/action/       confirm | reject
```

Reconciliation scoring uses four weighted signals (amount ±0.5%, date
±3d, reference contains, vendor fuzzy) to produce a 0–100 score with
high (≥80) / medium (≥60) / low bands. The ERP can pull confirmed
matches via `?status=confirmed` and post them back to its own GL.

### 8.4 OpenAPI 3 contract

All endpoints are described by the live OpenAPI 3 schema:

```
GET /api/schema/                  YAML / JSON contract
GET /api/docs/                    Swagger UI
GET /api/redoc/                   ReDoc renderer
```

Recommended ERP integration kit: code-generate a typed client from
`/api/schema/` using `openapi-generator` for the language of your
choice (Python, TS, C#, Java are all first-class targets). Subsequent
breaking changes go through versioned URLs (`/api/v2/…`) so an existing
generated client never breaks silently.

---

## Auth + tenancy summary

```
POST /api/v1/auth/login/            { email, password }      → access + refresh
POST /api/v1/auth/refresh/          { refresh }              → new access (rotates refresh)
POST /api/v1/mobile/auth/login/     { email, password,       → access + refresh + device
                                      device_id, platform }
POST /api/v1/mobile/auth/logout/    { refresh, device_id }   → blacklist + deactivate device
```

Every authenticated call inherits the user's `organization_id` from
the JWT; requests on resources owned by a different tenant return
**404**, never **403** (information-disclosure protection).

## Rate limiting

The platform uses Django's RatePlatformLimiter middleware. Default
quotas (overridable per integration in admin):

| Scope                 | Quota          |
|-----------------------|----------------|
| Anonymous             | 60 req/min     |
| Authenticated user    | 600 req/min    |
| ERP service account   | 6 000 req/min  |
| Webhook delivery (out)| 60 / minute / endpoint |

Rate-limited responses carry `Retry-After: <seconds>` and the standard
`X-RateLimit-*` triplet of headers.

## Error envelope

All 4xx / 5xx responses share the same shape:

```json
{
  "error": "human-readable message (English)",
  "error_ar": "نفس الرسالة بالعربية (إن أمكن)",
  "code": "INVOICE_NOT_FOUND",
  "details": {…optional…}
}
```

`code` values are stable; `error` text may be re-translated.

---

## SDKs / examples

```python
# Python — submit + poll
import requests

BASE = "https://app.tadgeeg.com/api/v1"
headers = {"Authorization": f"Bearer {jwt}"}

with open("invoice.pdf", "rb") as fh:
    r = requests.post(
        "https://app.tadgeeg.com/auditor/upload/",
        files={"file": fh},
        data={"selected_doc_type": "purchase_invoice"},
        headers=headers, allow_redirects=False,
    )
    invoice_id = r.headers["Location"].rsplit("/", 2)[1]

# poll until audit completes
while True:
    inv = requests.get(f"{BASE}/invoices/{invoice_id}/", headers=headers).json()
    if inv["status"] in ("approved", "flagged", "rejected"):
        break
print("validation_score:", inv["validation"]["validation_score"])
```

```ts
// TypeScript — webhook receiver (Express)
import { createHmac, timingSafeEqual } from "crypto";

app.post("/tadgeeg/webhook", express.raw({ type: "*/*" }), (req, res) => {
  const expected = "sha256=" + createHmac("sha256", SECRET)
    .update(req.body).digest("hex");
  const provided = req.headers["x-tadgeeg-signature"] as string ?? "";
  if (!timingSafeEqual(Buffer.from(expected), Buffer.from(provided))) {
    return res.status(401).send("bad sig");
  }
  const event = JSON.parse(req.body.toString());
  // forward into your ERP
  res.status(200).send("ok");
});
```
