# TADGEEG-FIN-AUDIT-6D — Evidence Assurance & Reporting

> **Phase type:** Additive assurance/reporting layer over 6A–6C. One migration. No new apps, no duplicated logic, no rewritten phase.
> **Date:** 2026-07-24 · **Builds on:** `ebda512` (6C).
> **Honored:** fully additive · zero regression · no ledger writes · no AI · no automatic audit opinion · no production-readiness claim.

---

## 1. Architectural conflicts found
1. **6C already stores `last_verification_ok` (boolean)** while 6D needs a richer `verification_result`.
2. **Retention level mismatch** — 6C has attachment-level `retention_until`; 6D requires an *engagement-level* policy.
3. **Readiness conclusion must not change**, yet 6D must surface evidence data in the readiness export.
4. **The dashboard already carries two evidence aggregates** (6B `status_counts`, 6C `dashboard_summary`); eight more widgets could mean eight more queries.
5. **"Required evidence" is undefined in the schema** — nothing records how much evidence an item *should* have.
6. *(Found by a 6D test)* **A deleted file crashed the reader** — `FileNotFoundError` escaped 6C's `_read_and_hash`, so a sweep would abort and a download would 500.

## 2. Decisions taken
1. Added `verification_result` (choices) + `verification_duration_ms` + `verification_error`; **`last_verification_ok` is kept as the boolean mirror** (same pattern as `is_active`↔`lifecycle_state`). No existing reader changes.
2. New `AuditEvidenceRetentionPolicy` keyed to the engagement, which **computes into the existing `retention_until` field**. `AuditEngagement` is **not modified**; no second retention concept is introduced.
3. Evidence data is added to the **5D export payload/template only** (`include_evidence=True`), explicitly flagged `informational_only`. The 5A `_conclude()` algorithm and the workpaper model are untouched — asserted by a test.
4. One **combined aggregate** (`assurance_dashboard`) drives all new widgets, fed defensively so a widget can never break the dashboard.
5. Defined **required = evidence requests raised**; coverage % = accepted ÷ required. Items with no requests get a distinct `no_requests` status rather than a misleading 0%.
6. Fixed at the source in `evidence_lifecycle._read_and_hash`: `FileNotFoundError`/`OSError` now raise `EvidenceIntegrityError`, so a missing file is *reported* (`missing_file`) instead of crashing. This also turns a missing-file download into a clean `409`. All 43 existing 6C tests still pass.

### Explicitly REUSED (not reimplemented)
`evidence_lifecycle.verify_attachment` (the actual SHA-256 comparison), `_attachment_event` (append-only trail), `evidence_request.status_counts`, `evidence_lifecycle.dashboard_summary`/`queue_counts`, `apps/notifications` (`notify`), the 5D export service + template, and the 6C lifecycle/version/retention fields.

## 3. Files created/changed
**Created:** `apps/audit/services/evidence_assurance.py` · `apps/audit/views_evidence_assurance.py` · `apps/audit/migrations/0026_…` · `apps/audit/tests/test_evidence_assurance.py` · `apps/frontend/evidence_assurance_views.py` · `apps/frontend/tests/test_evidence_assurance_pages.py` · `templates/audit/assurance/{_shared,_nav,overview,integrity,coverage,index,retention}.html` · this document.
**Changed:** `apps/audit/evidence_models.py` (additive fields/choices + new model) · `apps/audit/models.py` (re-export) · `apps/audit/services/evidence_lifecycle.py` (missing-file robustness) · `apps/audit/services/evidence_notifications.py` (4 auditor-only helpers) · `apps/audit/services/audit_readiness_export.py` (`include_evidence`) · `apps/audit/urls.py` · `apps/frontend/urls.py` · `apps/frontend/page_views.py` (dashboard context) · `templates/audit/audit_readiness_report.html` · `templates/dashboard/index.html` · `templates/layouts/dashboard_base.html`.

## 4. Migration
**0026** — adds `verification_result`, `verification_duration_ms`, `verification_error` to `AuditEvidenceAttachment`; creates `AuditEvidenceRetentionPolicy`. Purely additive; no field removed; no existing migration edited; `makemigrations --check` clean.

## 5. Backend implementation
- **Integrity sweep** — `sweep_attachments()` walks every *live* attachment, delegates the hash comparison to 6C's `verify_attachment`, and records result + duration + error. Archived attachments are skipped. **Files are never modified or repaired** — asserted by a test that confirms tampered bytes stay tampered.
- **Exception report** — `integrity_exception_report()` buckets hash mismatch · missing files · unreadable · no digest · pending verification · expired · frozen · archived, with statistics and an integrity %.
- **Coverage** — `evidence_coverage()` computes required/uploaded/accepted/rejected/pending and coverage %/status per GL finding and SAD item, plus an overall summary. Statuses: complete (100) · high (≥75) · partial (≥50) · low (>0) · none (0) · no_requests.
- **Evidence index** — `evidence_index()` produces immutable `EV-00001…` rows with finding, SAD item, filename, version, SHA-256, integrity, status, reviewer, review date, retention and lifecycle. **No download URLs** (asserted).
- **Retention** — `set_retention_policy()` / `apply_retention_policy()` (7 y · 10 y · forever · custom). Applying only stamps `retention_until`; frozen attachments are skipped and **nothing is ever deleted or purged**.
- **Dashboard** — `assurance_dashboard()` returns integrity %, coverage %, pending reviews, rejected, expired, frozen, open requests and a verification status, using aggregate queries.
- **Readiness integration** — `readiness_evidence_section()` feeds the export only, tagged `informational_only`.
- **Notifications** — integrity failure, coverage below threshold, evidence expired, verification completed. All resolve recipients via the auditor capability, so **clients are never notified** (asserted).

## 6. Frontend implementation
| Page | URL | Surfaces |
|---|---|---|
| Assurance overview | `/audit/assurance/` | integrity %, coverage %, pending reviews, rejected, open requests, expired, frozen, verification status + progress bars |
| Integrity report | `/audit/assurance/integrity/` | **Run integrity sweep** button + every exception bucket with result/lifecycle badges and errors |
| Coverage report | `/audit/assurance/coverage/` | per-finding and per-SAD-item table with coverage bars, status badges, links into the 6B host pages |
| Evidence index | `/audit/assurance/index/` | the immutable index (no download links) |
| Retention policy | `/audit/assurance/retention/` | set + optionally apply a policy per engagement; existing policies table |
| Dashboard widgets | `/dashboard/` | integrity %, coverage %, expired, frozen, verification status + link to assurance |

Shared sub-navigation and an engagement filter across all five pages; a sidebar entry ("Evidence Assurance"). Reuses the existing `dashboard_base` layout and the 6B/6C style partial: RTL + English, responsive (tables scroll, KPI grids collapse), badges, breadcrumbs, empty states. No SPA.

## 7. API endpoints (all ADDED)
| Method | Path |
|---|---|
| POST | `/api/v1/audit/evidence-assurance/sweep/` |
| GET | `/api/v1/audit/evidence-assurance/integrity-report/` |
| GET | `/api/v1/audit/evidence-assurance/coverage/` |
| GET | `/api/v1/audit/evidence-assurance/index/` |
| GET | `/api/v1/audit/evidence-assurance/dashboard/` |
| GET/POST | `/api/v1/audit/engagements/<uuid>/retention-policy/` |

All accept an optional `?engagement=<uuid>` filter that 404s for a foreign engagement.

## 8. Security review
- **Auditor-only**: every assurance endpoint and page requires `IsSeniorAuditorOrAbove` / the auditor capability. Assurance is an internal quality function — a client user gets **403 on all five pages and all five endpoints** (asserted).
- **Organization isolation**: every query filters on `organization` first; the optional engagement filter is resolved through an org-scoped lookup that returns **404** for a foreign engagement (both API and page).
- **Client capabilities unchanged** — 6B/6C client read/upload rights are untouched; no privilege escalation, no new client surface.
- **Append-only history preserved** — sweeps write `verified`/`verification_failed` events through the existing recorder; nothing is edited or removed.
- **No deletion anywhere** — retention is metadata; expiry is computed and notified, never enforced.
- **No download URLs in the index**, by design and by test.

## 9. Tests added
`apps/audit/tests/test_evidence_assurance.py` (47): sweep (clean/mismatch/missing file/skips archived/org-scoped/append-only, never repairs), exception report (buckets, statistics, integrity %, lifecycle buckets, pending, org scope), coverage (0 %/100 %/50 %/no_requests/rejected/SAD item/org scope), evidence index (all columns, no URLs, archived included, org scope), retention (7 y/forever/custom/validation/skips frozen/no deletion/one per engagement), readiness integration (sections present, **conclusion unchanged**, opt-out, HTML render stays opinion-safe), dashboard (aggregates, failure flag, org scope), notifications (all four, auditors only, never clients), API (all six endpoints, client 403 on every one, cross-org 404 ×2), and no-ledger-writes/no-deletion.

`apps/frontend/tests/test_evidence_assurance_pages.py` (15): login required + client 403 + auditor render across all five pages, overview widgets + sub-nav, sweep from UI, failure visible, pending bucket, coverage listing + acceptance reflected, index without download links, retention set/apply/validation/cross-org, cross-org exclusion from reports, dashboard widgets.

## 10. Intentionally NOT implemented
Scheduled/beat-driven sweeps (the service is idempotent and callable; wiring cron is a deployment decision) · automatic purge or repair of evidence · virus scanning · client-facing assurance views · charts beyond CSS progress bars (no chart library is bundled).

## 11. Recommended next phase
**TADGEEG-FIN-AUDIT-6E — Assurance automation & attestation:** schedule the sweep via Celery beat with an exception digest, add a signed assurance attestation appended to the readiness export, per-organization coverage thresholds and SLA policies, and an evidence completeness gate that *advises* (never blocks) before readiness sign-off.
