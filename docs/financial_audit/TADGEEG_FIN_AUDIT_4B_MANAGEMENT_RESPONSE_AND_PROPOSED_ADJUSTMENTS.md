# TADGEEG-FIN-AUDIT-4B — Management Response & Proposed Adjustment Workflow for SAD Items

> **Phase type:** Additive. Management-response tracking + proposed-adjustment capture for SAD items (4A).
> **Date:** 2026-06-23 · **Builds on:** `65139ae` (4A). · **Predecessors:** [4A](TADGEEG_FIN_AUDIT_4A_SAD_MISSTATEMENT_ACCUMULATION_BACKBONE.md), [3B](TADGEEG_FIN_AUDIT_3B_GL_FINDING_REVIEW_WORKFLOW.md), [0B](TADGEEG_FIN_AUDIT_0B_RUNTIME_VERIFICATION_AND_SOURCE_OF_TRUTH.md).
> **Honored:** `apps.audit` canonical; reuse existing SAD item + `IsSeniorAuditorOrAbove`; **no** ledger posting, **no** formal opinion, **no** AI.

---

## 1. What was implemented

For each `AuditDifferenceItem` (an accepted audit difference): a controlled **management-response** workflow with an append-only trail, and **proposed audit adjustment** capture for documentation. Plus org-scoped DRF endpoints, read-only admin, tests, docs, migration `0020`.

`AuditDifferenceItem` already carried `management_response_status` (6 choices, from 4A), so it supports the workflow with no breaking change. Mirrors the 3B review-workflow pattern.

## 2. Management response statuses & transitions

| From | Allowed to |
|---|---|
| `not_requested` | pending |
| `pending` | agreed · disagreed |
| `agreed` | adjusted · unadjusted |
| `disagreed` | unadjusted |
| `adjusted` | — (final) |
| `unadjusted` | — (final) |

A non-empty **note is required** for `disagreed`, `unadjusted`, `adjusted`. Any other transition (or unknown status) → 400. `adjusted`/`unadjusted` are final in this phase.

## 3. Response history behavior

Each successful transition writes one `AuditDifferenceItemResponse` (`audit_difference_item_responses`): `item`, `summary`, `engagement`, `organization`, `from_status`, `to_status`, `actor`, `response_note`, `response_reason`, `metadata`, `created_at`. `response_reason` ∈ `management_agreed · management_disagreed · adjustment_to_be_posted_by_client · client_refused_adjustment · immaterial_unadjusted · pending_management_reply · other`. Append-only — strictly read-only in admin (`has_add/change/delete_permission = False`).

## 4. Proposed audit adjustment model

`ProposedAuditAdjustment` (`audit_proposed_adjustments`): `item`/`summary`/`engagement`/`organization`; `adjustment_type` (reclassification/accrual/correction/reversal/disclosure_only/other); `description`; `debit_account_code/name`, `credit_account_code/name`; `amount`; `currency`; `management_accepted` (nullable); `client_posted_reference`; `status` (draft/proposed/accepted_by_management/rejected_by_management/posted_by_client/not_posted); `proposed_by/at`; timestamps. `clean()` enforces org == engagement.org.

Service `create_or_update_adjustment` validates: tenancy, known type, **amount > 0**, currency (defaulted from the SAD/engagement snapshot when omitted), and **debit+credit accounts required unless `disclosure_only`**. Supports updating an existing adjustment via `adjustment_id`.

## 5. Why proposed adjustments do not post to the ledger

A proposed adjustment is the auditor's **documented recommendation**, not an approved entry. Posting is the client's decision in their own accounting system; we only **reference** it (`client_posted_reference`, `status=posted_by_client`). Writing to `ledger.JournalEntry` would corrupt the books and overstep the audit role. A test asserts zero new `ledger.Account`/`JournalEntry`/`JournalLine` rows after recording responses and adjustments.

## 6. API behavior

Under `/api/v1/audit/`:

| Method · Path | Permission | Behavior |
|---|---|---|
| `POST sad/items/<uuid>/management-response/` | auditor+ | Org-scoped transition; body `status`, `response_note`, `response_reason`; 404 cross-org, 400 invalid/missing-note. Returns updated item + response row. |
| `GET sad/items/<uuid>/responses/` | authenticated | Org-scoped response history (read-only). |
| `POST sad/items/<uuid>/proposed-adjustment/` | auditor+ | Create/update a proposed adjustment (no ledger entry). 400 on validation failure. |
| `GET sad/items/<uuid>/proposed-adjustments/` | authenticated | Org-scoped adjustments (read-only). |

## 7. Tenant isolation rules

Every endpoint resolves the SAD item scoped to `request.user.organization` (other org → 404, no disclosure); both services independently reject a cross-org actor. Trail/adjustment rows inherit org/engagement/summary from the item. Tested: cross-org response 404, cross-org service denial, `clean()` org checks.

## 8. Why this is still not an audit opinion

Recording management's response and documenting a proposed adjustment are **working-paper activities**, not the formation of an opinion. No ISA-700 opinion is generated and its wording is untouched. The SAD conclusion + these responses are *inputs* an auditor weighs; the final opinion remains the licensed auditor's.

## 9. Why evidence / workpapers are intentionally not implemented yet

Evidence upload (files supporting a response/adjustment) and workpaper generation (formal schedules) are separate phases with their own storage/permissions/rendering. This phase delivers only the response + proposed-adjustment data layer they will build on.

## 10. Test results

`pytest apps/audit/tests/test_audit_difference_response.py` — all response transitions + finality + note rules + one-trail-per-transition + cross-tenant denial + `clean()`; proposed-adjustment create/update, amount>0, normal-requires-accounts, disclosure_only-exempt, invalid-type, cross-tenant, engagement/org/summary linkage; API response + adjustment endpoints (org-scoped, 400/404); and no ledger writes. Full `apps/audit` suite re-run (see response §9).

## 11. Intentionally NOT implemented (out of scope)

Ledger posting / journal creation · formal ISA-700 opinion or wording change · workpaper generation · evidence upload · bank/VAT reconciliation · sampling · assertions matrix · AI · reopen of final response statuses.

## 12. Recommended next phase

**TADGEEG-FIN-AUDIT-5A — Opinion worksheet (auditor-edited, non-automatic):** consume the SAD conclusion + accepted/unadjusted differences + management responses into an auditor *worksheet* that proposes (but never auto-issues) an opinion direction, with explicit "auditor review required / final opinion belongs to a licensed auditor" framing. Separately, **rework the existing ISA-700 wording** away from auto-asserted opinions. Optionally precede with an **evidence-upload** phase tied to `needs_evidence`/responses.

## 13. What NOT to change (carried forward)

No second `AuditEngagement`; no `apps/financial_audit`; no ledger posting / `ledger.JournalEntry` change; no formal opinion or ISA-700 wording change; no evidence upload / workpaper this phase; no AI; no payments/subscriptions/CRM/Moyasar/manual-payments/legal-page changes; no production-readiness claim.
