# TADGEEG-FIN-AUDIT-5A — Audit Readiness / Opinion Preparation Workpaper

> **Phase type:** Additive. A non-final auditor aid that consolidates the SAD, management responses and proposed adjustments to help prepare an opinion.
> **Date:** 2026-06-23 · **Builds on:** `9707b15` (4B). · **Predecessors:** [4B](TADGEEG_FIN_AUDIT_4B_MANAGEMENT_RESPONSE_AND_PROPOSED_ADJUSTMENTS.md), [4A](TADGEEG_FIN_AUDIT_4A_SAD_MISSTATEMENT_ACCUMULATION_BACKBONE.md), [0B](TADGEEG_FIN_AUDIT_0B_RUNTIME_VERIFICATION_AND_SOURCE_OF_TRUTH.md).
> **Honored:** `apps.audit` canonical; reuse engagement + SAD; **no** formal opinion, **no** ISA-700 issuance, **no** AI, **no** ledger writes.

---

## 1. What was implemented

`AuditReadinessWorkpaper` (engagement-level) + `audit_readiness_workpaper` service that reads the current SAD, its items' management responses, open evidence requests, and proposed adjustments, then produces a **readiness conclusion** and a **cautious suggested opinion direction** (always "subject to auditor review") plus a legal disclaimer. Org-scoped DRF endpoints, read-only admin, tests, docs, migration `0021`.

## 2. Why this is NOT a formal audit opinion

The workpaper is an **AI-assisted preparation aid**. It never asserts "in our opinion"/"present fairly", never issues an unqualified/qualified/adverse/disclaimer opinion, and **never calls `ISA700OpinionService` to issue one**. Every output direction is phrased "…subject to auditor review", and a fixed disclaimer is stored on every record (see §6). A test asserts the unsafe phrases are absent from the serialized output.

## 3. Model/service decision

**Option A — new additive `AuditReadinessWorkpaper`.** The existing `WorkingPaper` is hash-chained/document-scoped (unsafe to overload), and the ISA-700 opinion service is the risky path we must avoid. The new model links to `engagement` + `sad_summary` and carries counts, materiality snapshot, JSON breakdowns, the suggested direction, and the disclaimer. `clean()` enforces org == engagement.org and sad_summary belongs to the engagement.

## 4. How SAD & management responses are used

The service (`generate_for_engagement`) loads the engagement's current `AuditDifferenceSummary` (raises `ReadinessError` if none) and its items, then computes:
- `adjusted` / `unadjusted` / `pending` (not_requested + pending) counts from `management_response_status`;
- `uncorrected_total = total_absolute_impact − adjusted_total`;
- open `needs_evidence` GL findings on the engagement;
- proposed-adjustment count/total/by-status.

It does **not** modify the SAD, its items, or the GL findings (verified by test). It is **idempotent** — one workpaper per engagement, regenerated in place.

## 5. Readiness conclusions & suggested directions

| Readiness conclusion | When | Suggested direction (cautious) |
|---|---|---|
| `not_assessed` | no usable materiality | `no_direction` |
| `no_accepted_differences` | 0 accepted, no open evidence | `likely_unmodified_subject_to_auditor_review` |
| `insufficient_evidence` | open `needs_evidence` findings (or 0 accepted + open evidence) | `insufficient_basis_subject_to_auditor_review` |
| `possible_material_impact` | uncorrected total ≥ overall materiality | `possible_modified_opinion_subject_to_auditor_review` |
| `unadjusted_differences_need_evaluation` | pending responses, or uncorrected total > trivial | `possible_modified_opinion_subject_to_auditor_review` |
| `differences_below_materiality` | accepted diffs all corrected / immaterial & responses concluded | `likely_unmodified_subject_to_auditor_review` |

All deterministic; no AI.

## 6. Legal-safe disclaimer

Stored verbatim on every workpaper (`legal_disclaimer`):

> "This workpaper is an AI-assisted audit readiness and opinion preparation aid. It does not constitute a formal audit opinion. The final audit opinion must be prepared and approved by a licensed auditor based on professional judgment and sufficient appropriate audit evidence."

Forbidden phrasing ("in our opinion", "present fairly", "...opinion issued", "disclaimer issued") is **not** produced; opinion *directions* are only ever "…subject to auditor review".

## 7. API behavior

Under `/api/v1/audit/`:

| Method · Path | Permission | Behavior |
|---|---|---|
| `POST engagements/<uuid>/audit-readiness/generate/` | auditor+ | Org-scoped; builds the workpaper from the current SAD (400 if no SAD). Returns it. |
| `GET engagements/<uuid>/audit-readiness/` | authenticated | The engagement's current workpaper (404 if none). |
| `GET audit-readiness/<uuid>/` | authenticated | Workpaper detail (org-scoped). |

Read-only after generation; **no final-opinion endpoint**.

## 8. Tenant isolation rules

Generate/view resolve the engagement scoped to `request.user.organization` (other org → 404); detail filters by org. The workpaper inherits org from the engagement. Tested: cross-org generate 404 (no workpaper created), cross-org detail 404.

## 9. Why the ISA-700 service was not used for issuance

`apps/reports/services/isa700_opinion_service.py` *generates a formal opinion* ("In our opinion … present fairly"), which is exactly the legal exposure flagged in 0B. This phase keeps that path untouched and instead produces a clearly-labelled preparation aid. Reworking the ISA-700 wording is a separate, dedicated effort.

## 10. Why the ledger is not modified

The workpaper only reads SAD/finding/adjustment data and writes its own row. It proposes nothing to post and touches no accounting truth. A test asserts zero new `ledger.Account`/`JournalEntry`/`JournalLine` rows after generation.

## 11. Test results

`pytest apps/audit/tests/test_audit_readiness_workpaper.py` — all readiness tiers + directions, pending-response handling, proposed-adjustment counting, disclaimer present, **unsafe opinion phrases absent**, SAD/findings immutability, idempotency, no-SAD error, `clean()` org check, API generate/view/detail org-scoped, cross-org denial, and no ledger writes. Full `apps/audit` suite re-run (see response §10).

## 12. Intentionally NOT implemented (out of scope)

Formal ISA-700 opinion issuance · automatic unqualified/qualified/adverse/disclaimer opinion · ISA-700 wording change · client-facing final opinion · workpaper PDF/export rendering · evidence upload · ledger posting · bank/VAT reconciliation · AI.

## 13. Recommended next phase

**TADGEEG-FIN-AUDIT-5B — ISA-700 wording remediation:** rework `apps/reports/services/isa700_opinion_service.py` output (and its templates) from auto-asserted opinions to an auditor-edited draft framed as "auditor review required / final opinion belongs to a licensed auditor", consuming this readiness workpaper as input. Optionally **5C — readiness/opinion export** (PDF/HTML of the workpaper with the disclaimer) and an **evidence-upload** phase tied to `needs_evidence`.

## 14. What NOT to change (carried forward)

No second `AuditEngagement`; no `apps/financial_audit`; no formal opinion / ISA-700 issuance or wording change; no ledger posting / `ledger.JournalEntry` change; no evidence upload this phase; no AI; no payments/subscriptions/CRM/Moyasar/manual-payments/legal-page changes; no production-readiness claim.
