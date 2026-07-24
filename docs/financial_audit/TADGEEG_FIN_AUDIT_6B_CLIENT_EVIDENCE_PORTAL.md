# TADGEEG-FIN-AUDIT-6B — Client Evidence Portal & Collaboration

> **Phase type:** Additive extension of the 6A evidence workflow into an Auditor ↔ Client collaboration, **backend + frontend**. Two migrations, no new apps, no model duplication.
> **Date:** 2026-07-24 · **Builds on:** `546d20c` (6A).
> **Honored:** reuse existing models/services; additive only; no new apps; no ledger writes; no accounting posting; no AI; no automatic audit opinion; no payment/CRM/subscription/**authentication** changes.

---

## 1. Architectural conflicts found (reported before implementing)

Two conflicts were discovered during inspection and resolved by explicit decision:

**Conflict 1 — no "Client" role exists.** `User.Role` has only auditor-side roles plus `finance_manager`; there is no client/company role, and rule 16 forbids authentication changes. **Resolution (chosen): per-request assignment.** A new additive FK `AuditEvidenceRequest.assigned_client_user` grants client-portal access to exactly one user per request. Access is therefore **data-driven, not role-driven** — zero changes to `apps/authentication`, and it works with whatever role the client user already has.

**Conflict 2 — the three required integration targets had no pages.** The spec asks for UI "inside the GL Finding page", "inside the SAD Item page" and in "Audit Readiness"; none of those frontend pages existed (findings/SAD/readiness were API-only plus the 5D export). **Resolution (chosen): create minimal read-only host pages** whose sole purpose is to carry the required evidence affordances.

## 2. Files created/changed

**Backend (changed, additive):** `apps/audit/evidence_models.py` (3 fields + SLA properties + `ASSIGNED` event type + uniqueness constraint), `apps/audit/services/evidence_request.py` (numbering, assignment, explanation, upload validation, counts), `apps/audit/views_evidence.py` (client scoping, assign + explanation endpoints), `apps/audit/serializers.py`, `apps/audit/urls.py`.
**Backend (new):** `apps/audit/services/evidence_notifications.py`, migrations `0023`, `0024`, `apps/audit/tests/test_evidence_client_portal.py`.
**Frontend (new):** `apps/frontend/client_portal_views.py`, `apps/frontend/audit_host_views.py`, `templates/audit/client_portal/{_evidence_styles,list,detail}.html`, `templates/audit/findings/detail.html`, `templates/audit/sad/item_detail.html`, `templates/audit/readiness/summary.html`, `apps/frontend/tests/test_client_portal_pages.py`.
**Frontend (changed):** `apps/frontend/urls.py`, `apps/frontend/page_views.py` (dashboard widget context), `templates/layouts/dashboard_base.html` (sidebar), `templates/dashboard/index.html` (widget).
**Docs:** this file.

## 3. Migrations
- **0023** — adds `assigned_client_user`, `management_explanation`, `request_number` (+ index, + per-org uniqueness constraint on non-blank numbers).
- **0024** — adds the `assigned` choice to `AuditEvidenceRequestEvent.event_type`.

Both are purely additive; no data migration, no field removal, no change to 6A semantics.

## 4. Backend implementation
**Reused, never replaced:** `AuditEvidenceRequest`, `AuditEvidenceAttachment`, `AuditEvidenceRequestEvent`, the 6A transition graph and review rules, `apps/notifications` (`Notification` + `notify()`), and `core.utils.file_validation` size limits.

- **Request number** — `EVR-00001`, sequential per organization, generated in-transaction with retry on collision and a partial unique constraint.
- **Assignment** — `assign_users()` sets auditor and/or client user, validates both belong to the request's organization, and appends an `assigned` event.
- **Management explanation** — `record_management_explanation()` stores the client's context and appends a `note_added` event; blocked on final requests.
- **Upload validation** — `validate_evidence_file()` enforces the allowlist **PDF, DOCX, XLSX, PNG, JPG/JPEG, ZIP**, reuses the project size limits (`MAX_FILE_SIZE` / `MAX_ZIP_SIZE`), and screens magic bytes for executables/scripts. Defined locally rather than widening the shared `SAFE_MIME_TYPES` (which lacks `.docx`) so **no other upload flow in the project is loosened**. SHA-256 + size + content type are stored per attachment.
- **SLA** — computed properties only (`days_remaining`, `is_overdue`, `sla_state` ∈ completed/waiting/overdue/due_soon/on_track/none). No stored state, no scheduler.
- **Counts** — `status_counts()` returns every status plus `overdue`, `total`, `open_gaps` in a **single** aggregate query (conditional counts), so embedding it in the dashboard stays cheap.
- **Notifications** — system/in-app only, via the existing service: request created → client; files uploaded → assigned auditor + requester; accepted/rejected/more-evidence → client. Failures are swallowed by `notify()` and can never break the workflow.

## 5. Frontend implementation
| URL | Page | Contents |
|---|---|---|
| `/audit/client-evidence/` | Client portal list | request #, title, finding, SAD item, priority, due date, **SLA badge**, status badge, assigned by, last updated, action; filters (status, priority, engagement, overdue) + search (title/number/finding/SAD item); status KPI widget; empty state |
| `/audit/client-evidence/<uuid>/` | Client portal detail | request info, description, reason, requested by, assigned auditor, due date, priority, status; attachments (name/uploader/date/size/SHA-256); **drag & drop multi-file upload with progress bar**; management explanation; submit; append-only timeline |
| `/audit/findings/<uuid>/` | GL finding (new host page) | finding details + **"Request Evidence"** button + its evidence requests |
| `/audit/sad-items/<uuid>/` | SAD item (new host page) | item details + evidence requests, **open count**, **latest upload** |
| `/audit/readiness/<uuid>/` | Readiness (new host page) | outstanding evidence (open/submitted/under review/more needed/accepted/rejected/overdue) shown **before** concluding readiness, with the 5A/5B safe-wording notice |
| `/dashboard/` | Dashboard widget | Open · Submitted · Under review · Accepted · Rejected · More needed · Overdue |

Sidebar gains **Audit → Client Evidence Portal**. All pages use the existing `dashboard_base` layout, are RTL/English (logical CSS properties, bilingual labels: بوابة أدلة العميل · رفع دليل · حالة الطلب · ملاحظة المراجع), responsive (grids collapse, tables scroll), and include breadcrumbs, badges, timelines, empty states and permission-aware buttons. Upload progress uses dependency-free vanilla JS with a plain-POST fallback.

## 6. API endpoints
Existing 6A endpoints retained. **New:** `POST evidence-requests/<uuid>/assign/` (auditor+) and `POST evidence-requests/<uuid>/management-explanation/` (auditor+ or assigned client). **Changed (widened safely):** `attachments/` and `submit/` now also allow the assigned client user; `list`/`detail`/`events` are now client-scoped.

## 7. Security decisions
- **Client identity is per-request** (`assigned_client_user`) — no role or auth change, and no blanket "client" access to an organization.
- **A client sees only their own assigned requests.** The list filters to `assigned_client_user=user`; detail/events return **404** (not 403) for any other request so existence is never leaked — including another client in the *same* organization.
- **Organization isolation preserved**: every query is `organization`-scoped first; cross-org is 404 everywhere (API + pages).
- **Clients cannot review** (accept/reject/more-evidence/cancel remain `IsSeniorAuditorOrAbove`), cannot create requests, cannot assign, cannot modify findings or SAD (host pages are strictly read-only), and cannot delete attachments (no delete path exists anywhere).
- **Append-only**: all state changes emit events; the event admin has add/change/delete disabled.
- **Upload hardening**: extension allowlist + size limits + magic-byte screen; whole batch is validated **before** any file is stored, so a rejected batch leaves no partial upload. SHA-256 retained for verification.
- Accepting evidence still **never** auto-resolves the GL finding (6A rule, re-asserted by test).

## 8. Tests added
`apps/audit/tests/test_evidence_client_portal.py` (33): numbering (sequential, per-org independent), assignment + events + notification, cross-org assignment rejected, SLA (overdue/due_soon/on_track/completed/none), upload allowlist (6 accepted formats; `.exe`/`.sh`/`.html`/`.csv` rejected; executable-disguised-as-PDF rejected), SHA-256/metadata, management explanation (record/empty/final), notifications (upload→auditor, all three outcomes→client, no-client-assigned safe), status counts (values, client scoping, **single query**), client API security (own-only listing, other-client 404, upload+submit allowed, review/create/assign 403, cross-org 404, bad format 400), auditor assignment API, and ledger isolation.

`apps/frontend/tests/test_client_portal_pages.py` (20): login required; list (badges, other-client hidden, status filter, search, overdue filter); detail (dropzone + timeline render, cross-client 404, cross-org 404, multi-file upload, rejected batch stores nothing, explanation saved, submit, client cannot review); host pages (GL finding "Request Evidence" + cross-org 404, SAD item evidence panel, readiness counts + no unsafe opinion wording + cross-org 404); dashboard widget.

## 9. Intentionally NOT implemented
New `CLIENT` role · any authentication change · email/SMS/push delivery (system notifications only) · attachment download/delete endpoints · client self-service request creation · reopen of final requests · bank/VAT reconciliation · AI · ledger posting · React/Vue.

## 10. Recommended next phase
**TADGEEG-FIN-AUDIT-6C — Evidence delivery & lifecycle:** authenticated attachment download with SHA-256 verification on read, evidence retention/archival policy, optional email notification channel, bulk assignment, and an auditor-side evidence queue with SLA escalation.

## 11. What NOT to change (carried forward)
No formal audit opinion; no unsafe ISA-700 wording; no ledger/`JournalEntry` writes; no AI; no new apps; no duplicate evidence models or parallel workflow; no authentication/payments/subscriptions/CRM/legal-page changes; no production-readiness claim.
