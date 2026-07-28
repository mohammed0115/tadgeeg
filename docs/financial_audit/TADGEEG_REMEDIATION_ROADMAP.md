# Tadgeeg — Remediation Roadmap (Sequential Fix Groups)

> Converts every finding in [`TADGEEG_COMPREHENSIVE_PLATFORM_REVIEW.md`](TADGEEG_COMPREHENSIVE_PLATFORM_REVIEW.md) into **ordered groups executed consecutively**.
> **Rule:** each group is a coherent, shippable unit. Do **not** start a group before its dependencies are done. Each group ends green (tests pass, no regression) and is committed before the next begins.
> **Date:** 2026‑07‑28 · **Status:** plan only — no production code until you approve and pick the starting group.

**Legend** — Effort: S (≤1 day) · M (2–4 d) · L (1–2 wk) · XL (>2 wk). Risk: 🟢 additive/safe · 🟡 refactor · 🔴 data migration / behavior change.

---

## Execution order (at a glance)

```
G0  Foundation & De-risk        (🟢🟡, safe)          ── must be first
G1  Product Consolidation       (🔴, decision + merge) ── depends on G0
G2  Traceability Spine          (🟢🔴)                 ── depends on G1
G3  Engagement Mgmt & Review    (🟢🟡)                 ── depends on G2
G4  Client Experience           (🟡🔴)                 ── depends on G0 (roles)
G5  Bridge Invoice ↔ Engagement (🟡)                   ── depends on G2, G3
G6  Reporting & Opinion         (🟢)                   ── depends on G2, G3
G7  UX / UI System & IA         (🟡)                   ── depends on G1
G8  Arabic / RTL / a11y polish  (🟢)                   ── overlaps G7
G9  Performance & Scale         (🟡)                   ── depends on stable models (G2–G3)
G10 Test & Security Hardening   (🟢)                   ── continuous; gate before launch
```

Critical path: **G0 → G1 → G2 → G3 → (G5, G6)**. G4/G7/G8/G9/G10 can be interleaved once their dependencies clear.

---

## G0 — Foundation & De‑risk  *(no new features; pure hygiene + safety)*
**Why first:** removes risk and confusion before any real building.

### ⚠️ Status: PARTIALLY DONE — premises corrected after reading the code

Reading the repository corrected several G0 assumptions. What actually happened:

| Item | Original plan | Reality found | Decision |
|---|---|---|---|
| Remove 12 dormant apps | Delete (P2‑1, T‑5) | **Load‑bearing:** imported by *installed* apps (`platform_admin`→`storage_management` 51 refs; `vendor_dashboard`/`rule_engine`→`audit_engine` 45 refs; `reporting` 25). Deleting breaks startup. Worse smell than "dead": **imported‑but‑unregistered** (models used without being in `INSTALLED_APPS` → tables may not exist). | **NOT deleted.** Needs a deliberate untangling pass (map each import, register or replace), not blind deletion. |
| Collapse settings | One file (P2‑2, T‑3) | `settings.py` is shadowed/dead (package wins), but `DJANGO_SETTINGS_MODULE='finai_backend.settings'` is referenced in ~10 scripts; blast radius if wrong = total. | **Deferred** (risk > value for an autonomous pass). |
| Immutable audit trail | Build event log (§23) | **Already exists & is strong:** `ActivityLog` (append‑only, per‑org, **tamper‑evident hash chain**, edit‑forbidden) + `EvidenceAccess` (ISA 230 §A6). Findings already logged via `GeneralLedgerRiskFindingReview`. The *only* real gap: **engagement stage changes emitted no event.** | **DONE — wired** (below). |
| Monolith split | Split `page_views.py` (5758) | XL, high‑churn; unsafe to do blindly. | **Deferred** to its own incremental pass. |
| Central tenant scoping | Add mixin + enforce | Enforcement = broad risky refactor across 142 routes. | **Deferred** (adding an unused helper adds no value; adoption is the risky part). |

### ✅ Delivered in this pass (additive, safe, tested)
- `apps/audit/services/audit_trail.py` — a **defensive, reusable** helper that emits ISA‑lifecycle events into the existing `ActivityLog` hash chain (never raises into the caller).
- New `ActivityLog.Action` values `ENGAGEMENT_STAGE_CHANGED`, `FINDING_STATUS_CHANGED` (metadata‑only migration `0003`).
- Engagement `set_stage` (workspace) now writes a **hash‑chained, tamper‑evident** stage‑transition event (no event on a no‑op same‑stage submit).
- Tests: `apps/audit/tests/test_audit_trail.py` (6) — chained rows, chain links, never‑raises, workspace integration, no‑op skip. Regression: **769 passed**.

### ⏭️ G0 remainder (deliberate follow‑up passes — not blind)
1. **Untangle the imported‑but‑unregistered apps** (register or replace their imports; then remove truly‑dead ones). Own pass, behind review.
2. **Collapse settings** to one module (careful, tested).
3. **Split `page_views.py`** incrementally by domain.
4. **Central tenant‑scoping mixin + adoption** (paired with G7’s view refactor).

**Acceptance (revised):** stage changes write immutable events ✅; remaining items scheduled as their own passes with tests.

---

## G1 — Product Consolidation  *(the two audit engines)*

### ⚠️ Status: RE‑SCOPED — premise corrected, no risky merge needed

Reading the code corrected the review’s P0‑1 severity:

| Assumption (review) | Reality found | Consequence |
|---|---|---|
| Two competing "audit" homes confuse users | `/auditor/` (`apps.auditing`) is surfaced in `base.html` as **"Upload Document" under an "Invoices" section** — *not* as an "Audit" home. The UI collision is minor. | User‑facing confusion is **low**, not P0. |
| Merge/retire `apps.auditing` | It is a **live, self‑contained** AI document→GAAP/IFRS compliance feature (`AuditDocument`→`AuditFinding`, gpt‑4o). `apps.audit`/`apps.invoices`/`apps.frontend` **never import it**. | Merging/deleting would **destroy a working feature** for ~zero benefit. **Do not merge.** |
| Doubles maintenance | The real overlap is **functional**: two AI *document* pipelines — `apps.auditing` (doc→standards) vs `apps.invoices` (doc→fraud/OCR). | A **future** consolidation opportunity, not an urgent blocker. |

**Revised decision:**
- **Keep `apps.auditing` as‑is** (live, isolated, low‑risk). No merge, no deletion.
- **Developer clarity (docs only):** record the three distinct roles — `apps.audit` = ISA engagement audit · `apps.auditing` = AI document→accounting‑standards compliance · `apps.invoices` = invoice OCR + fraud. Removes the *code‑level* naming confusion (`audit` vs `auditing`), the only real smell here.
- **Defer** any invoice↔auditing pipeline consolidation to a deliberate, separately‑scoped project (not on the critical path).

**Net effect:** G1 drops from "#1 blocker / XL / 🔴" to **"documentation + de‑prioritise."** The freed priority goes to **G2 (traceability spine)** and **G3 (engagement mgmt & review)** — the genuine P0s. G1’s critical‑path status is removed.

---

## G2 — Traceability Spine  *(the core domain fix)*
**Why:** without linked Risk→…→Report, conclusions can’t be defended in an audit file.

| Covers | Findings |
|---|---|
| Persist `AssessedRisk`, `Control`, `Procedure` as linked entities (replace stateless calculators / opaque JSON) | P0‑2 |
| Unify the 3 finding models into one **Findings register** | P1‑1 |
| Link chain: Risk → Assertion → Control → Procedure → Evidence → Finding | P0‑2 |
| Wire existing 9F evidence links up to the risk/assertion | §12(e) |

**Effort:** XL · **Risk:** 🟢 new tables (additive) · 🔴 merging finding models (migration behind flag).
**Acceptance:** from any Finding an auditor navigates to its Procedure → Evidence → Risk in ≤3 clicks; one findings register; ISA 300/330/240 outputs become linked entities, not just JSON snapshots.

---

## G3 — Engagement Management & Review Governance
**Why:** you can’t run/review a real engagement today (stage only).

| Covers | Findings |
|---|---|
| `EngagementMember` (team, role‑on‑engagement, responsibilities, deadlines) | P0‑4 |
| Preparer → Reviewer → Partner **sign‑off** + review notes | P0‑3 (ISA 220/230) |
| Issue → owner → due date → remediation → **closure** loop | P1‑1 |

**Effort:** L · **Risk:** 🟢 additive models · 🟡 working‑paper UI changes.
**Acceptance:** a working paper cannot be signed off by its own preparer; an issue has owner+due+closure; an engagement shows assigned team + deadlines.

---

## G4 — Client Experience  *(auditor ↔ client collaboration)*
**Why:** there is no authenticated client today (token/FK only).

| Covers | Findings |
|---|---|
| First‑class **client user role** + org‑of‑type‑client model | P0‑5 |
| Authenticated client portal (upload TB / answer requests / see deadlines) | P0‑5 |
| Client dashboard | P1‑4 (client slice) |

**Effort:** L · **Risk:** 🟡 role model change · 🔴 if it touches tenant model.
**Acceptance:** a client logs in with their own account and fulfills an evidence request without a token link; client sees only their data (org‑scoped test).

---

## G5 — Bridge Invoice/Fraud ↔ Engagement
**Why:** turns the two islands into one product; leverages the OCR/fraud differentiator inside a real audit.

| Covers | Findings |
|---|---|
| Invoice/fraud signals become engagement **procedures / findings / evidence** | P1‑2 |
| Fraud/OCR analysis runs *inside* an engagement’s procedures | §29 direction |

**Effort:** L · **Risk:** 🟡.
**Acceptance:** a flagged invoice can be promoted to an engagement finding with its evidence attached and traced to a risk.

---

## G6 — Reporting & Opinion
**Why:** only a readiness workpaper + PDF exists; no formal report lifecycle.

| Covers | Findings |
|---|---|
| Report builder (draft → review → final), version history, approval | P1‑3 |
| Executive summary + findings + recommendations + management responses assembled from linked data | P1‑3 |
| ISA 700‑safe opinion handling preserved | (existing) |

**Effort:** M–L · **Risk:** 🟢 mostly additive.
**Acceptance:** a versioned report is assembled from the traceability spine and exported (PDF exists already); no "In our opinion" auto‑emission.

---

## G7 — UX / UI System & Information Architecture
**Why:** two competing homes, 142 flat routes, 3 style idioms.

| Covers | Findings |
|---|---|
| Engagement‑centric IA (single spine) + top‑level nav | §28–32, P1‑4 |
| One design system (spacing/typography/table‑first/semantic color) | P3‑1, §31, §33 |
| Role dashboards (auditor / admin) | P1‑4 |
| KPI hierarchy (KPIs answer a question or go) | §17, §26 |

**Effort:** XL · **Risk:** 🟡 (UI churn; do page‑by‑page).
**Acceptance:** one clear starting spine; unified components; each dashboard answers "what do I do next?".

---

## G8 — Arabic / RTL / Accessibility Polish
**Why:** Arabic‑first is a differentiator; don’t erode it.

| Covers | Findings |
|---|---|
| Remove hardcoded bilingual titles → `{% trans %}` only | P1‑6 |
| Translate remaining 216 msgids | §18 |
| RTL pass (tables, numbers, currency, dates, charts, LTR‑islands for IDs/emails) | §12 |
| Accessibility pass (ARIA, contrast, keyboard, focus) | §19 |

**Effort:** M · **Risk:** 🟢.
**Acceptance:** no English‑only strings in the Arabic UI where an Arabic term exists; RTL renders correctly incl. LTR‑islands; basic a11y checks pass.

---

## G9 — Performance & Scale
**Why:** list dashboards fan out N×(10+ queries); no full‑population strategy.

| Covers | Findings |
|---|---|
| Fix `_engagement_overview` N‑query fan‑out (aggregate/annotate/cache) | §24 |
| Index `extracted_data` JSON query paths; pagination everywhere | §24 |
| Full‑population strategy for exports/analytics at 10M invoices | §24 |

**Effort:** L · **Risk:** 🟡.
**Acceptance:** engagement list stays fast at 100s of engagements (query‑count test); documented scale plan.

---

## G10 — Test & Security Hardening  *(continuous; gate before launch)*
**Why:** verify the unverified; protect a financial product.

| Covers | Findings |
|---|---|
| E2E tests for the core journey (upload→analysis→finding→evidence→report) | §25 |
| Verify/fix file‑upload validation (type/size/AV), download auth for all doc types, rate limits, error leakage, secrets | §21 |
| Raise `--cov-fail-under` gradually; add client‑flow + permission tests | §25 |

**Effort:** L · **Risk:** 🟢.
**Acceptance:** core journey has E2E coverage; upload/download security items closed or ticketed; coverage gate raised.

---

## Recommended cadence

1. **G0** (foundation) — start here; unblocks everything, zero feature risk.
2. **G1 → G2 → G3** — the domain spine, in strict order.
3. Interleave **G4, G7, G8** once G0/G1 are done.
4. **G5, G6** after G2/G3.
5. **G9, G10** continuously; G10 gates launch.

Each group: branch → implement additively → tests green → commit → update this roadmap’s status → next group.

---

**Next step:** approve this grouping and tell me which group to start (recommended: **G0**). I will not modify production code until you do.
