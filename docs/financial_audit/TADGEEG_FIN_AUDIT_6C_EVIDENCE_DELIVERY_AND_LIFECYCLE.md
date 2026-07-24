# TADGEEG-FIN-AUDIT-6C — Evidence Delivery & Lifecycle

> **Phase type:** Additive completion of the evidence lifecycle on top of 6A/6B — backend **and** frontend. One migration. No new apps, no duplicated models, no replaced services.
> **Date:** 2026-07-24 · **Builds on:** `fe7967f` (6B).
> **Honored:** no ledger/JournalEntry writes · no TB/GL/risk/materiality/SAD/review/readiness/ISA-700 changes · no CRM/billing/subscription/authentication changes · no existing migration modified · no AI.

---

## 1. Architectural conflicts found (reported before coding)
1. **`is_active` vs. new lifecycle states** — the pre-6C boolean is used in 4 call sites. Duplicating it would fork the truth.
2. **Versioning had no grouping concept** — attachments were already never overwritten, but nothing expressed "version N of this evidence".
3. **Attachment-scoped events vs. the request-scoped trail** — download/verify/archive are attachment-level; a second event model would duplicate the audit trail.
4. **"Expired" retention had no policy** — no retention field and no purge job existed anywhere in the project.
5. **SHA-256-before-serve requires reading the file twice** (or buffering) to guarantee corrupt bytes are never emitted.

## 2. Decisions taken
1. `lifecycle_state` is authoritative; **`is_active` is kept as a mirror** (`active`/`frozen` → True) so all existing queries keep working untouched.
2. `version` ordinal per request + an explicit `replaces` self-FK chain — **no new model**.
3. Added a **nullable `attachment` FK to the existing `AuditEvidenceRequestEvent`** — one append-only trail for both request and attachment events.
4. Added `retention_until`; `is_expired` is **computed**, and **nothing is ever auto-purged or hard-deleted**.
5. Read-then-hash-then-serve: the digest is verified **before** any byte is returned; on mismatch the download is refused with `409` and a `verification_failed` event.

## 3. Files created
`apps/audit/services/evidence_lifecycle.py` · `apps/audit/views_evidence_lifecycle.py` · `apps/audit/migrations/0025_…` · `apps/audit/tests/test_evidence_lifecycle.py` · `apps/frontend/evidence_queue_views.py` · `apps/frontend/tests/test_evidence_lifecycle_pages.py` · `templates/audit/evidence/queue.html` · this document.

## 4. Files modified
`apps/audit/evidence_models.py` (additive fields/choices) · `apps/audit/services/evidence_request.py` (version stamping on upload) · `apps/audit/services/evidence_notifications.py` (3 new helpers) · `apps/audit/serializers.py` · `apps/audit/urls.py` · `apps/frontend/evidence_views.py` (lifecycle actions + version history) · `apps/frontend/urls.py` · `apps/frontend/page_views.py` (dashboard summary context) · `templates/audit/evidence/detail.html` · `templates/audit/client_portal/detail.html` · `templates/dashboard/index.html` · `templates/layouts/dashboard_base.html`.

## 5. Migrations
**0025** — adds to `AuditEvidenceAttachment`: `lifecycle_state`, `lifecycle_changed_at`, `lifecycle_changed_by`, `retention_until`, `version`, `replaces`, `notes`, `last_verified_at`, `last_verification_ok` (+2 indexes); adds `attachment` FK and 9 new `event_type` choices to `AuditEvidenceRequestEvent`. Purely additive — no field removed, no existing migration touched.

## 6. Backend implementation
- **Download (Part 1)** — `read_for_download()` never returns bytes unless the recomputed digest matches. Media URLs are never exposed; the file is served through an authenticated, org-scoped, permission-checked view.
- **Integrity (Part 2)** — `verify_attachment()` re-hashes on demand; both paths write `verified` / `verification_failed` events and update `last_verified_at` / `last_verification_ok` (surfaced as an `integrity_badge`).
- **Versioning (Part 3)** — every upload stamps `version = max+1`; `supersede()` links `replaces` and archives the prior version. Old versions stay readable and immutable.
- **Audit trail (Part 4)** — download, archive, restore, freeze, expire, version-created, verification-failure, escalation and assignment all append to the single immutable trail (admin add/change/delete disabled).
- **Archive/Retention (Parts 5–6)** — `archive` / `restore` / `freeze` / `mark_expired` / `set_retention`. **Freeze is terminal**: it blocks archive, restore, expire and retention changes (frozen evidence remains downloadable). Nothing is ever hard-deleted.
- **Queue (Part 7)** — `auditor_queue()` with buckets (waiting review · overdue · due today · accepted today · rejected · more evidence · high priority), filters, search and sorting; `queue_counts()` in one aggregate query.
- **Bulk assignment (Part 8)** — `bulk_assign_reviewer()` in a single transaction, reusing `assign_users` so rules and events are identical; final requests are skipped and reported.
- **SLA (Part 9)** — `escalate_overdue()` records an `escalated` event (idempotent per day) and notifies. **It never changes a request's status.**
- **Dashboard (Part 10)** — `dashboard_summary()` returns waiting, pending reviews, accepted, rejected, overdue, more-evidence and **average review time** (`reviewed_at − submitted_at`).
- **Notifications (Part 11)** — reuses `apps/notifications` only; adds assignment-changed, due-tomorrow and overdue on top of the existing uploaded/accepted/rejected.

## 7. Frontend implementation
| UI | Where | Backend capability surfaced |
|---|---|---|
| **Evidence Queue** `/audit/evidence/queue/` | new page + sidebar entry | buckets w/ counts, filters, search, sorting, dashboard cards, **bulk assignment** (checkbox select-all + reviewer picker) |
| **Version history** table | auditor detail page | every version w/ uploader, date, size, **lifecycle badge**, **integrity badge** |
| **Download / Verify / Archive / Restore / Freeze** buttons | auditor detail page, per version | the five lifecycle + integrity endpoints |
| **Download button + integrity badge + version** | client portal detail | secure download for the assigned client |
| **Dashboard cards** | main dashboard | pending reviews, average review time, + link into the queue |

All pages reuse the existing `dashboard_base` layout: RTL + English (logical CSS properties, bilingual headings), responsive (tables scroll, grids collapse), badges, timeline, breadcrumbs and empty states. Buttons are permission-aware (lifecycle controls render only for auditors; frozen versions hide mutating actions).

## 8. API endpoints (all ADDED; none replaced)
| Method | Path |
|---|---|
| GET | `/api/v1/audit/evidence-attachments/<uuid>/download/` |
| GET/POST | `/api/v1/audit/evidence-attachments/<uuid>/verify/` |
| POST | `/api/v1/audit/evidence-attachments/<uuid>/{archive\|restore\|freeze}/` |
| GET | `/api/v1/audit/evidence-requests/<uuid>/versions/` |
| GET | `/api/v1/audit/evidence-queue/` |
| POST | `/api/v1/audit/evidence-requests/bulk-assign/` |
| GET | `/api/v1/audit/evidence-dashboard/summary/` |

## 9. Security review
- **No direct media URLs.** Bytes are only ever served by the authenticated download view after org scoping, visibility and integrity checks.
- **Organization isolation** first, then **assigned-client visibility**: `scoped_attachment()` returns `None` → **404** for a foreign org *and* for a client who is not assigned to that request (existence is never disclosed). Verified by tests for both cases.
- **Least privilege**: archive/restore/freeze, the queue, bulk assignment and the dashboard summary are auditor+ (`IsSeniorAuditorOrAbove`); the assigned client may download and verify only.
- **No deletion path exists** anywhere — archive/expire are state changes; frozen is terminal.
- **No evidence replacement** — uploads only ever create new versions; prior versions keep their bytes and digest.
- **No privilege escalation** — client capabilities are unchanged from 6B; no role or authentication change.
- **Corrupt evidence is refused** (`409`) rather than served, and the failure is recorded immutably.

## 10. Tests added
`apps/audit/tests/test_evidence_lifecycle.py` (43): verification OK/tamper-detected, download refusal on corruption (with no download event), versioning (ordinals, old versions intact, `version_created`, supersede+archive), archive/restore, freeze blocking every mutation while remaining downloadable, retention expiry computed (not purged), expired download blocked, archived hidden-but-kept, queue buckets/search/high-priority/org scoping, bulk assign (transaction, skip-final, foreign reviewer rejected), SLA escalation (event, idempotent, never closes), due-tomorrow notification, dashboard summary + avg review time, download API permissions (auditor / assigned client / unassigned 404 / cross-org 404 / anonymous / 409 corrupt), verify + lifecycle APIs, versions/queue/bulk-assign/summary endpoints, assignment + overdue notifications, no-deletion and **no ledger writes**, and events linked to their attachment.

`apps/frontend/tests/test_evidence_lifecycle_pages.py` (17): queue login/render/permissions/bucket/search/org-exclusion/bulk-assign/validation, auditor detail version history + controls + badges, archive→restore, freeze→blocked, verify success and failure surfaced, cross-org attachment action rejected, client denied lifecycle actions, client download button, dashboard cards + queue link.

## 11. Intentionally NOT implemented
Automatic retention purge (evidence is never destroyed) · a scheduled beat entry for escalation (the service + idempotency exist; wiring a cron is a deployment decision) · virus scanning · e-signature · external/pre-signed CDN delivery · attachment deletion.

## 12. Recommended next phase
**TADGEEG-FIN-AUDIT-6D — Evidence assurance & reporting:** scheduled integrity sweeps with an exception report, an evidence index appended to the 5D readiness export, per-engagement retention policies, and evidence coverage metrics per finding/SAD item.
