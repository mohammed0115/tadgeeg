# TADGEEG-FIN-AUDIT-9H — Persist ISA 300/330/240 planning to the engagement

> **Phase type:** New model + service + API + frontend wiring. One migration (`0032`).
> **Date:** 2026-07-28 · **Builds on:** `0192cfe` (9G).
> **Honored:** additive · organization-scoped · auditor-only · **no ledger writes** · no AI · **not an audit opinion** · existing 8H compute path unchanged.

---

## 1. What was implemented
The ISA 300/330/240 assessment pages (8H) computed the audit strategy/plan, risk-response mappings and fraud-response plan **deterministically but statelessly**. ISA 300 §12 (and 330/240 documentation) require these to be **documented** on the audit file. This phase lets the auditor **save a computed artifact onto an engagement** — a dated, attributable record — and see previously saved records for that engagement.

## 2. Model — `EngagementPlanningRecord` (migration 0032)
One uniform model for all three artifacts via a `kind` discriminator (`audit_plan` / `risk_responses` / `fraud_plan`). Engagement + organization scoped. Fields: `title` (a short human summary), `payload` (JSON — the engine output: strategy+plan / mappings / fraud plan), `inputs` (JSON — the parameters used, for reproducibility), `created_by`, timestamps. `clean()` enforces `organization == engagement.organization`.

## 3. Service — `services/planning_records.py`
`save_record(engagement, actor, kind, payload, inputs, title)` (validates `kind`, full-cleans, saves) · `list_records(engagement, kind=None)` · `delete_record` · `counts(organization, engagement=None)` (per-kind + total, for a workspace/dashboard). No engine logic — storage only.

## 4. API (additive, org-scoped, auditor+)
- `GET /api/v1/audit/engagements/<id>/planning-records/` (list; filter `?kind=`).
- `GET/DELETE /api/v1/audit/planning-records/<id>/` (detail / delete).

Junior → 403; cross-org → 404.

## 5. Frontend
Each ISA page (`/audit/isa/planning|responses|fraud/`) gains, **without changing the stateless compute path**:
- an optional **"Save to engagement"** `<select>` + submit button (shared `_eng_save.html`) — on submit it computes *and* persists the result for the chosen engagement;
- a **"Saved to engagement"** panel (shared `_saved.html`) listing prior records (title / kind / when / who) for the selected engagement;
- a green save notice.

Selecting no engagement and clicking save shows "Choose an engagement…" and persists nothing. Plain compute (and the 9G PDF/HTML exports) are entirely unaffected.

## 6. Security & guardrails
Auditor-only (`is_auditor` / `IsSeniorAuditorOrAbove`). Organization-scoped everywhere; cross-org engagement/record → 404, and `clean()` rejects a mismatched org. **No ledger writes** (asserted). Deterministic; the saved record is an advisory working paper, **not an audit opinion**.

## 7. Tests
`apps/audit/tests/test_planning_records.py` (11): save+list per kind (payload/created_by), unknown-kind rejected, counts, org-must-match, delete; API list+filter, detail+delete, junior 403, cross-org 404; no-ledger-writes.
`apps/frontend/tests/test_isa_planning_pages.py` (+6): save audit-plan / risk-responses / fraud-plan from the UI, save-without-engagement warns + persists nothing, saved-panel lists records, and **compute-without-save persists nothing** (guards the existing 8H path). Regression: **761 passed**.

## 8. Intentionally NOT implemented
Editing a saved record (records are immutable snapshots; re-save to supersede) · a frontend delete button (API supports delete; UI delete is a later polish) · surfacing planning-record counts in the 8A engagement workspace (the `counts()` helper is ready for it) · versioning/diffing between saved snapshots.

## 9. Recommended next
Remaining optional enhancements: surface `planning_records.counts()` in the 8A workspace planning section · a reverse deep-link column on the 6A evidence page to the linked substantive item / confirmation (9F) · email dispatch for confirmations (9C) & the management letter (9B).
