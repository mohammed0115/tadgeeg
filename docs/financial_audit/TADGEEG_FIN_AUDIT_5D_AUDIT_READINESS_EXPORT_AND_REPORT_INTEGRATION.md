# TADGEEG-FIN-AUDIT-5D — Audit Readiness Export & Safe ISA-700 Draft Report Integration

> **Phase type:** Export / report-integration layer over the 5A workpaper and 5B-hardened ISA-700 wording. **No new models, no migrations.**
> **Date:** 2026-07-12 · **Builds on:** `12f2ad4` (5C). · **Predecessors:** [5A](TADGEEG_FIN_AUDIT_5A_AUDIT_READINESS_OPINION_PREPARATION_WORKPAPER.md), [5B](TADGEEG_FIN_AUDIT_5B_SAFE_ISA700_WORDING_HARDENING.md), [5C](TADGEEG_FIN_AUDIT_5C_ISA700_LEGACY_TEST_REPAIR.md).
> **Honored:** no formal opinion issued; no unsafe wording reintroduced; no evidence upload; no frontend; no AI; no ledger/payment/CRM changes; no production-readiness claim.

---

## 1. What was implemented
A safe, read-only **export layer** for the 5A `AuditReadinessWorkpaper`, plus a small **ISA-700 draft integration** that sources its suggested direction from the workpaper:

- **`apps/audit/services/audit_readiness_export.py`** — builds a structured, JSON-safe export payload from a workpaper and renders it to **JSON / HTML / PDF**. Pure read: never modifies the workpaper, SAD, items, findings, or adjustments; no AI; no ledger writes.
- **`templates/audit/audit_readiness_report.html`** — self-contained bilingual (EN/AR) template with the **disclaimer banner at the top**, SAD conclusion, difference/response/adjustment summaries, materiality snapshot, and the "Suggested Direction — Subject to Auditor Review" block. No formal-opinion labels.
- **`build_readiness_draft_from_workpaper()`** in `apps/reports/services/isa700_opinion_service.py` — maps `AuditReadinessWorkpaper.suggested_opinion_direction` → the internal ISA-700 `opinion_type` CODE and reuses the 5B-hardened, "subject to auditor review" prose builder. Returns `is_formal_opinion=False`, `subject_to_auditor_review=True`, `source_workpaper_id`, and the disclaimer.
- **Two API endpoints** (audit app, org-scoped, auditor+): export the latest workpaper for an engagement, or a specific workpaper by id.

## 2. Export decision (A/B/C)
**Option B — JSON + HTML + PDF.** WeasyPrint (`weasyprint>=62.3`, runtime 68.1) is already a project dependency and is used safely in `apps/reports/views.py` (`_render_report_pdf_bytes`). The export service reuses the same lazy-import WeasyPrint pattern; **no new PDF dependency was introduced.** PDF degrades gracefully to `501` if WeasyPrint is unavailable at runtime.

## 3. Export formats supported
| Format | How | Endpoint query |
|---|---|---|
| JSON (default) | `build_export_payload()` → DRF `Response` | `?format=json` or none |
| HTML | `render_html()` → `HttpResponse(text/html)` | `?format=html` |
| PDF | `render_pdf()` → WeasyPrint → `HttpResponse(application/pdf)` | `?format=pdf` |

The export payload contains: engagement info · SAD summary snapshot · readiness conclusion · suggested direction (subject to auditor review) · management-response summary · proposed-adjustment summary · unadjusted-differences summary · open evidence (`needs_evidence`) count · materiality snapshot · `generated_by`/`generated_at` · required disclaimer (EN + AR).

## 4. ISA-700 / readiness integration behavior
The `AuditReadinessWorkpaper` is the **preferred source** of the suggested direction. `build_readiness_draft_from_workpaper()` maps the workpaper direction to the ISA-700 code and feeds the hardened paragraph builder:

| Workpaper `OpinionDirection` | ISA-700 `opinion_type` code |
|---|---|
| `likely_unmodified_…` | `unqualified` |
| `possible_modified_opinion_…` | `qualified` |
| `insufficient_basis_…` | `disclaimer` |
| `no_direction` | `disclaimer` |

The `opinion_type` code is retained **only** as a compatibility/internal aid; the emitted prose and labels are draft directions ("subject to auditor review") and the payload carries `is_formal_opinion=False`, `subject_to_auditor_review=True`, `source_workpaper_id`, and the disclaimer. The draft is embedded in the export payload as `isa700_draft` (toggle via `include_isa700_draft`). This integration is small and additive — it does **not** modify `generate_opinion()` or any existing report flow.

## 5. Safe wording / disclaimer behavior
Every format is labelled **"Audit Readiness Report — Opinion Preparation Draft"** and **"Suggested Direction — Subject to Auditor Review"**, with **"Final Opinion Requires Licensed Auditor Approval"**. Each export includes the legal disclaimer (workpaper `legal_disclaimer` + `SAFE_DISCLAIMER_EN/AR`). Tests assert the absence of unsafe EN phrases (`in our opinion`, `present fairly`, `opinion issued`, `unqualified/qualified/adverse/disclaimer opinion issued`) and unsafe AR phrases (`في رأينا`, `تعرض بعدالة`, `تم إصدار رأي`, `رأي صادر`) in the JSON and HTML output.

## 6. API endpoints added
- `GET /api/v1/audit/engagements/<uuid:pk>/audit-readiness/export/` — latest workpaper for the engagement.
- `GET /api/v1/audit/audit-readiness/<uuid:pk>/export/` — specific workpaper.

Behavior: authenticated + `IsSeniorAuditorOrAbove` (matches the existing generate endpoint); **organization-scoped** — a workpaper/engagement in another org returns `404` and never leaks existence; optional `?format=json|html|pdf`. No final-opinion endpoint. (The `format` query param collides with DRF's reserved content-negotiation override, so the two export views declare passthrough `html`/`pdf` renderers; the views return plain `HttpResponse`, so those renderers are never actually invoked.)

## 7. Tests added/updated
New `apps/audit/tests/test_audit_readiness_export.py` (15 tests): payload required-sections · disclaimer present · direction subject-to-auditor-review · no unsafe EN/AR phrases (payload + HTML) · ISA-700 draft sourced from workpaper (correct compat code, not formal) · workpaper/SAD/items **not modified** by export · JSON export (by engagement + by id) · HTML export · PDF export (`%PDF`, skipped if WeasyPrint absent) · cross-org denial (both paths) · role gating (junior auditor → 403) · **no writes to ledger tables**. Existing 5A/5B/5C suites re-run unchanged.

## 8. Commands run
`git status` · `python manage.py check` · `python manage.py makemigrations --check` · `python -m compileall apps/audit apps/reports` · `pytest apps/audit/tests/test_audit_readiness_workpaper.py` · `pytest apps/reports/tests/test_isa700_wording_safety.py` · `pytest tests/test_isa700_opinion.py` · `pytest tests/test_report_generation.py` · `pytest apps/audit/tests/test_audit_readiness_export.py` (new) · `pytest apps/audit/tests/`.

## 9. Test/check results
See the phase response §9. Summary: `check` clean, `makemigrations --check` = No changes, `compileall` exit 0, all targeted suites pass. The project-wide coverage gate (45%) fails on narrow runs because only a subset of the codebase executes — this is a global threshold, **not** a test failure; reported honestly.

## 10. Intentionally NOT implemented
Formal opinion issuance · automatic final opinion · a final-opinion endpoint · evidence upload · bank/VAT reconciliation · frontend workspace · AI · ledger posting · payment/subscription/CRM changes · changes to the existing `generate_opinion()` report flow or its templates · new PDF dependency.

## 11. Recommended next phase
**TADGEEG-FIN-AUDIT-5E — Evidence-request workflow tied to `needs_evidence`:** let auditors attach/track evidence against open `GeneralLedgerRiskFinding` (NEEDS_EVIDENCE) so the readiness conclusion can move off `insufficient_evidence`. Separately, a review/sign-off workflow (`reviewed_by`/`reviewed_at`) and optional archival of exported PDFs as immutable workpaper attachments.

## 12. What NOT to change (carried forward)
No formal opinion issuance; no `in our opinion`/`present fairly`/`opinion issued` (or Arabic equivalents) in automated output; no removal of compatibility fields; no evidence upload; no frontend; no AI; no ledger/`JournalEntry` writes; no payments/subscriptions/CRM/Moyasar/manual-payments/legal-page changes; no production-readiness claim.
