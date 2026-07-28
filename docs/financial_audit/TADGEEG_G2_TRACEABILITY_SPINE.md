# TADGEEG-G2 — Traceability Spine (ISA 315 anchor)

> **Phase type:** New domain entity + service + API. One migration (`0033`). Frontend wiring deferred to G2.2.
> **Date:** 2026‑07‑28 · **Builds on:** `03d73a1` (G0/G1).
> **Honored:** additive · organization‑scoped · auditor‑only · **no ledger writes** · no AI · advisory (not an opinion).

---

## 1. Why
The review’s top domain gap (P0‑2): risk/procedure/evidence existed only as **stateless calculators** and opaque JSON snapshots (`EngagementPlanningRecord`, 9H), so there was no walkable audit chain. G2 introduces the chain’s **anchor entity** as a first‑class, linkable row:

```
AssessedRisk → (Control) → Procedure → Evidence → Finding → Report
   ▲ this slice (G2.1)        └── later slices (G2.2+)
```

## 2. What was built (G2.1 — the anchor)
`AssessedRisk` (`apps/audit/assessed_risk_models.py`, migration `0033`) — one persisted **risk of material misstatement** at the assertion level, engagement + organization scoped:
- `reference` (`RISK-00001`), `title`, `fs_area` (financial‑statement area), `assertion` (8 ISA assertions), `inherent_risk` (low/medium/high/significant), `control_risk` (low/medium/high), `is_significant`, `is_fraud_risk`, `description`, `notes`, `status` (identified → responded → tested → concluded → closed), `created_by`.
- Property `combined_risk` = `max(inherent, control)`; significant/fraud force `"significant"` — mirrors `isa330_risk_responses` so the two agree.
- `clean()` enforces `organization == engagement.organization`; unique `reference` per org.

## 3. Service — `services/assessed_risk.py`
`create_risk` (validates title, integrity‑safe numbering) · `set_status` (lifecycle transition) · `list_risks` (filter by status/assertion) · `summary` (counts by status + significant/fraud tallies). Deterministic; no ledger writes.

## 4. API (additive, org‑scoped, auditor+)
- `GET/POST /api/v1/audit/assessed-risks/` (list — filter `engagement`/`status`; create).
- `GET/POST /api/v1/audit/assessed-risks/<id>/` (detail; `status` transition).
- `GET /api/v1/audit/engagements/<id>/risk-summary/` (counts).

Junior → 403; cross‑org → 404.

## 5. Security & guardrails
Organization‑scoped everywhere (cross‑org → 404; `clean()` rejects mismatched org). Auditor‑only (`IsSeniorAuditorOrAbove`). **No ledger writes** (asserted). Deterministic; advisory working paper, not an opinion.

## 6. Tests
`apps/audit/tests/test_assessed_risk.py` (11): create/numbering/scoping, title required, `combined_risk` + significant/fraud, status transitions (+invalid), summary; API create/list/detail, status, summary, junior 403, cross‑org 404; no‑ledger‑writes. Regression: 572 audit tests pass.

## 7. What is NOT in this slice (next: G2.2)
- **Frontend:** a risk register page + wiring the ISA 315/330 pages to persist `AssessedRisk` rows (currently they still compute statelessly / snapshot to 9H).
- **Links:** `Procedure` entity referencing a risk; linking `Evidence` (9F), `SubstantiveTestItem`, `AuditConfirmationRequest`, and a unified `Finding` back to the `AssessedRisk`.
- **Unify findings:** merge the three finding models (`GeneralLedgerRiskFinding`, `AuditControlDeficiency`, `auditing.AuditFinding`) — the riskier G2 step, done behind a flag.

Each is an additive slice on top of this anchor; the anchor ships first so nothing depends on unbuilt entities.

## 8. Recommended next
**G2.2** — risk register UI + Procedure entity linked to `AssessedRisk` + wire 9F evidence links up to the risk; then the findings‑register unification.
