# TADGEEG-FIN-AUDIT-9A — Financial Statements Review (IAS 1)

> **Phase type:** New advisory module (backend service + API + polished frontend). **No new model, no migration.**
> **Date:** 2026-07-25 · **Builds on:** `216949a` (8E/8F). Part of the Phase-8/9 frontend-completion roadmap.
> **Honored:** additive · deterministic (no AI) · organization-scoped · auditor-only · **no ledger writes** · **no formal opinion** (advisory only).

---

## 1. What was implemented
A **Financial Statements Review** that derives a Balance Sheet and Income Statement from a staged Trial Balance (1A/1B) using the existing `AccountMapping` classification taxonomy, then computes key ratios, a year-over-year comparison, and deterministic classification-anomaly flags. This closes the largest genuine gap identified in the roadmap ("مراجعة القوائم المالية").

## 2. Reuse (no duplication)
| Reused | From | Why |
|---|---|---|
| `TrialBalanceImport` / `TrialBalanceRow` | 1A | source data |
| `AccountMapping.Category` taxonomy (17 categories) | 1B | maps accounts → IAS 1 lines — **no new classification** |
| `is_auditor` | 6C | one definition of auditor+ for the page |
| ISA visual style (`audit/isa/_style.html`) | 8E/8F | consistent polished design |

## 3. Design decision — derive, don't persist
Financial statements are **always re-derived on the fly** from the current trial balance. This matches how audit FS review actually works (they must reflect the latest TB), keeps the phase **additive with no migration**, and avoids stale snapshots. Persistence/snapshotting is noted as a future enhancement.

## 4. Backend implementation (`services/financial_statements.py`)
- `build_financial_statements(engagement, tb_import=None)` — the entry point. Uses the latest completed TB unless one is given.
- **Aggregation:** joins TB rows to `AccountMapping` by `account_code`, sums net-debit per category (`closing_debit − closing_credit`, falling back to `closing_balance`), and presents credit-normal categories (liabilities, equity, revenue) as positive.
- **Balance Sheet:** assets / liabilities / equity lines + totals, profit for the period, and the accounting-equation check (`Assets = Liabilities + Equity incl. profit`).
- **Income Statement:** revenue, cost of sales, gross profit, expenses, other income, net profit.
- **Ratios:** current ratio, debt-to-equity, gross margin, net margin, return on equity (guarded against divide-by-zero → `None`).
- **Year-over-year:** per-category deltas + %Δ vs the prior TB import (when a second import exists).
- **Anomaly flags (deterministic, advisory):** equation imbalance · negative equity · sign anomalies (category balance on the abnormal side) · unmapped accounts (excluded from the statements).

## 5. API (additive, org-scoped, auditor+)
`GET /api/v1/audit/engagements/<uuid>/financial-statements/` — returns the full derived payload (Decimals serialised as strings). `400` if no trial balance; `404` for a foreign-org engagement.

## 6. Frontend
`/audit/financial-statements/` (sidebar entry + engagement workspace deep link). Engagement picker; then: classification-flag panel, a five-tile ratio row, side-by-side **Balance Sheet** and **Income Statement** tables (grouped headers, totals, tabular figures), and a **year-over-year** table with coloured deltas. Reuses the 8E/8F professional style (gradient hero, refined cards); RTL-aware, responsive, advisory banner. Auditor-only.

## 7. Security
Organization-scoped everywhere; a foreign engagement is `404` (API) or silently unresolved (page). Auditor-only (`IsSeniorAuditorOrAbove` / `is_auditor`); juniors get `403`. Advisory only — nothing persisted, no ledger writes, no opinion (asserted).

## 8. Tests
`apps/audit/tests/test_financial_statements.py` (16): no-TB raises, balanced statements, ratios, equation-imbalance / negative-equity / sign-anomaly / unmapped-accounts flags, year-over-year (and none with a single import), API returns/400/junior-403/cross-org-404, and no-ledger-writes. `apps/frontend/tests/test_financial_statements_page.py` (7): login required, junior 403, renders BS/IS/ratios, empty + no-engagement states, cross-org ignored.

## 9. Intentionally NOT implemented
Persisted FS snapshots · current/non-current split beyond the taxonomy approximation · Cash-Flow Statement and Statement of Changes in Equity (need movement data, not just closing balances) · Notes to the financial statements · direct FS file import (FS are derived from the TB).

## 10. Recommended next phase
**9C External Confirmations (ISA 505)** or **9B Management Letter (ISA 265)** — the remaining real gaps; plus the deferred **ISA 300/330/240** list-builder UIs to finish the ISA assessment suite.
