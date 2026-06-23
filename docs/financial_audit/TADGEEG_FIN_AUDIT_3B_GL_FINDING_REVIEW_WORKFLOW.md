# TADGEEG-FIN-AUDIT-3B — GL Finding Review Workflow

> **Phase type:** Additive. A controlled auditor review workflow for `GeneralLedgerRiskFinding` candidates, with an immutable audit trail.
> **Date:** 2026-06-23 · **Builds on:** `cd7bda0` (3A). · **Predecessors:** [3A](TADGEEG_FIN_AUDIT_3A_MATERIALITY_INTEGRATION_FOR_GL_FINDINGS.md), [2B](TADGEEG_FIN_AUDIT_2B_GENERAL_LEDGER_RISK_ANALYSIS.md), [0B](TADGEEG_FIN_AUDIT_0B_RUNTIME_VERIFICATION_AND_SOURCE_OF_TRUTH.md).
> **Honored:** `apps.audit` canonical; reuse existing engagement/finding + `IsSeniorAuditorOrAbove`; **no** SAD, **no** evidence upload, **no** AI, **no** ledger writes, **no** ISA-700 wording change.

---

## 1. What was implemented

A safe, auditor-driven review workflow that moves a GL candidate finding through a fixed set of status transitions and records **one immutable trail row per transition**:
- `GeneralLedgerRiskFindingReview` audit-trail model;
- `apps/audit/services/gl_finding_review.py` transition service (allowed-transition map, note rules, atomicity);
- `POST .../risk-findings/<uuid>/review/` endpoint (auditor+, org-scoped);
- `latest_review`/`reviews_count` exposed on the finding serializer;
- read-only admin, tests, docs, migration `0018`.

The existing `GeneralLedgerRiskFinding` already had `status`/`reviewed_by`/`reviewed_at`/`reviewer_note` (2B), so it supports transitions with no breaking change. The implementation mirrors the project's existing `UpdateCaseStatusView` pattern (`APIView` + `[IsAuthenticated, IsSeniorAuditorOrAbove]` + org-scoped fetch).

## 2. Allowed status transitions

| From | Allowed to |
|---|---|
| `candidate` | accepted · dismissed · needs_evidence · escalated |
| `needs_evidence` | accepted · dismissed · escalated |
| `escalated` | accepted · dismissed |
| `accepted` | — (final) |
| `dismissed` | — (final) |

`accepted`/`dismissed` are **final** — no reopen in this phase (no safe reopen pattern exists yet; deferred). Any other transition (including `→ candidate` or an unknown status) is rejected with a 400.

## 3. Review reasons

`evidence_sufficient · false_positive · immaterial · needs_supporting_document · management_explanation_required · escalation_required · other` (defaults to `other`).

## 4. Audit-trail behavior

Each successful transition writes one `GeneralLedgerRiskFindingReview` (`audit_gl_risk_finding_reviews`): `finding`, `engagement`, `organization`, `from_status`, `to_status`, `reviewer`, `reviewer_note`, `review_reason`, `metadata`, `created_at`. The trail is **append-only** — strictly read-only in admin (`has_add/change/delete_permission = False`). The finding's `latest_review` + `reviews_count` are exposed read-only on the API.

## 5. Service & rules (`gl_finding_review.review_finding`)

`review_finding(finding, *, actor, to_status, reviewer_note="", review_reason="", metadata=None)`:
- validates `to_status` and `review_reason`;
- **tenant safety**: rejects an actor whose organization ≠ the finding's;
- enforces the transition map;
- **requires a non-empty note** for `dismissed`, `needs_evidence`, `escalated`;
- **atomically** updates `status`/`reviewed_by`/`reviewed_at`/`reviewer_note` (via `update_fields`) and creates the trail row;
- raises `GLFindingReviewError` (→ 400) for any invalid case.
- **Never** changes the original risk `score`/`severity` (2B) or any `materiality_*` field (3A); never uses AI; never writes to the ledger.

## 6. API behavior

| Method · Path | Permission | Behavior |
|---|---|---|
| `POST /api/v1/audit/general-ledger/risk-findings/<uuid>/review/` | auditor+ (`IsSeniorAuditorOrAbove`) | Org-scoped; body `status`, `reviewer_note`, `review_reason`. 404 if the finding isn't in the user's org; 400 on invalid transition or missing required note. Returns the updated finding + the created review row. |

The list/detail endpoints already include `status`, `reviewed_by`, `reviewed_at`, `reviewer_note`, the materiality fields, and now `latest_review`/`reviews_count`.

## 7. Permission & tenant isolation rules

Reviewing requires **auditor+** (`IsSeniorAuditorOrAbove`). The finding is fetched scoped to `request.user.organization` (other org → 404, no disclosure), and the service independently rejects a cross-org actor. The trail row inherits org/engagement from the finding. Tested: cross-org review denied (finding unchanged), missing-note 400, invalid-transition 400.

## 8. Why candidate findings remain separate from SAD

A review decision (accept/dismiss/…) records the **auditor's disposition** of a candidate; it is **not** a posted misstatement. Aggregating accepted misstatements against materiality to inform the opinion (SAD) is a separate model/phase. Keeping review state on the finding (plus a trail) leaves a clean, explicit input for a future SAD step without presupposing its design.

## 9. Why SAD is intentionally not implemented yet

SAD requires a dedicated accumulation model, rules for what counts as a misstatement vs a control/observation, and a link to the (reworded) opinion worksheet — all out of scope here. This phase deliberately stops at producing a reviewed, audit-trailed disposition.

## 10. Why original risk / materiality data is preserved

The 2B deterministic score/severity and the 3A materiality overlay are independent analytical signals; a human review decision must not silently overwrite them (an auditor and a later SAD step need the original machine assessment alongside the disposition). The service touches only review-state fields; a test asserts score/severity and `materiality_*` are unchanged after review.

## 11. Test results

`pytest apps/audit/tests/test_gl_finding_review.py` — all allowed transitions, finality of accepted/dismissed, invalid-transition + invalid-status rejection, note requirements (dismissed/needs_evidence/escalated), one-trail-row-per-transition with correct from/to, `reviewed_by/at/note` set, preservation of risk + materiality, cross-tenant actor denial, model `clean()` org check, API success/400/404 + cross-org denial, and no ledger writes. Full `apps/audit` suite re-run (see response §9).

## 12. Intentionally NOT implemented (out of scope)

Reopen of final statuses · SAD/misstatement accumulation · evidence upload · workpaper generation · report packs · ISA-700 wording · AI · sampling · assertions matrix · any ledger posting.

## 13. Recommended next phase

**TADGEEG-FIN-AUDIT-4A — SAD / misstatement accumulation:** aggregate `accepted` GL findings (with their materiality classification + amount) into an engagement-level Summary of Audit Differences, compared to overall/performance materiality, to feed an auditor opinion *worksheet* (still "auditor review required", no automatic licensed opinion). Optionally precede with a thin evidence-request workflow tied to `needs_evidence`.

## 14. What NOT to change (carried forward)

No second `AuditEngagement`; no `apps/financial_audit`; no SAD/evidence-upload/workpaper this phase; no overwrite of original risk/materiality; no AI; no ledger writes; no `ledger.JournalEntry` change; no payments/subscriptions/CRM/Moyasar/manual-payments/legal-page changes; no ISA-700 wording change; no production-readiness claim.
