# Tadgeeg — Comprehensive Platform Review (Read‑Only Architectural Audit)

> **Type:** Read‑only review — no files were modified to produce it. **Date:** 2026‑07‑28.
> **Reviewer lenses:** Principal engineer · systems architect · financial‑audit product expert · UX/UI reviewer · security/quality reviewer · competitive‑gap analyst.
> **Evidence rule:** every claim about the current system cites real evidence (file / line / route / model). Competitor claims are labelled **Confirmed / Likely / Unknown** and are never fabricated.
> **Status:** Awaiting approval before any design or implementation.

> Scope note: Tadgeeg is ~154k LOC across ~50 app folders. This pass read the routing, settings, auth/roles, the AI layer, the evidence/security paths, and traced representative flows end‑to‑end, plus deep prior knowledge of `apps.audit`. Where inference (not verification) is used, it is stated.

---

## 1. Executive Summary

Tadgeeg is **not one product — it is three products fused in one repo**, sharing a tenant model but only loosely integrated:

- **(A) Invoice/document AI‑analysis & fraud engine** — `apps.invoices`, `apps.auditing` (routed `/auditor/`), `apps.rule_engine` (159 files), ~20 ERP document types. This is the **original core**.
- **(B) ISA financial‑audit engagement platform** — `apps.audit` (145 files) + the audit pages in `apps.frontend`. This is the **newer, most standards‑complete layer** (the recent 8A–9H work).
- **(C) A broad ERP/finance document surface** — dozens of `frontend` routes (purchase orders, payroll, VAT returns, journal entries…), `apps.ledger`, `apps.banking`, `apps.zatca`, `apps.payments`.

The single biggest issue is **not a missing feature — it is a product‑identity and coherence problem**: two parallel "audit" apps (`apps.audit` vs `apps.auditing`), ~12 installed‑but‑dead or dormant apps, a 5,758‑line monolithic view file, and a role model with **no first‑class client user**. The ISA layer (B) is genuinely strong on paper (broad standards coverage, excellent evidence integrity), but its **traceability chains are partial** and it is **not connected** to the invoice/fraud island (A).

**Verdict:** strong domain building blocks, weak product spine. The highest‑leverage work is **consolidation and traceability**, not new features.

---

## 2. What Tadgeeg Is Today

| Layer | Evidence | Nature |
|---|---|---|
| Invoice AI‑analysis / fraud | `apps/invoices/services/processor.py` (OCR → `analyze_invoice_risk` → `ai_risk` stored in `extracted_data`), `apps/rule_engine` (DSL + risk_engine 1257 LOC), `apps/audit/services/fraud_engine.py` | **Core (original)** |
| ISA engagement audit | `apps/audit/*` (engagement, GL findings, evidence, SAD, confirmations, substantive, management letter, planning records) | **Core (new, strongest standards coverage)** |
| ERP document surface | ~20 doc‑type routes in `apps/frontend/urls.py`, `apps/ledger`, `apps/documents/typed_views.py` (1669 LOC) | **Supporting / sprawling** |
| Billing/subscriptions | `apps/billing` (48 files), `SubscriptionRequiredMiddleware` | Supporting |
| AI governance | `apps/ai_safety` (`runtime.call_model`, budget, redaction, registry) | Supporting (good) |

**Product classification:** a **mix**, but the center of gravity reads as an **AI‑assisted invoice/transaction analysis platform that has grown an ISA audit‑engagement layer on top**. It is *not yet* a coherent "audit‑process management" product the way Caseware/TeamMate are.

**Core / Supporting / Experimental / Legacy:**
- **Core:** `apps.audit` (ISA), `apps.invoices` + `apps.rule_engine` (analysis/fraud), `apps.authentication`, `apps.billing`, `apps.frontend`.
- **Supporting:** `apps.documents`, `apps.ledger`, `apps.banking`, `apps.zatca`, `apps.analytics`, `apps.reports`, `apps.ai_safety`, evidence subsystem (inside audit).
- **Experimental/parallel:** `apps.auditing` (AI‑auditor/document‑validation engine at `/auditor/` — overlaps `apps.audit` conceptually), `apps.assistant`, `apps.streaming`.
- **Legacy / dormant (installed‑but‑no‑route or not installed):** `apps.audit_engine`, `apps.reporting`, `apps.cms`, `apps.file_management`, `apps.storage_management`, `apps.system_monitoring`, `apps.jobs`, `apps.leads`, `apps.workflow`, `apps.organization_admin/_settings/_users` (12 folder‑apps not in `INSTALLED_APPS`).

---

## 3. Current Architecture

- **Django monolith**, DRF for APIs, **server‑rendered templates** for the UI (245 templates), Celery (`finai_backend/celery.py`), Tailwind + Vite.
- **Settings indirection:** active config is the `finai_backend/settings/` *package* → `base.py` → `from finai_backend.settings_canonical import *`. A shadowed `finai_backend/settings.py` file and `settings_canonical.py` both exist — **confusing footgun** (`settings/__init__.py` picks `test.py` vs `base.py` by sniffing argv for "pytest").
- **31 installed apps**; ~12 folder‑apps dormant/legacy → **dead weight**.
- **Monolithic views:** `apps/frontend/page_views.py` = **5,758 LOC** (`run_audit` at line 2427); `documents/typed_views.py` 1669; `reports/views.py` 1595; `invoices/views.py` 1376; `authentication/views.py` 1035.
- **Routing** (`finai_backend/urls.py`): API under `/api/v1/*`; ISA API under `/api/v1/audit/`; invoice/AI auditor under `/auditor/` (`apps.auditing`); the whole server‑rendered UI under `''` (`apps.frontend`, 142 routes).
- **Two audit subsystems** with separate models: `apps.audit` (engagement‑centric) and `apps.auditing` (`AuditDocument`, `AuditFinding`, `AccountingRuleEvaluation`, `AIValidationDataset/Run`, document‑centric). They do not share a finding/evidence model.

**Architecture findings:** monolith view file (P1); settings indirection (P2); parallel audit apps (P1); dormant apps (P2); no shared "finding/evidence" abstraction across the two audit engines (P1 domain).

---

## 4. Current User Journeys

Roles are **all audit‑firm‑side** (`apps/authentication/models.py:116‑123`): `admin, cao, senior_auditor, junior_auditor, compliance_officer, finance_manager, external_auditor`. **No company/client user role.** New sign‑ups default to `junior_auditor` (`:128`).

- **Auditor (senior+/admin/cao)** — the only fully‑served journey. `/login/` → `/dashboard/` (invoice dashboard) → either the **invoice path** (`upload` → `run_audit` → `invoice_detail`/`audit_session_detail` → `reports`) or the **ISA path** (`engagement_list` → `engagement_workspace` → trial_balance/GL/SAD/evidence/ISA/substantive/confirmations/management_letter/readiness). Gated by `is_auditor` = `has_role_capability("approve_invoices")`.
- **Junior auditor** — logs in but is **403’d out of most audit surfaces**. Dead‑end role.
- **Company/Client user** — **no real journey.** Only client touchpoints are the **public evidence‑response** and **confirmation‑response** pages, driven by FK/token (`assigned_client_user`, `response_token`), not a logged‑in role.
- **Platform Admin** — `apps.platform_admin` (46 files) + Django admin (not deeply traced).

**Dead ends / missing transitions:** junior‑auditor has no meaningful capability set; no preparer→reviewer→partner sign‑off; client has no authenticated workspace.

---

## 5. Current Audit Workflow

Two disconnected workflows:

**(A) Invoice/transaction audit** (original): upload → `processor.py` (OCR/extraction → rule_engine validation + `analyze_invoice_risk` AI score → `InvoiceValidationResult`, `is_duplicate`, `ocr_confidence`, `extracted_data.ai_risk`) → statuses (`flagged`…) → `run_audit` re‑runs Stage‑3 engine only (`apps/audit/tasks.py:96`) → invoice audit report.

**(B) ISA engagement audit** (`apps.audit`): `AuditEngagement` stage machine (acceptance→planning→risk→fieldwork→review→eqr→reporting→archived) → materiality (ISA 320) → TB import + mapping → GL import + risk analysis (2B) → finding review (3B) → SAD (ISA 450) → evidence (ISA 500, 6A‑6D) → confirmations (ISA 505) → substantive (ISA 501) → management letter (ISA 265) → readiness workpaper (ISA 700‑safe) → planning records (ISA 300/330/240).

**The two never meet:** a flagged invoice/fraud signal in (A) does not become a GL finding or evidence item in (B). **Central domain gap.**

---

## 6. Domain Model Analysis

`apps.audit` entities: `AuditEngagement` → `GeneralLedgerRiskFinding`, `AuditDifferenceSummary/Item`, `AuditEvidenceRequest`(+`Attachment`,+`Event`), `AuditConfirmationRequest`, `AuditControlDeficiency`, `SubstantiveTestItem`, `EngagementPlanningRecord`, `AuditReadinessWorkpaper`, `TrialBalanceImport/Row`, `AccountMapping`, `GeneralLedgerImport/Row`, `ProposedAuditAdjustment`.

**Strengths:** UUID PKs, `organization` + `engagement` FKs, `clean()` org‑match validators, per‑org reference numbering, evidence versioning + SHA‑256.

**Gaps:**
- **No `Risk → Assertion → Control → Procedure → Evidence → Finding` spine.** `risk_decomposition`/`risk_matrix`/`isa330` are **stateless calculators**; only ISA 300/330/240 outputs are persisted as opaque JSON (`EngagementPlanningRecord.payload`, 9H), not as linked entities.
- **Findings siloed:** `GeneralLedgerRiskFinding` (2B) vs `AuditControlDeficiency` (9B) vs invoice `AuditFinding` (`apps.auditing`) are three unrelated "finding" concepts with no shared base.

---

## 7. Global Platform Benchmark (reference platforms)

Confidence reflects general product knowledge (live docs not fetched this pass).

- **Caseware** — engagement files, working‑paper hierarchy with sign‑off, TB + lead schedules, analytics (IDEA), roll‑forward. **Confirmed** leader in working papers + analytics.
- **TeamMate+** — engagement/project management, risk‑control matrices, procedures library, issue tracking + remediation, review notes, time/budget. **Confirmed** strong on audit *process*.
- **AuditBoard** — SOX/internal audit, risk‑control‑test linkage, issue management, collaboration, dashboards. **Confirmed** strong RCM + collaboration; **Likely** weaker external‑audit TB/GL substantive.
- **Workiva** — connected reporting/disclosure, controls, data lineage. **Confirmed** strong reporting/traceability; **Unknown** OCR fraud.
- **DataSnipper** — document extraction / tick‑and‑tie in Excel, evidence cross‑referencing. **Confirmed** closest analogue to Tadgeeg’s document‑extraction strength.

**Pattern all four share that Tadgeeg lacks:** an explicit **audit‑process spine** (engagement → RCM → procedure → working paper → sign‑off → issue → report) with **review hierarchy**. Tadgeeg has the pieces, not the linked spine.

---

## 8. Competitive Capability Matrix

Legend: ✅ present · ◐ partial · ✗ absent · “?” unknown for competitor.

| Capability | Tadgeeg (evidence) | Caseware | TeamMate | AuditBoard | Workiva | DataSnipper | Gap | Imp. |
|---|---|---|---|---|---|---|---|---|
| Engagement mgmt (team, stage, deadlines) | ◐ stage only; no team/deadlines/sign‑off | ✅ | ✅ | ✅ | ✅ | ✗ | P0 | High |
| Working papers + reviewer sign‑off | ◐ exists (ISA 230) but no hierarchy | ✅ | ✅ | ✅ | ✅ | ? | P0 | High |
| TB / GL import + mapping | ✅ | ✅ | ✅ | ◐ | ◐ | ◐ | Parity | — |
| Risk→Control→Procedure→Evidence linkage | ✗ (calculators; JSON only) | ✅ | ✅ | ✅ | ✅ | ✗ | P0 | High |
| Substantive procedures (inv/assets/payroll) | ✅ (9D) | ✅ | ✅ | ◐ | ✗ | ◐ | Parity | — |
| External confirmations (ISA 505) | ✅ (9C, tokenized reply) | ◐ | ✅ | ◐ | ✗ | ✗ | **Diff.** | High |
| Evidence request + integrity (SHA‑256, versioning) | ✅✅ (6A‑6D) | ◐ | ◐ | ◐ | ✅ | ✅ | **Diff.** | High |
| Document OCR / tick‑and‑tie | ✅ (`invoices/processor`) | ◐ | ✗ | ✗ | ◐ | ✅✅ | **Diff.** | High |
| Fraud analytics (dup/Benford/vendor) | ✅ (`fraud_engine`) | ◐ | ◐ | ✗ | ✗ | ✗ | **Diff.** | High |
| Findings/issue tracking + remediation | ◐ 3 siloed models; no closure loop | ✅ | ✅ | ✅ | ✅ | ✗ | P1 | High |
| Report builder + opinion + versioning | ◐ readiness + PDF; no report builder | ✅ | ✅ | ✅ | ✅ | ✗ | P1 | Med |
| Client portal (authenticated) | ✗ (token/FK only) | ◐ | ◐ | ✅ | ✅ | ✗ | P1 | High |
| Arabic‑first + ZATCA/KSA | ✅✅ (`LANGUAGE_CODE=ar`, `apps.zatca`) | ✗ | ✗ | ✗ | ✗ | ✗ | **Diff.** | High |

---

## 9–11. Gap Register (P0 / P1 / P2‑P3)

**P0 — prevents core function / professional use**

| ID | Area | Current | Expected | Evidence | Impact |
|---|---|---|---|---|---|
| P0‑1 | Product coherence | 3 fused products, 2 audit apps, 12 dead apps | One focused product + one audit engine | `INSTALLED_APPS`; `apps.audit` vs `apps.auditing`; `/auditor/` | Confuses users, doubles maintenance, blocks positioning |
| P0‑2 | Traceability spine | Risk/procedure/evidence not linked | Linked Risk→Assertion→Control→Procedure→Evidence→Finding→Report | `risk_decomposition`, `EngagementPlanningRecord.payload` | Cannot defend conclusions in an audit file |
| P0‑3 | Working‑paper sign‑off | No preparer/reviewer/sign‑off | Review hierarchy + sign‑off + review notes | `apps.audit` working papers | Fails ISA 220 governance |
| P0‑4 | Engagement management | Stage only; no team/deadlines | Team, responsibilities, due dates, completion | `engagement_models` | Can’t run a real engagement |
| P0‑5 | Client user | No client role; token/FK only | Authenticated client workspace | `authentication.Role`, `assigned_client_user` | No true auditor↔client collaboration |

**P1 — important for professional launch**

| ID | Area | Gap | Evidence |
|---|---|---|---|
| P1‑1 | Findings register | 3 siloed models, no follow‑up/closure | `GeneralLedgerRiskFinding`, `AuditControlDeficiency`, `auditing.AuditFinding` |
| P1‑2 | Invoice↔engagement bridge | Fraud/invoice signals never become findings/evidence | (A) vs (B) islands |
| P1‑3 | Report/opinion builder | Only readiness workpaper + PDF | `audit_readiness_export` |
| P1‑4 | Role dashboards | One invoice dashboard only | `page_views.py` |
| P1‑5 | Monolith view file | 5,758‑line `page_views.py` | file size |
| P1‑6 | AR/EN UI mixing | Hardcoded bilingual titles bypass locale | `templates/audit/*` |

**P2 / P3**

| ID | Gap | Sev |
|---|---|---|
| P2‑1 | Dormant apps removal (12) | P2 |
| P2‑2 | Settings triple‑file indirection | P2 |
| P2‑3 | Email dispatch for confirmations/letters | P2 |
| P2‑4 | Reverse deep‑link evidence→source | P3 |
| P2‑5 | Notifications/mentions in collaboration | P2 |
| P3‑1 | Design‑system unification (3 idioms) | P3 |

---

## 12–14. Audit‑Domain / Workflow / AI Gaps

**Audit‑domain:** (a) no persisted assessed‑risk register linked to procedures/evidence (P0‑2); (b) no reviewer sign‑off (P0‑3, ISA 220); (c) no issue‑remediation‑closure loop (P1‑1); (d) three finding models unmerged; (e) confirmations/substantive/deficiencies can link to evidence (9F) but **not to a risk/assertion**.

**Workflow:** junior‑auditor dead‑end; no client authenticated flow; no preparer→reviewer→partner transitions; invoice‑audit and engagement‑audit not bridged.

**AI:**
- ✅ **Good:** AI contained (~5 call sites), centrally wrapped by `apps.ai_safety.runtime.call_model` (budget guard, cost cap, redaction, model registry, `record_call`); **ISA layer is fully deterministic (no AI)** — correct for defensible conclusions.
- ◐ **Concern (Med‑High):** invoice `ai_risk`/`overall_risk_score` is stored (`extracted_data.ai_risk`) and consumed by `fraud_engine`, but a UI path showing *result → reason → rule/analysis → source data → evidence* for AI risk was **not verified**. If an auditor cannot drill from an AI score to its basis → **High‑risk explainability gap**.
- ◐ **Human review:** invoice statuses/manual‑review views imply human‑in‑the‑loop for invoices; unclear for AI narratives (`reports/services/ai_*`).
- Classification: invoice AI = **Analytical/Decision‑support**; report narratives = **Advisory**. Acceptable *if* explainability UI exists (verify).

---

## 15–19. UX / UI / Arabic‑English / RTL / Accessibility

**UX / IA:** two competing homes — invoice `dashboard` vs ISA `engagement_workspace` — and **142 flat routes** including ~20 ERP document pages. No single "where do I start" spine. **No role‑specific dashboards.** The 8A workspace is the right idea but sits beside the invoice product rather than being the app’s center.

**UI:** ≥3 style idioms coexist — `client_portal/_evidence_styles.html`, `audit/isa/_style.html`, `audit/modules/_shared.html`. KPI‑card‑heavy dashboards. Risk of "template‑ish" density over calm, professional financial UI.

**Arabic/English:** platform **is Arabic‑first** (`LANGUAGE_CODE="ar"`, `LocaleMiddleware`, `USE_I18N`, `locale/ar` = 3,655 msgids / **3,439 translated ≈ 94%**, compiled `.mo`) — a real strength. **But** newer audit templates hardcode bilingual titles ("Substantive Testing · الاختبارات الأساسية", "Management Letter · خطاب الإدارة") that bypass the locale system and violate the language rule; **216 untranslated msgids** remain.

**RTL:** ISA styles use logical properties (`inset-inline-*`) — good. Not audited: table number/currency/date alignment, chart direction, breadcrumbs, LTR‑islands (IDs/emails/invoice numbers). **Unverified — dedicated RTL pass needed.**

**Accessibility:** no evidence of ARIA/labels/focus review; forms use inline styles. **Unverified — likely gaps** (contrast, keyboard nav, screen‑reader labels). P2.

---

## 20. Permission / Role Findings

- Capability map (`authentication/models.py:194‑209`) is **invoice‑era** ("approve_invoices", "edit_invoice_data") reused to gate ISA pages. Only 5 capabilities; coarse.
- **Backend enforcement exists** (API `IsSeniorAuditorOrAbove`; frontend `is_auditor`) — not button‑hiding only. Good.
- **No client capability set**; junior auditor near‑powerless.
- **Tenant isolation is manual per‑view** (`organization=` filter ~54× in `apps/audit/*.py`). Works where applied, but **any missed filter = IDOR**. No global tenant‑scoping manager/mixin. **Security/architecture risk (P1).**

---

## 21. Security Findings

**Strengths (verified):**
- **Evidence download** is exemplary: `scoped_attachment(user, pk)` (org‑scoped → 404 on foreign; **anti‑IDOR**) + **SHA‑256 re‑verification before serving** + refuses corrupted bytes (409) + `DOWNLOADED` event + retention/expiry check (`evidence_lifecycle.py:134‑175`, `views_evidence_lifecycle.py:41‑66`).
- **MFA/TOTP** with **replay protection** (`last_totp_counter`) + **encrypted `mfa_secret`** at rest (`EncryptedCharField`) + login lockout (`failed_login_attempts`, `locked_until`).
- CSRF (Django) + DRF auth.

**Risks / unverified (pen‑test needed):**
- **P1:** manual per‑view tenant filtering (no central enforcement) → IDOR surface across 142 routes + many doc‑type views not all read.
- **Unverified P1/P2:** file **upload** validation (type/size/AV) in `processor.py`/`documents`; **download authorization** for non‑evidence doc types; rate limiting; error leakage; secrets (`.env` present in tree — confirm not committed).
- **P2:** `/auditor/` app and dozens of doc‑type endpoints not individually authorization‑audited.

**No P0 security issue confirmed**, but absence of central tenant enforcement is the thing most likely to hide one.

---

## 22–23. Data Integrity & Audit Trail

- **Integrity:** consistent org+engagement FKs + `clean()` validators in `apps.audit`; per‑org unique reference numbers; immutable evidence versions. **But:** cascade behavior on `Organization`/`Engagement` delete **unverified** (orphan/cascade risk); no DB‑level tenant constraint; concurrency ad‑hoc (retry loops on numbering).
- **Audit trail:** **append‑only `AuditEvidenceRequestEvent`** (created/assigned/submitted/reviewed/downloaded/verification_failed) is genuinely strong; `activity_logs.ActivityLog` for general events. **Gap:** no comprehensive immutable who/what/before/after trail for **finding status changes, stage changes, report issuance, permission/subscription changes** (ISA 230). Stage changes save with `update_fields` but produce **no event record**. **P1.**

---

## 24. Performance Findings (architectural)

- **Workspace/list aggregation:** `_engagement_overview()` runs many sub‑queries each (materiality, GL, SAD, evidence, assurance, analytics, readiness, +substantive/confirmations/deficiencies/planning). `engagement_list` runs it **per row for up to 200 engagements** (`engagement_workspace_views.py:174‑176`) → **N×(10+ queries)**. Fine at demo scale, **crawls at 100s of engagements**. **P1.**
- **Invoice processing** at 10M scale: OCR + AI per file is Celery‑chunked (reasonable); full‑population analytics/aggregates and exports are the likely bottlenecks; `extracted_data` JSON query indexing unverified.
- **No full‑population scale strategy** evident; 100‑company / 10M‑invoice **not yet supported without work**.

---

## 25. Test Coverage Findings

- **104 test files**; `apps.audit` = **24 files (~761 tests, all passing)** — ISA layer **well‑covered** (permissions, org‑scoping, cross‑org 404, no‑ledger‑writes, safe wording). Real strength.
- `apps.invoices`/`apps.auditing`/`apps.rule_engine` = **19 files** for a much larger surface → **relatively under‑tested**.
- Coverage gate `--cov-fail-under=45` (`pytest.ini`) is low.
- **Missing:** end‑to‑end journey tests, client‑flow tests, many doc‑type views. **P1 for the non‑audit half.**

| Workflow | Unit | Integration | Permission | E2E |
|---|---|---|---|---|
| ISA engagement (audit) | ✅ | ◐ | ✅ | ✗ |
| Evidence lifecycle | ✅ | ✅ | ✅ | ◐ |
| Invoice OCR→risk→report | ◐ | ◐ | ? | ✗ |
| Rule engine/DSL | ◐ | ? | ? | ✗ |
| Billing/subscription gate | ◐ | ◐ | ◐ | ✗ |

---

## 26–27. Design & Technical Findings

**Design:**
| Page | Component | Problem | Severity | Treatment |
|---|---|---|---|---|
| Global | Navigation | Two homes; 142 flat routes | P1 | Single engagement‑centric IA |
| Workspace | KPI + cards | 6 KPIs + 8 equal‑weight cards → no hierarchy | P1 | Prioritize “work to do” |
| Audit pages | Titles | Hardcoded "EN · عربي" bilingual titles | P1 | Localize via `{% trans %}` only |
| Global | Styles | 3 style idioms | P2 | One design system |

**Technical:**
| ID | Sev | Location | Problem | Root cause |
|---|---|---|---|---|
| T‑1 | P1 | `frontend/page_views.py` (5758) | Monolith view | Organic growth |
| T‑2 | P1 | `apps.audit` vs `apps.auditing` | Parallel audit engines | Two eras fused |
| T‑3 | P2 | `settings.py` + `settings/` + `settings_canonical` | Config indirection | Refactor residue |
| T‑4 | P1 | per‑view `organization=` | No central tenant scoping | Manual pattern |
| T‑5 | P2 | 12 dormant apps | Dead code | Abandoned experiments |

---

## 28–37. Proposed Direction (direction only — no mockups)

- **Product IA & Design System:** make the product **engagement‑centric**; one calm professional financial IA; one design system (spacing/typography/table‑first/semantic color); tables > cards; KPIs answer a question or are removed.
- **Design around Engagement (recommended):** `AuditEngagement` becomes the UX center. Everything hangs off it: **Overview → Planning → Financial Data → Risk (RCM) → Procedures → Evidence → Findings → Review/Sign‑off → Report**. The invoice/fraud engine becomes an **analysis tool inside** an engagement’s Procedures/Evidence (bridging island A into B).
- **Proposed navigation (top level):** الرئيسية · عمليات التدقيق · البيانات المالية · المخاطر · الإجراءات · الأدلة · الملاحظات · التقارير · التحليلات · الإدارة — **only after** consolidation.
- **Semantic color system:** tokens for Primary/Neutral/Success/Warning/Danger/Info; **separate scales for Severity vs Status vs Risk** (never one hue for two meanings).
- **Role dashboards:** Auditor (work due, reviews, open findings, missing evidence, risks) · Company/Client (requests, deadlines, statuses) · Admin (accounts, usage, anomalies). Requires a **client user role** first.
- **Competitive advantage to lean into:** Arabic‑first + KSA/ZATCA + **document OCR/fraud analytics fused into a real ISA engagement with best‑in‑class evidence integrity** — a combination none of the five reference tools offer together.

---

## 38–43. Change Scope (high‑level)

- **Backend:** persisted `AssessedRisk`, `Procedure`, unified `Finding`, `EngagementMember` (+role/task/deadline) + sign‑off events; a **central tenant‑scoping manager/mixin**; a **bridge** turning invoice/fraud signals into engagement findings/evidence.
- **Frontend:** collapse the two homes into the engagement cockpit; extract `page_views.py` into per‑domain modules; unify styles; remove hardcoded bilingual titles.
- **DB:** new tables for risk/procedure/finding/member/signoff + immutable event log for status/stage/report changes. **Migration risk:** additive tables safe; risky parts are **merging the three finding models** and **retiring `apps.auditing`** (data migration + route deprecation) — do behind flags.
- **Dependencies:** client role before role dashboards & portal; traceability entities before RCM UI; tenant‑scoping mixin before scaling routes.

---

## 44. Recommended Phases

- **Phase 0 — Consolidate & de‑risk (no new features):** remove 12 dormant apps; collapse settings; decide `apps.auditing` fate; add central tenant‑scoping; add immutable event log for stage/finding/report. *Exit:* one audit engine, one config, tenant enforcement, full audit trail.
- **Phase 1 — Traceability spine:** persist Risk→Assertion→Control→Procedure→Evidence→Finding; unify findings; wire 9F links to risks. *Exit:* auditor can walk the chain end‑to‑end.
- **Phase 2 — Engagement management & review:** team/roles/deadlines; preparer→reviewer→sign‑off (ISA 220/230); issue→remediation→closure. *Exit:* a real engagement can be run and reviewed.
- **Phase 3 — Client experience:** client user role + authenticated portal. *Exit:* true auditor↔client collaboration.
- **Phase 4 — Bridge the islands:** invoice/fraud analysis becomes engagement procedures/evidence. *Exit:* one product.
- **Phase 5 — UX/UI system + AR polish + performance:** unified design system, role dashboards, RTL/a11y pass, fix N‑query dashboards, remove AR/EN mixing.

## 45. Acceptance Criteria (examples)
- P0: zero dormant apps installed; one settings source; every audit list query provably org‑scoped (test); stage/finding/report changes produce immutable events.
- P1: from any Finding, navigate to its Procedure → Evidence → Risk in ≤3 clicks; single Findings register.
- P2: a working paper cannot be "signed off" by its preparer; issue has owner+due+closure.
- P3: a client logs in with their own account and fulfills a request without a token link.

---

## 46. Final Recommendation & Scores

| Dimension | Score | Why |
|---|---|---|
| **Product Readiness** | **52/100** | Strong pieces, but 3 fused products, 2 audit engines, 12 dead apps, no client role → not a coherent shippable product. |
| **Audit Workflow Maturity** | **60/100** | Broad ISA coverage in `apps.audit`, but no traceability spine, no sign‑off hierarchy, no issue‑closure loop. |
| **Technical Quality** | **58/100** | Clean service/test patterns in `apps.audit`; undermined by 5758‑line monolith, config indirection, dead code, manual tenant scoping. |
| **Security Readiness** | **64/100** | Excellent evidence integrity + MFA/TOTP + encryption; but no central tenant enforcement and large unverified surface. |
| **UX Maturity** | **47/100** | Two competing homes, 142 flat routes, no role dashboards, no client journey. |
| **UI Consistency** | **50/100** | Three style idioms, KPI‑heavy, hardcoded bilingual titles vs a 94% Arabic‑localized base. |
| **Competitive Readiness** | **45/100** | Real differentiators (Arabic/KSA + OCR/fraud + evidence integrity), but below parity on engagement mgmt, working‑paper review, findings/reporting. |

**TOP 10 BLOCKERS**
1. Two parallel audit apps (`apps.audit` vs `apps.auditing`) — decide/merge (P0‑1).
2. No persisted traceability spine (Risk→…→Report) (P0‑2).
3. No working‑paper preparer/reviewer sign‑off (ISA 220) (P0‑3).
4. No first‑class client user role/portal (P0‑5).
5. Thin engagement management (no team/deadlines/tasks) (P0‑4).
6. Three siloed finding models; no issue‑closure loop (P1‑1).
7. Invoice/fraud island not bridged to engagements (P1‑2).
8. No central tenant enforcement → IDOR risk surface (P1/security).
9. Incomplete immutable audit trail (stage/finding/report changes) (P1).
10. 5,758‑line monolith view + 12 dead apps → change risk (P1/P2).

**TOP 10 HIGH‑VALUE IMPROVEMENTS**
1. Make Engagement the UX + data center; fold invoice/fraud into it.
2. Persist the traceability spine as linked entities.
3. Add review hierarchy + sign‑off + immutable event log.
4. Introduce client user role + authenticated portal.
5. Unify findings into one register with remediation/closure.
6. Central tenant‑scoping mixin/manager.
7. Role‑specific dashboards (auditor/client/admin).
8. Remove dead apps + collapse settings + split monolith.
9. One design system + fix AR/EN hardcoded titles + RTL/a11y pass.
10. Fix N‑query dashboards for scale; add E2E tests for the core journey.

**Recommended target architecture:** a single **engagement‑centric ISA audit platform** where **invoice/document OCR + fraud analytics** is a first‑class *analysis capability inside procedures/evidence*, backed by a **persisted audit chain**, **review/sign‑off governance**, a **central tenant‑isolation layer**, and an **Arabic‑first design system** — retiring the parallel `apps.auditing` engine and the dormant apps.

---

**STOP.** No production files were modified. Awaiting approval of this review before proceeding to any proposed design or implementation. On approval, choose: (a) start with **Phase 0 consolidation**, or (b) produce the detailed **PROPOSED DESIGN DIRECTION** (IA + design system + page‑by‑page plan) first.
