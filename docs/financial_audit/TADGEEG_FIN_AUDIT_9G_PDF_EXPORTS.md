# TADGEEG-FIN-AUDIT-9G — PDF exports (Management Letter + Audit Plan)

> **Phase type:** Export enhancement — adds PDF alongside existing HTML/JSON. **No model, no migration, no ledger writes.**
> **Date:** 2026-07-28 · **Builds on:** `e7d7765` (9F).
> **Honored:** additive · auditor-only · deterministic · advisory (not an audit opinion) · reuses the existing WeasyPrint infrastructure (8G/5D).

---

## 1. What was implemented
Downloadable, print-ready **PDF** for two auditor deliverables, reusing the same WeasyPrint pipeline already used by the readiness export:

- **Management Letter (ISA 265, 9B)** — the existing engagement endpoint gained `?format=pdf`, rendering the already-standalone `management_letter/letter.html` document to an attachment PDF.
- **Audit Plan (ISA 300, 8H)** — the stateless planning page gained a **Download PDF** button that re-runs the engine on submit and streams a PDF built from a new standalone print template.

## 2. Management Letter PDF
`EngagementManagementLetterView.get` (`apps/audit/views_management_letter.py`) now handles `format` ∈ {json, html, **pdf**}. The `pdf` branch renders `letter.html` → `weasyprint.HTML(string=…).write_pdf()` → `application/pdf` with `Content-Disposition: attachment; filename="management-letter-<code>.pdf"`. A `_PassthroughPDFRenderer` (`format="pdf"`, `media_type="application/pdf"`) was added to `renderer_classes` so DRF content negotiation accepts `?format=pdf` (otherwise negotiation 404s before the view runs; permissions still apply — junior → 403, cross-org → 404). If WeasyPrint is unavailable the endpoint returns **503** (callers fall back to HTML/JSON). Frontend: an **Export PDF** button beside Export HTML / JSON.

## 3. Audit Plan PDF
The `planning` view (`apps/frontend/isa_assessment_views.py`) gained an `export=pdf` POST branch: after building the strategy + plan, it renders the new standalone `templates/audit/isa/planning_pdf.html` and returns it via a shared `_pdf_response(html, filename, request)` helper (graceful `None` → inline error if WeasyPrint is missing). The planning form gained a second submit button `name="export" value="pdf"` ("Download PDF"). Still stateless — nothing persisted.

## 4. Print template
`planning_pdf.html` mirrors the `letter.html` house style: `<!DOCTYPE html>`, inline CSS, `@page { size: A4 }`, Arabic-capable font stack (`Noto Sans Arabic`/`DejaVu Sans`), an ISA-300 badge, an advisory banner, the strategy key–value block + communications list, and the procedure table. Self-contained (no external assets) so WeasyPrint renders deterministically.

## 5. Security & guardrails
Auditor-only on both (management-letter endpoint: `IsSeniorAuditorOrAbove`; planning page: `is_auditor`). Organization-scoped (cross-org engagement → 404). **No ledger writes**, no AI. Both documents carry the advisory / ISA-265 disclaimer wording — **not an audit opinion**.

## 6. Tests
`test_management_letter.py` (+2): `?format=pdf` returns `application/pdf` + `attachment` + `%PDF-` magic; junior → 403 and cross-org → 404 on the PDF route.
`test_isa_planning_pages.py` (+1): `export=pdf` POST returns `application/pdf` + `%PDF-`.
Regression: **745 passed**.

## 7. Intentionally NOT implemented
PDF for the ISA 330/240 list-builder outputs (the management letter + audit plan are the formal deliverables; the response/fraud tables are working aids) · server-side PDF archival/attachment to the engagement · custom letterhead/branding · emailing the PDF (a later dispatch enhancement).

## 8. Recommended next
Remaining optional enhancements: email dispatch for confirmations (9C) & the management letter (9B) · persisting ISA 300/330/240 strategy/plan onto the engagement row · a reverse deep-link column on the evidence page to the linked substantive item / confirmation (9F).
