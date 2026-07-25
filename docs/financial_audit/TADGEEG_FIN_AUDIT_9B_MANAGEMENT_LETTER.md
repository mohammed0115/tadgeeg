# TADGEEG-FIN-AUDIT-9B — Management Letter (ISA 265)

> **Phase type:** New module — model + service + API (JSON/HTML letter) + auditor frontend. One migration.
> **Date:** 2026-07-25 · **Builds on:** `3538880` (9C).
> **Honored:** additive · organization-scoped · auditor-only · **no ledger writes** · no AI · **not an audit opinion** (ISA 265 communication).

---

## 1. What was implemented
A **control-deficiency register** and a generated **Management Letter** (ISA 265). The auditor records deficiencies in internal control, classifies each (material weakness / significant deficiency / other), captures management's response and status, and generates a letter grouped by significance — exportable as JSON or a standalone HTML document.

## 2. Model — `AuditControlDeficiency`
Engagement + organization scoped. Fields: `reference` (per-org `DEF-00001`), `title`, `area` (9 choices: financial reporting, revenue, procurement/payables, payroll, cash/treasury, inventory, fixed assets, IT general controls, other), `classification` (material_weakness / significant_deficiency / other_deficiency), `description`, `potential_effect`, `recommendation`, `management_response` + owner + `target_date`, `status` (open / management_responded / remediated / accepted_risk), an optional `gl_finding` FK (reuse of the 2B finding that surfaced it), and `identified_by`. `severity_rank` orders the letter most-severe-first.

## 3. Service — `services/management_letter.py`
`create_deficiency` · `record_management_response` (moves open → management_responded) · `set_status` · `build_management_letter(engagement)` (groups by classification, counts, disclaimer) · `status_counts`. The letter carries `not_an_opinion: True` and the ISA 265 disclaimer ("…does not modify the audit opinion…").

## 4. API (additive, org-scoped, auditor+)
`GET/POST /api/v1/audit/control-deficiencies/` · `GET/POST /api/v1/audit/control-deficiencies/<id>/` (detail + record response / set status) · `GET /api/v1/audit/engagements/<id>/management-letter/` (`?format=json|html`). Junior → 403; cross-org → 404. The HTML export reuses the 5D passthrough-renderer pattern.

## 5. Frontend
`/audit/management-letter/` (engagement-scoped, sidebar): classification/status KPIs, a "record a deficiency" form, a collapsible **deficiency register** with inline management-response and status controls, and **Export HTML / JSON** buttons that hit the letter endpoint. Reuses the module style; auditor-only. The HTML letter document (`management_letter/letter.html`) groups material weaknesses → significant → other with the ISA 265 disclaimer banner.

## 6. Security
Organization-scoped everywhere; foreign engagement/deficiency → 404. Auditor-only (`IsSeniorAuditorOrAbove` / `is_auditor`); juniors 403. Advisory — a communication under ISA 265, **not an opinion** (asserted the HTML export never emits "In our opinion"); no ledger writes; the optional `gl_finding` link is validated to the same engagement.

## 7. Tests
`apps/audit/tests/test_management_letter.py` (13): numbering, response moves status, empty-response rejected, set-status (+invalid), letter grouping/ordering + safe wording, status counts, API create/list/detail + record-response + **letter JSON & HTML** (+ no "In our opinion") + junior 403 + cross-org 404, and no-ledger-writes.
`apps/frontend/tests/test_management_letter_page.py` (7): login required, junior 403, create-deficiency, record-response + status, register render + export links, no-engagement and cross-org states.

## 8. Intentionally NOT implemented
PDF export (JSON + HTML only; PDF is a later WeasyPrint pass) · automatic derivation of deficiencies from findings (auditor-entered; the optional `gl_finding` link is manual) · deficiency versioning/history · email dispatch of the letter.

## 9. Recommended next phase
**9D** — inventory (ISA 501) / fixed assets / payroll audit modules; plus the deferred **ISA 300/330/240** list-builder UIs. Optionally add a WeasyPrint PDF export of the management letter and auto-suggest deficiencies from open GL findings.
