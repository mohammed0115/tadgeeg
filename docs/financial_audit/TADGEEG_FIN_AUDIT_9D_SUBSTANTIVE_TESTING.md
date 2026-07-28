# TADGEEG-FIN-AUDIT-9D — Substantive Testing (ISA 501 / Fixed Assets / Payroll)

> **Phase type:** New module — model + service + API + auditor frontend. One migration (`0030`).
> **Date:** 2026-07-27 · **Builds on:** `5f70887` (9B).
> **Honored:** additive · organization-scoped · auditor-only · **no ledger writes** · no AI (deterministic re-performance) · **not an audit opinion** (advisory working paper).

---

## 1. What was implemented
A uniform **substantive-test register** covering three areas under one model: **Inventory (ISA 501)**, **Fixed assets**, and **Payroll**. For each item the auditor records the entity's **book value** and an independently derived **tested value** — either typed directly or **recomputed deterministically** by the system — and the platform flags a **variance** outside tolerance. Nothing is posted to the ledger; a variance is surfaced for the auditor's judgement, never auto-corrected.

## 2. Model — `SubstantiveTestItem`
Engagement + organization scoped. Key fields: `reference` (per-org `SUB-00001`), `area` (inventory / fixed_assets / payroll / other), `item_reference` (SKU / asset tag / employee id), `description`, `book_value`, `tested_value` (nullable until tested), `tolerance`, `quantity_book` / `quantity_counted` (inventory count sheets), `inputs` (JSON — area-specific recompute parameters), `notes`, `status` (open / matched / variance / cancelled), `created_by`. Properties: `variance` = `book − tested` (None until tested) and `is_within_tolerance` = `|variance| ≤ tolerance`. `clean()` enforces `organization == engagement.organization`. Unique `reference` per organization.

## 3. Service — `services/substantive_testing.py`
Deterministic re-performance helpers (ISA 500/501):
- `straight_line_nbv(cost, salvage, useful_life_years, elapsed_years)` → `{annual_depreciation, accumulated_depreciation, net_book_value}`; accumulated depreciation is **capped at the depreciable base** so NBV floors at salvage.
- `net_pay(gross, deductions)` = gross − deductions.
- `inventory_value(quantity, unit_cost)` = quantity × unit cost.

Workflow: `create_item` (derives `tested_value` from area-specific `inputs` when present, then classifies), `record_tested` (records the independently tested value and classifies matched/variance by tolerance), `cancel`, `area_summary` (per-area counts + net variance for the dashboard). `_classify` sets **matched** when within tolerance, else **variance**. `create_item` numbers references with an integrity-safe retry loop.

## 4. API (additive, org-scoped, auditor+)
- `GET/POST /api/v1/audit/substantive-items/` (list — filter by `engagement` / `area`; create with optional `inputs` recompute).
- `GET/POST /api/v1/audit/substantive-items/<id>/` (detail; `action=record` records tested value, `action=cancel`).
- `GET /api/v1/audit/engagements/<id>/substantive-summary/` (per-area counts + net variance).

Junior → 403; cross-org → 404.

## 5. Frontend
`/audit/substantive-testing/` (engagement-scoped, sidebar entry "Substantive Testing"). **Area tabs** (Inventory / Fixed assets / Payroll / Other) switch the register and the create form. The create form shows an **area-specific recompute box**: straight-line NBV inputs for fixed assets, gross/deductions for payroll, counted-qty × unit-cost for inventory — when filled, the tested value is recomputed server-side. Per-area KPIs (items / matched / variances / total), a register table with book / tested / **variance** (colour-coded) / status, and an inline **"Test"** control to record a tested value per row. Reuses the module style; auditor-only. A **Summary JSON** button hits the summary endpoint.

## 6. Security
Organization-scoped everywhere; foreign engagement/item → 404. Auditor-only (`IsSeniorAuditorOrAbove` / `is_auditor`); juniors 403. Advisory re-performance — **no ledger writes** (asserted in tests against `apps.ledger` `Account`/`JournalEntry`/`JournalLine` counts); no AI, no formal opinion.

## 7. Tests
`apps/audit/tests/test_substantive_testing.py`: recompute helpers (straight-line + cap + zero-life rejected, net pay, inventory), service (numbering/scoping, recompute-on-create for all three areas, tolerance classification, cancel blocks testing, area summary), API (create/list/detail, record, summary, junior 403, cross-org 404), and no-ledger-writes.
`apps/frontend/tests/test_substantive_page.py`: login required, junior 403, no-engagement state, create-with-recompute (inventory + fixed assets), record-tested from UI, register render (tabs + summary link + reference), area-tab filtering, cross-org ignored.

## 8. Intentionally NOT implemented
Bulk import of count sheets / asset registers (items are entered individually or via API) · declining-balance / units-of-production depreciation (straight-line only) · payroll statutory tables (deductions are provided, not derived) · sampling selection (reuses ISA 530 sampling separately) · PDF export. These are deterministic extensions for a later pass.

## 9. Recommended next phase
The deferred **ISA 300/330/240** list-builder UIs (planning strategy, risk responses, fraud factors). Optionally: bulk CSV import of inventory count sheets / fixed-asset registers into the substantive register, and linking flagged variances to 6A evidence requests.

---

## 10. Follow-up (2026-07-28) — Bulk CSV/XLSX import
Added `import_items(engagement, actor, area, file_obj, filename)` to `services/substantive_testing.py`: auditors upload the count sheet / asset register / payroll run their client already has, instead of keying rows one at a time.

- **Flexible headers.** Columns are matched by a normalised alias map (`_COL_ALIASES`) — e.g. `sku` / `asset_tag` / `employee_id` → `item_reference`; `carrying_amount` / `net_book_value` → `book_value`; area recompute columns (`cost`/`salvage`/`useful_life`/`age`, `gross`/`deductions`, `counted_qty`/`unit_price`).
- **Tolerant amounts.** `_parse_amount` strips thousands separators and currency symbols ($, £, €, SAR/ر.س); blank → skipped.
- **Reuses `create_item`** per row, so recompute + matched/variance classification apply exactly as for manual entry. Malformed rows are skipped and reported (`{"created", "skipped", "errors"}`), never partially corrupting the register. Capped at 5 000 rows.
- **Frontend.** An "Import count sheet / register" card (CSV/XLSX, `multipart/form-data`) on `/audit/substantive-testing/`, area-aware hint text, wired via the `action=import` branch.
- **Tests (+10).** Service: inventory/fixed-asset/payroll recompute-on-import, tolerant amounts + currency, blank-skip + missing-book report, unsupported type rejected, XLSX path. Frontend: import card renders, CSV upload creates items, missing-file guard.

No new model/migration; no ledger writes.
