# TADGEEG-FIN-AUDIT-6A — Evidence Request Workflow (Backend + Frontend)

> **Phase type:** New workflow — models + service + API + **server-rendered frontend**. One migration.
> **Date:** 2026-07-12 · **Builds on:** `ec12052` (5D). · **Predecessors:** [3B](TADGEEG_FIN_AUDIT_3B_GL_FINDING_REVIEW_WORKFLOW.md), [4A](TADGEEG_FIN_AUDIT_4A_SAD_MISSTATEMENT_ACCUMULATION_BACKBONE.md), [4B](TADGEEG_FIN_AUDIT_4B_MANAGEMENT_RESPONSE_AND_PROPOSED_ADJUSTMENTS.md), [5A](TADGEEG_FIN_AUDIT_5A_AUDIT_READINESS_OPINION_PREPARATION_WORKPAPER.md), [5D](TADGEEG_FIN_AUDIT_5D_AUDIT_READINESS_EXPORT_AND_REPORT_INTEGRATION.md).
> **Honored:** no formal opinion; no AI; no ledger writes; no bank/VAT reconciliation; no payment/subscription/CRM changes; no production-readiness claim.

---

## 1. What was implemented
An evidence-request workflow that lets an auditor request, upload/attach, track, and review supporting evidence for a machine-suggested GL risk finding (typically `needs_evidence`/`escalated`) or an accepted SAD difference item — **with a minimal safe frontend** so the feature is usable from the Tadgeeg UI, not API-only.

- **Backend:** three models, a workflow service, DRF endpoints, admin registration.
- **Frontend:** server-rendered Django pages (list, detail, create) reachable from the audit navigation, exposing **every** service capability as a page/table/button/badge/history view.

## 2. Files created/changed
**Backend**
- `apps/audit/evidence_models.py` (new) — `AuditEvidenceRequest`, `AuditEvidenceAttachment`, `AuditEvidenceRequestEvent`.
- `apps/audit/services/evidence_request.py` (new) — workflow service.
- `apps/audit/views_evidence.py` (new) — DRF endpoints.
- `apps/audit/migrations/0022_auditevidencerequest_auditevidenceattachment_and_more.py` (new).
- `apps/audit/models.py`, `serializers.py`, `admin.py`, `urls.py` (changed) — register/serialize/admin/route.
- `apps/audit/tests/test_evidence_request.py` (new) — backend tests.

**Frontend**
- `apps/frontend/evidence_views.py` (new) — list / detail / create page views.
- `apps/frontend/urls.py` (changed) — three page routes.
- `templates/audit/evidence/list.html`, `detail.html`, `create.html` (new).
- `templates/layouts/dashboard_base.html` (changed) — "Evidence Requests" sidebar entry.
- `apps/frontend/tests/test_evidence_pages.py` (new) — frontend tests.

**Docs:** this file.

## 3. Migration created
`0022_auditevidencerequest_auditevidenceattachment_and_more` — creates the three tables + indexes. No changes to existing models; `makemigrations --check` is clean afterward.

## 4. Evidence request model / service details
`AuditEvidenceRequest`: `engagement`, `organization`, nullable `gl_finding` / `sad_item`, `requested_by`, `assigned_to`, `title`, `description`, `request_reason` (support_finding · management_explanation · supporting_document · bank_support · invoice_support · contract_support · approval_support · other), `status`, `priority` (low/medium/high/critical), `due_date`, `requested_at`, `submitted_at`, `reviewed_by`/`reviewed_at`/`reviewer_note`, timestamps. `clean()` enforces org == engagement.org, that a linked finding/item belongs to the same engagement+org, and that **at least one** of finding/item is set.

`AuditEvidenceAttachment`: FileField (`max_length=255`, org/request-scoped upload path) + optional `document` FK, `file_sha256`, `size_bytes`, `content_type`, `description`, `is_active`, `uploaded_by`, `uploaded_at`. Attachments to a **final** request are rejected.

`AuditEvidenceRequestEvent`: append-only trail (`created`, `submitted`, `under_review`, `accepted`, `rejected`, `more_evidence_required`, `cancelled`, `attachment_added`, `note_added`) with `from_status`/`to_status`/`note`/`metadata`. No add/change/delete in admin.

Service (`evidence_request.py`): `create_evidence_request`, `add_attachment` (computes sha256+size), `submit_evidence`, `review_evidence_request`, plus `open_evidence_request_count`. Every mutation is atomic and writes an event. Reviewer note is required for `reject`/`more_evidence`. Accept requires ≥1 active attachment **unless** `request_reason == management_explanation` (documented explanation-only exception).

## 5. Attachment / document reuse decision
**Option B — a lightweight `AuditEvidenceAttachment` with its own FileField.** `documents.Document` exists and has org scoping + `file_sha256`, but it is coupled to an extraction/analysis pipeline (`signals.py`, `tasks.py`) that could trigger downstream processing/AI — out of scope for this phase. The lightweight model stays self-contained (sha256/size/content_type computed in-service) and keeps a nullable `document` FK so a future phase can link to `Document` without a migration.

## 6. Status transitions
```
open                   → submitted | cancelled
submitted              → under_review | cancelled
under_review           → accepted | rejected | more_evidence_required | cancelled
more_evidence_required → submitted | cancelled
accepted / rejected / cancelled → (final, no transitions)
```
`cancel` is permitted from any non-final state (a safe superset of the spec's `open→cancelled`; a cancel is not a reopen). No reopen is implemented.

## 7. API endpoints (all under `/api/v1/audit/`)
| Method | Path | Permission |
|---|---|---|
| GET / POST | `evidence-requests/` | GET auth · POST auditor+ |
| GET | `evidence-requests/<uuid>/` | auth (org-scoped) |
| POST | `evidence-requests/<uuid>/submit/` | auditor+ |
| POST | `evidence-requests/<uuid>/review/` (`action`, `note`) | auditor+ |
| GET / POST | `evidence-requests/<uuid>/attachments/` | auditor+ |
| GET | `evidence-requests/<uuid>/events/` | auth (org-scoped) |

All queries are scoped to `request.user.organization`; another org's request is a 404 (no existence leak). Create/review/submit/upload require `IsSeniorAuditorOrAbove` (auditor+); client/company upload is deferred (documented) and restricted to auditor+ this phase. No hard delete; no ledger writes.

## 8. Frontend pages (server-rendered, `apps/frontend`)
| URL | Page | Capability surfaced |
|---|---|---|
| `/audit/evidence/` | List | table (title, linked finding/item, status **badge**, priority, due, requested/assigned, created, detail link), status filter, open-count KPI, "Request Evidence" button |
| `/audit/evidence/new/` | Create | pick engagement + GL finding (needs_evidence/escalated) or SAD item, title, description, reason, priority, due date |
| `/audit/evidence/<uuid>/` | Detail | full details, attachments list (name/uploader/date/size/hash/description), **upload** form, **every** review action button (submit, mark under review, accept, reject, request more, cancel), reviewer-note input, event **history** timeline |

Reachable from the **audit navigation** ("Evidence Requests" sidebar item). **Every backend capability has a frontend entry point** (create button, upload form, one button per review transition, status badges, history timeline, list table). Status badges cover all seven statuses. Labels are bilingual EN/AR (طلبات الأدلة · طلب دليل · رفع دليل · حالة الطلب · تحت المراجعة · مقبول · مرفوض · مطلوب دليل إضافي · ملغى · ملاحظة المراجع) and the layout is RTL-aware via the shared `dashboard_base` (`dir` + logical CSS properties).

**Entry-point note (addendum §7):** the audit `GeneralLedgerRiskFinding` items have no standalone Django template page (they are API/dashboard-driven; the `general_ledger_detail` page belongs to the unrelated `documents.GeneralLedger` domain), so a per-finding inline "Request Evidence" button was not safely available. Instead the evidence pages are surfaced through the audit navigation and the create page lets the auditor select the target finding/SAD item — a safe, documented entry point.

Frontend permissions mirror the API: any authenticated org member can **view**; create/upload/submit/review require auditor+ (`has_role_capability("approve_invoices")`). Cross-org detail is 404. POST by a non-auditor returns 403.

## 9. Relationship with `needs_evidence` findings & why acceptance doesn't close the finding
A request may target a finding in `needs_evidence`/`escalated`. **Accepting evidence never changes the GL finding's status** — it does not accept, dismiss, or resolve it. The 3B review workflow remains the single place a finding's status changes; the auditor must review the finding separately using their professional judgment. Tests assert the finding status is unchanged after acceptance. `AuditReadinessWorkpaper` still counts `needs_evidence` findings exactly as before (unchanged); the new `open_evidence_request_count` helper is additive and does not alter readiness conclusions.

## 10. Why this is not a formal opinion / no ledger writes
The workflow only tracks evidence requests and their review state; it emits no opinion text and sets no opinion. It writes only to the three new `audit_evidence_*` tables (+ its own FileField storage) — never to `apps.ledger` (`Account`/`JournalEntry`/`JournalLine`), asserted by a ledger-isolation test.

## 11. Tests run
Backend `apps/audit/tests/test_evidence_request.py` (19): creation linked to finding/SAD item, link-required + org validation, happy path, invalid transition rejected, note-required reject/more-evidence, accept-requires-attachment + explanation-only exception, finality, attach-to-final rejected, attachment hash/metadata, append-only ordered history, finding-unchanged + no-ledger-writes, API create/list/detail/upload/submit/review/events org-scoped, junior-denied, cross-org 404. Frontend `apps/frontend/tests/test_evidence_pages.py`: login required, list scoping + badge, cross-org 404, create renders/creates + junior 403, detail actions/history render, upload from detail, full review flow via detail, junior can view but not act. Regression: 3B / 4A / 4B / 5A / 5D suites + full `apps/audit`. Results in the response §10.

## 12. Intentionally NOT implemented
Workpaper generation · formal ISA-700 opinion · automatic finding resolution on acceptance · reopen of final requests · client/company upload role (deferred) · bank/VAT reconciliation · AI · ledger posting · React/Vue (project uses Django templates) · per-finding inline "Request Evidence" button (no safe finding page — see §8).

## 13. Recommended next phase
**TADGEEG-FIN-AUDIT-6B — Client evidence portal & finding linkage:** a safe client/company upload role and a per-finding "Request Evidence" affordance once a GL-finding detail page exists; optionally surface the open-evidence-request count in the readiness export area and add reviewer assignment/notification.
