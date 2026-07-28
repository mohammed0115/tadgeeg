# TADGEEG-FIN-AUDIT-9F — Evidence linkage (variances & confirmations → 6A)

> **Phase type:** Cross-module wiring — extends the 6A evidence request to two new targets. One migration (`0031`, additive nullable FKs).
> **Date:** 2026-07-28 · **Builds on:** `ea0b2df` (9D import).
> **Honored:** additive · organization-scoped · auditor-only · **no ledger writes** · no AI · **not an audit opinion** · existing 6A behaviour preserved.

---

## 1. What was implemented
Closes the loop between the newer audit modules and the existing evidence workflow: an auditor can now **raise a 6A evidence request directly from a flagged substantive variance (9D) or an external-confirmation discrepancy/no-reply (9C)**, and each source row shows whether evidence has already been requested. This is what makes the platform feel like one connected system rather than separate tools.

## 2. Model — `AuditEvidenceRequest` (widened, migration 0031)
Two new **nullable** FK targets, alongside the existing `gl_finding` / `sad_item`:
- `substantive_item` → `SubstantiveTestItem` (9D), `related_name="evidence_requests"`.
- `confirmation_request` → `AuditConfirmationRequest` (9C), `related_name="evidence_requests"`.

`clean()` was **widened, not changed in spirit**: each new target is validated to the same engagement + organization, and the "must link a target" rule now accepts any one of the four (GL finding / SAD item / substantive item / confirmation). Existing requests and all existing callers (which always pass a GL finding or SAD item) are unaffected — the rule was only relaxed, never tightened. No test asserted the old message, so nothing broke.

## 3. Service
- `evidence_request.create_evidence_request(...)` gained `substantive_item=None` and `confirmation_request=None` kwargs (backward compatible).
- `substantive_testing.request_evidence(item, actor, …)` — raises a `SUPPORTING_DOCUMENT` request linked via `substantive_item`; priority **high** when the item is a variance. Auto-titles from area + reference + variance.
- `confirmation_request.request_evidence(request, actor, …)` — raises a request linked via `confirmation_request`; reason `BANK_SUPPORT` for bank confirmations else `SUPPORTING_DOCUMENT`; priority **high** on a discrepancy. Auto-titles from type + number + party + difference.

Both reuse `create_evidence_request` (so the append-only event history, numbering, and client-assignment/notification all apply unchanged).

## 4. Frontend
- **Substantive register** (`/audit/substantive-testing/`): variance rows show a **📎 Request evidence** button; once linked, a **📎 N evidence** badge replaces it. Query prefetches `evidence_requests` (no N+1).
- **Confirmations** (`/audit/confirmations/`): discrepancy / no-reply rows show the same button → badge. Query prefetches `evidence_requests`.

Both wired through a new `action=request_evidence` branch in their existing POST handlers; auditor-only; the raised request appears in the normal 6A workflow.

## 5. Security & guardrails
Organization-scoped everywhere (cross-org target rejected in `clean()` — tested). Auditor-only. **No ledger writes** (asserted). Advisory — raising an evidence request neither resolves the variance/discrepancy nor posts anything; it starts a documentation trail.

## 6. Tests
`apps/audit/tests/test_evidence_linkage.py` (9): widened-clean (substantive-only valid, confirmation-only valid, no-target still rejected, cross-org rejected); `request_evidence` from a substantive variance and from a bank-confirmation discrepancy (link, reason, priority, reverse count); no-ledger-writes.
Frontend: `test_substantive_page.py` (+2 — variance offers button, request links + badge shows), `test_confirmation_pages.py` (+2 — discrepancy offers button, request links + badge shows).
Regression: **742 passed** (incl. 155 evidence/confirmation-core tests unaffected).

## 7. Intentionally NOT implemented
Auto-raising evidence requests (still an explicit auditor click) · reverse navigation deep-link from the evidence page back to the source item (the FK exists; a UI link is a later polish) · bulk "request evidence for all variances" · email dispatch of the raised request (the 6A notification hook already fires on create).

## 8. Recommended next
Remaining optional enhancements: PDF export (management letter 9B / audit plan 8H) via WeasyPrint · email dispatch for confirmations & management letter · persisting ISA 300/330/240 strategy/plan onto the engagement row · a deep-link column on the evidence page showing the linked substantive item / confirmation.
