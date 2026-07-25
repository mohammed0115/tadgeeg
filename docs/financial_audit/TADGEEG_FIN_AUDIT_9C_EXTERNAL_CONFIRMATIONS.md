# TADGEEG-FIN-AUDIT-9C — External Confirmations (ISA 505)

> **Phase type:** New module — model + service + API + auditor frontend + **public token-gated response page**. One migration.
> **Date:** 2026-07-25 · **Builds on:** `a7b322b` (9A).
> **Honored:** additive · organization-scoped · auditor-only (admin surface) · **no ledger writes** · no AI · no audit opinion · no authentication/billing changes.

---

## 1. What was implemented
An **external confirmation** workflow (ISA 505): the auditor creates a request for a customer/supplier/bank to confirm a recorded balance, sends it, records the reply, and **reconciles** the confirmed amount against the books — a difference outside tolerance is flagged as a **discrepancy** (never auto-posted). A secure per-request token backs a **public response page** so the external party can reply without an account.

## 2. Model — `AuditConfirmationRequest`
Engagement + organization scoped. Fields: `request_number` (per-org `CNF-00001`), `confirmation_type` (receivable/payable/bank/other), party name/reference/email, `recorded_amount`, `confirmed_amount`, `currency`, `tolerance`, `status`, `response_token` (unguessable UUID), timestamps (sent/responded/reviewed), requester/reviewer. Computed `difference` (recorded − confirmed) and `is_within_tolerance`.

**Status graph:** `draft → sent → responded → (matched | discrepancy)`, plus `sent → no_reply` and `* → cancelled` (non-final). Matched/discrepancy/no_reply/cancelled are terminal.

## 3. Service — `services/confirmation_request.py`
`create_confirmation` · `send` · `record_response` (callable by the auditor **or** the public party) · `reconcile` (classifies matched/discrepancy by tolerance) · `mark_no_reply` · `cancel` · `status_counts`. All transitions validated; recording a response computes the difference; reconciliation **only flags** — it never posts a correction.

## 4. API (additive, org-scoped, auditor+)
`GET/POST /api/v1/audit/confirmations/` · `GET /api/v1/audit/confirmations/<id>/` · `POST /api/v1/audit/confirmations/<id>/<action>/` where action ∈ send·record·reconcile·no_reply·cancel. Junior → 403; cross-org → 404.

## 5. Frontend
- **Auditor** `/audit/confirmations/` (engagement-scoped, sidebar + workspace): status KPIs, a create form, and a register with per-row actions (send / record / reconcile / no-reply) and the **secure response link** shown once sent. Discrepancy differences are highlighted.
- **Public** `/confirm/<uuid:token>/` — a standalone, branded, token-gated page (no login, `noindex`). The external party agrees with the stated balance or enters a different amount + comment; it records the response and thanks them. Already-responded and invalid-token states are handled.

## 6. Security decisions
- **Public page is intentionally anonymous** — verified safe: the billing `SubscriptionRequiredMiddleware` returns `False` for unauthenticated users ("Anonymous → other middleware handles login"), so the page is neither login- nor subscription-gated. No app chrome or other data is exposed — a token resolves to exactly one request and shows only that party's name, reference and the amount being confirmed (as an ISA 505 positive confirmation must).
- **Token is an unguessable UUID**; an invalid/unknown token is a 404. A response is only accepted while status is `sent` (single, idempotent reply).
- **Auditor surface is org-scoped and auditor-only** (`IsSeniorAuditorOrAbove` / `is_auditor`); cross-org is 404.
- **No ledger writes, no opinion, no auto-resolution** — a discrepancy is flagged for the auditor (asserted, incl. the public path).
- No authentication or billing code was modified.

## 7. Tests
`apps/audit/tests/test_confirmations.py` (14): numbering, full matched flow, discrepancy vs tolerance (and within-tolerance match), no-reply, cancel, invalid transitions, status counts, API create/list/detail + action flow + junior 403 + cross-org 404, and no-ledger-writes.
`apps/frontend/tests/test_confirmation_pages.py` (11): auditor login/junior/create-send-record-reconcile/secure-link/cross-org; **public** anonymous open, agree-records-recorded, differ-records-entered, invalid-token 404, already-responded blocked, and no-ledger-write on the public path.

## 8. Intentionally NOT implemented
Actual email dispatch to the party (only the link is generated; sending is a delivery/integration decision) · an append-only event trail (status + timestamps only) · attaching the returned letter as evidence (could link to 6A in a follow-up) · negative confirmations · sampling of the confirmation population.

## 9. Recommended next phase
**9B Management Letter (ISA 265)** — aggregate control deficiencies into a generated letter; and **9D** (inventory / fixed assets / payroll). Optionally wire confirmation email dispatch and link responses into the 6A evidence trail.
