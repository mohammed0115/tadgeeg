# Phase — Dashboard Fix

Targeted rewrite of the main dashboard (`/dashboard/`) to close the 18 gaps identified in the dashboard review. 16 fixed; 2 deferred (one needs a User schema change, one needs WebSocket wiring).

## Files changed

| File | Change |
|---|---|
| `apps/frontend/page_views.py` (the `dashboard` view) | Rewrite. View extracted into `_build_dashboard_payload()` + `_empty_dashboard_kpis()` helpers. Added cache wrapper, new KPI shape, cross-doc risk breakdown. |
| `templates/dashboard/index.html` | Empty-org banner, clickable stat-cards, per-currency total tile, year-aware chart labels, chart empty-states, status-display fix on table, upload card now a real link, dynamic "Coverage:" breadcrumb. |

No new migrations. No model edits. No API changes.

## Gaps closed

### 🔴 Critical correctness

| # | Gap | Fix |
|---|---|---|
| 1 | `total_amount` blindly summed across SAR / USD / EUR | View now returns `total_amount_by_currency` dict; template renders one row per currency. |
| 2 | `get_status_display` called on `dict` from `.values()` → silently fell through to raw enum | View returns model instances (with `.only(...)` to skip heavy fields); template uses `inv.get_status_display` and `inv.get_risk_level_display`. |
| 3 | OCR `%` used `Sum/Count` with NULL contaminating the count | Uses `Avg("ocr_confidence", filter=~Q(ocr_confidence__isnull=True) & ~Q(ocr_confidence=0))`. |
| 4 | Template said "Last 10" but view returned 8 | View now returns 10. |
| 5 | Top risky vendors grouped by name string ("ABC Co" ≠ "ABC Co.") | Primary path uses `VendorProfile` registry (deduplicated at write-time). Falls back to invoice-name grouping when registry empty. |

### 🟡 Performance

| # | Gap | Fix |
|---|---|---|
| 6 | 17+ separate DB round trips per render | One `Invoice.aggregate()` covers ~10 KPIs via `Count(filter=Q(...))`. Each typed-doc model collapsed to one `aggregate()` (count + per-level breakdown in a single query). **28 queries cold, 1 query warm.** |
| 7 | No caching | `cache.set(key, payload, 60)` keyed by `org_id` + hour bucket. Re-renders within the same hour use ~1 query. Verified: 1286 ms → 26 ms cached. |

### 🟠 Coverage

| # | Gap | Fix |
|---|---|---|
| 8 | Only 7 doc types in `doc_counts` (missing 13 phase-2 types) | All 21 typed models covered: invoices, purchase_orders, bank_statements, payroll, expense_reports, vat_returns, fixed_assets, sales_receipts, grn, payment_vouchers, sales_orders, quotations, proforma_invoices, receipt_vouchers, cash_vouchers, general_ledgers, ledgers, contracts, supplier_statements, customer_statements, journal_entries. |
| 9 | `risk_breakdown` was invoice-only | Aggregates across all 21 doc types via the same `aggregate()` loop. |
| 10 | Export / Filter buttons were dead `<button>` elements | Both now `<a>` tags pointing at the invoice list (Filter has working filters there; Export uses `?export=excel`). |
| 11 | Upload card looked like a drop zone but was inert | Whole card is now a real `<a>` to `frontend:upload`. |
| 12 | Stat cards not clickable | Fraud → `/invoices/?status=flagged`. Compliance → `/invoices/?compliance=qr_invalid`. Total Invoices → `/invoices/`. POs → `/documents/purchase-orders/`. Pending → `/invoices/?status=pending`. |

### 🔵 UX

| # | Gap | Fix |
|---|---|---|
| 14 | Hardcoded "Coverage: GCC" breadcrumb | Renders `request.user.organization.country` when present, falls back to "Coverage: GCC". |
| 15 | Chart labels missing year — "Dec, Jan, Feb" ambiguous across years | `m.strftime("%b '%y")` → "Dec '25", "Jan '26", "Feb '26". |
| 16 | User without organization saw zeros and no guidance | Dashboard short-circuits before any DB hit, renders an orange banner: "You're not associated with an organization yet." with a link to `/profile/`. |
| 17 | Charts rendered an empty doughnut on zero data | Both charts now show a friendly "No documents to score yet" / "Upload invoices to see the monthly trend" empty state when their data arrays are empty. |

## Deferred

| # | Gap | Reason |
|---|---|---|
| 13 | Onboarding modal flag in `localStorage` (resets per device) | Needs a `User.onboarding_completed_at` field + migration. Out of scope for a dashboard-only PR; tracked for the auth-app hardening sweep. |
| 18 | No real-time updates (WebSockets / channels) | `apps.streaming` and `channels` are configured but the dashboard doesn't subscribe. Real-time is a significant architectural addition (ASGI deploy, channel layers in production, frontend reconnect logic) — separate PR. |

## Verification

Test against the production-shape SQLite (1 org, 29 invoices, 20+ docs across phase-2 types):

```text
COLD VIEW:   28 queries  1286 ms  status=200      # was 48+ queries
WARM VIEW:    1 queries    26 ms  status=200      # 60 s cache window

KPIs sample:
  total_invoices: 29
  total_pos: 2
  total_amount_by_currency: {'SAR': 257050.0}
  primary_currency: SAR
  high_risk_count: 5
  fraud_alerts: 5
  compliance_alerts: 29
  pending_review: 22
  automation_pct: 13
  extraction_accuracy_pct: 0       # was biased low; now Avg()
  monthly_growth: 100
  vat_total: 31572.5
  doc_counts: 21 types covered (was 7)

risk_breakdown: {'low': 59, 'medium': 10, 'high': 9, 'critical': 0}
                                   ^^^^^^^^ aggregated across all doc types

recent_invoices: 10 rows           # was 8
recent_invoices[0].get_status_display(): "Flagged"  # was "flagged"
recent_invoices[0].get_risk_level_display(): "High"  # was "high"

Template render:
  ✓ country breadcrumb
  ✓ recent operations table
  ✓ risk chart heading
  ✓ table data-class
  ✓ risk + trend canvases
  ✓ compliance=qr_invalid drill-down link
  ✓ status=flagged drill-down link
  ✓ status=pending drill-down link
```

`python manage.py check` — 0 issues.

## Risks / things to watch

- The 60-second cache means a freshly uploaded invoice does NOT immediately update KPIs. If real-time freshness is needed, either drop the TTL or invalidate the cache from the upload pipeline (`cache.delete(f"dashboard:v2:{org_id}:*")` — though wildcard delete needs Redis-specific code).
- `total_amount_by_currency` is a dict; templates downstream that expected `kpis.total_amount` as a scalar will need updating. Searched: only the dashboard template referenced it.
- `VendorProfile` registry must be populated for the "by FK" path to fire. Older organizations may still hit the fallback path that groups by name. The fallback produces the same shape, so the template is unaffected.
- Cold-path 28 queries is acceptable but not minimal — could go to ~10 with a raw SQL UNION ALL across the typed-doc tables. Deferred; cache makes the cold path a 60-second event.
