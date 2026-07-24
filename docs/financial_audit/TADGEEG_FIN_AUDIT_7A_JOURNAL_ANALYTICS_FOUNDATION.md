# TADGEEG-FIN-AUDIT-7A — Advanced Audit Analytics Engine · Phase 1: Journal Analytics Foundation

> **Phase type:** Additive analytics foundation. One migration. No new apps, no duplicated rule logic, no phase rewritten.
> **Date:** 2026-07-24 · **Builds on:** `5d82754` (6D).
> **Honored:** purely additive · no breaking changes · no regression · no ledger writes · no AI · no machine learning · deterministic rules only · organization-scoped · permission-protected.

---

## 1. Architectural conflicts found

**Conflict 1 (major) — 6 of the 8 requested rules already exist in 2B.**
`services/general_ledger_risk_analysis.analyze_import` already implements Missing Description, Round Amount, Period-End Posting, Weekend Posting, Manual Journal and Sensitive Account, at **row** level, producing `GeneralLedgerRiskFinding` candidates that feed the 3B review → 4A SAD → 5A readiness pipeline. Re-implementing them would duplicate logic (explicitly forbidden). Only **High Value Journal** and **Dormant Account Activity** are genuinely new.

**Conflict 2 — `apps/analytics` already exists.** It holds `NLQueryHistory`, plus a Benford and an IAS-7 cash-flow service. Its domain (NL querying / statistics) is not engagement-scoped audit analytics. Note the pre-existing Benford service is *also* why 7A correctly excludes Benford.

**Conflict 3 — unit of analysis differs.** 2B analyses **rows**; 7A specifies **journals** ("affected journals", "total journals", "high-risk journals").

**Conflict 4 — "High Value" had no defined threshold**, but 3A's `gl_finding_materiality.resolve_materiality` already computes one.

**Conflict 5 — charts.** Chart.js is already vendored (`static/vendor/chart.umd.min.js`) and used via CDN on two pages; a new library would violate "reuse existing library only".

## 2. Decisions

1. **Build at journal level and import 2B's constants** rather than restating them. `MANUAL_KEYWORDS`, `SENSITIVE_CATEGORIES`, `WEEKEND_WEEKDAYS`, `PERIOD_END_WINDOW_DAYS`, `SIGNIFICANT_AMOUNT`, `_is_round`, `_row_date`, `_row_category`, `_severity_for` are all **imported from the 2B service**, so a threshold change stays in exactly one place. The rules are the same predicates re-expressed at journal granularity — not a second copy of the thresholds.
2. **7A lives in `apps/audit`** alongside 2B/3A/4A/5A/6A–6D, so organization/engagement scoping, permissions and test patterns are identical. `apps/analytics` was left untouched (different domain, and touching it would risk its Benford/NL services).
3. **High Value reuses 3A materiality** (`performance` → `overall`), falling back to a fixed threshold only when the engagement has no profile; the basis used is recorded in `run.metadata`.
4. **Strict separation from the finding pipeline.** 7A writes only its own four tables. It never creates/updates a `GeneralLedgerRiskFinding`, never accepts anything, never issues an opinion, never writes to `apps.ledger` — asserted by tests.
5. **Reuse the bundled Chart.js**, loaded local-first with a CDN fallback and a `typeof Chart === 'undefined'` guard so pages degrade gracefully.

### Explicitly REUSED (and why)
| Reused | From | Why |
|---|---|---|
| `MANUAL_KEYWORDS`, `SENSITIVE_CATEGORIES`, `WEEKEND_WEEKDAYS`, `PERIOD_END_WINDOW_DAYS`, `SIGNIFICANT_AMOUNT` | 2B | one source of truth for thresholds |
| `_is_round`, `_row_date`, `_row_category`, `_severity_for` | 2B | identical predicates/scoring bands, no re-derivation |
| `resolve_materiality` | 3A | audit-correct high-value threshold |
| `GeneralLedgerRow` / `GeneralLedgerImport` / `AuditEngagement` | 1A/2A | analytics read staged data; no new ingestion |
| `lc.is_auditor` | 6C | one definition of "auditor+" for pages |
| `Chart.js` (vendored) | existing static | "reuse existing library only" |

## 3. Files created/changed
**Created:** `apps/audit/journal_analytics_models.py` · `apps/audit/services/journal_analytics.py` · `apps/audit/views_journal_analytics.py` · `apps/audit/migrations/0027_…` · `apps/audit/tests/test_journal_analytics.py` · `apps/frontend/journal_analytics_views.py` · `apps/frontend/tests/test_journal_analytics_pages.py` · `templates/audit/analytics/{_shared,_nav,dashboard,runs,run_detail,rules}.html` · this document.
**Changed (additive only):** `apps/audit/models.py` (re-export) · `apps/audit/urls.py` · `apps/frontend/urls.py` · `templates/layouts/dashboard_base.html` (sidebar entry).

## 4. Migration
**0027** — creates `JournalAnalyticsRule`, `JournalAnalyticsRun`, `JournalAnalyticsResult`, `JournalAnalyticsSummary` (+ indexes and a per-org unique rule constraint). No existing model altered; `makemigrations --check` clean.

## 5. Backend implementation
- **Models.** `Run` (organization + engagement + GL import; status, started/completed, `execution_ms`, `rules_executed`, `rows_analyzed`, `journals_analyzed`, `findings_count`, `warnings`, `errors`, `metadata`), `Result` (rule id/name, severity, score, journal, account, entered_by, description, recommendation, amount, affected rows, `execution_ms`, evidence), `Rule` (per-org enable/disable + weight), `Summary` (totals, risk buckets, by-rule, by-severity, top accounts, top users).
- **Engine.** Rows are grouped into `Journal` objects (blank journal numbers become synthetic `ROW-n`). Each rule is an independent function receiving `(journal, ctx)`; a rule that raises is captured into `run.errors` and the run continues. Disabled rules are skipped, unknown rule codes produce a warning.
- **Rules (all deterministic).** `JA-ROUND`, `JA-WEEKEND`, `JA-PERIODEND`, `JA-MANUAL`, `JA-DESC`, `JA-HIGHVALUE`, `JA-DORMANT` (account reactivated after ≥180 idle days within the import), `JA-SENSITIVE`. Multiple rules may fire on the same journal (asserted).
- **Dashboard/report services.** `dashboard()` returns totals, risk buckets, top rules/accounts/users and a 10-run execution history; `report()` returns summary, rule statistics, chart data, top findings and recommendations — **JSON only, no PDF**.
- Not implemented by design: Benford, sampling, ratio analysis (later phases).

## 6. Frontend implementation
| Page | URL | Surfaces |
|---|---|---|
| Analytics dashboard | `/audit/analytics/` | totals, analyzed, flagged, high/medium/low risk, **doughnut + bar charts**, top rules, top accounts, top users, execution history, engagement filter |
| Runs & history | `/audit/analytics/runs/` | start a run against a GL import; full execution history |
| Run results | `/audit/analytics/runs/<uuid>/` | per-result table (rule, journal, account, user, severity, score, amount, lines, description, recommendation), rule/severity/journal filters, by-rule chart, JSON-report link |
| Rules | `/audit/analytics/rules/` | rule registry with descriptions/recommendations and **enable/disable** |

Sidebar entry "Journal Analytics"; sub-navigation across all pages; an "Advisory only" banner on the dashboard and results pages. Reuses the existing `dashboard_base` layout and the 6B style partial: RTL + English, responsive (tables scroll, KPI/chart grids collapse), badges, breadcrumbs, empty states. No SPA.

## 7. API (all additive, organization-scoped, auditor+)
| Method | Path |
|---|---|
| GET / POST | `/api/v1/audit/journal-analytics/runs/` |
| GET | `/api/v1/audit/journal-analytics/runs/<uuid>/` |
| GET | `/api/v1/audit/journal-analytics/runs/<uuid>/results/` (filters: `rule`, `severity`, `journal`) |
| GET | `/api/v1/audit/journal-analytics/runs/<uuid>/report/` (JSON report) |
| GET | `/api/v1/audit/journal-analytics/dashboard/` |
| GET / POST | `/api/v1/audit/journal-analytics/rules/` (list / enable-disable) |

## 8. Security
- **Organization-scoped everywhere**; a run, import or engagement from another organization returns **404** (asserted for run detail, results, report, run creation and the run list).
- **Auditor-gated** (`IsSeniorAuditorOrAbove` on the API; `is_auditor` on pages) — a junior auditor gets **403** on every endpoint and page (asserted).
- **Cross-tenant execution blocked** at the service boundary (`ValidationError`) when an import's engagement and organization disagree.
- **No ledger writes, no findings created, no automatic acceptance, no opinion** — asserted by a dedicated isolation test that also confirms staged GL rows are not modified.
- Every payload carries `advisory_only: true`, and the report states the results are not audit findings.

## 9. Tests
`apps/audit/tests/test_journal_analytics.py` (46): rule registry (seeding idempotent, disable/re-enable, unknown rule rejected, per-org isolation); **one positive and, where meaningful, one negative test per rule** (round, weekend, period-end, manual, missing description, high value via materiality + fallback, dormant, sensitive) plus multi-rule triggering; engine (counters/status, journal grouping, synthetic journal numbers, determinism, empty import, no-rules warning, unknown-rule warning, cross-tenant rejection, full result contract); summary (buckets, top accounts/users); dashboard (empty, populated, org-scoped) and report shape; API (create/detail/results/report/dashboard/rules/toggle, junior 403, cross-org 404 ×3); isolation (no findings, no ledger, GL rows unmodified, results scoped).

`apps/frontend/tests/test_journal_analytics_pages.py` (18): login required, junior 403 and auditor render across all pages; dashboard empty state, populated state with charts, cross-org exclusion; runs page listing/execute/redirect/invalid import/history; run detail results, filters, empty filter state, cross-org 404; rules listing, disable/enable, unknown-rule error; navigation.

## 10. Risks / notes
- **Synchronous execution.** A run is executed in-request; on a very large import this will be slow. The `Run` model already carries `pending`/`running` status so a later phase can move it to Celery without a schema change.
- **`JA-DORMANT` only sees the current import.** Dormancy is computed from gaps *within the imported data*, so it cannot detect an account dormant before the import window. This is deterministic and explainable, but it is not a full account-history analysis.
- **Journal grouping depends on `journal_number`.** Rows without one become single-row synthetic journals, which can inflate the journal count for poorly-formed extracts.
- **Overlap with 2B is intentional and visible**: the same underlying condition can appear both as a 2B row finding and a 7A journal analytic. 7A is advisory and deliberately does not deduplicate against 2B.
- `SIGNIFICANT_AMOUNT` and `DORMANT_DAYS` are fixed constants, not yet per-engagement configuration.
- No production readiness is claimed.

## 11. Recommended next phase
**TADGEEG-FIN-AUDIT-7B — Statistical Analytics:** Benford's Law (wiring the *existing* `apps/analytics/benford_service.py` into engagement-scoped runs rather than reimplementing it), plus ratio/trend analysis — reusing the same Run/Result/Summary backbone and rule registry established here.
