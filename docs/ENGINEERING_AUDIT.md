# TADGEEG — Comprehensive Engineering Source-Code Audit

> **AUDIT ONLY.** No source file was modified, no commit was created during this audit.
> **Tree state:** `Dockerfile` and `Dockerfile.optimized` carry *uncommitted* edits from a
> prior task (adding `libzbar0`). They are excluded from findings-as-fixes and noted in OPS-001.
> **HEAD:** `8d5e10d`.

## Coverage and honesty statement

The system is **178,609 lines of Python across 1,078 files, 199 models, 405 API endpoints**.
An exhaustive 17-phase audit at that scale is a multi-week engagement. This document reports
**only what was verified against source or by live execution**. Phases not reached are marked
`UNVERIFIED` rather than filled with plausible prose.

| Phase | Status |
|---|---|
| 0 Inventory | ✅ VERIFIED |
| 3 Multi-tenancy | ✅ VERIFIED (live cross-tenant probe) |
| 6 Financial integrity | ⚠️ PARTIAL (money typing + rule arithmetic verified) |
| 10 Billing/quota | ⚠️ PARTIAL (gate located, not exercised) |
| 12 Security config | ⚠️ PARTIAL (secrets/CORS/headers verified; no OWASP sweep) |
| 14 Testing | ⚠️ PARTIAL |
| 17 Code quality | ⚠️ PARTIAL |
| 1, 2, 4, 5, 7, 8, 9, 11, 13, 15, 16 | ❌ **UNVERIFIED** |

---

## 1. Executive Summary

Tadgeeg is a large, genuinely implemented Django platform — not a UI shell. Tenant isolation on
the primary financial endpoints **holds under live attack**, money is stored as `Decimal`
throughout, secrets are not committed, and the test suite is substantial (249 files, 60,506 LOC)
and green apart from one explained failure.

The danger is not absence of features. It is that **several audit rules issue verdicts without
measuring anything**, and the platform until today **could not check whether an invoice adds up**.
For a financial-audit product, a rule that reports "✓" on data it never examined is worse than a
missing rule: a reviewer sees the tick and moves on.

**Verdict: GO WITH CONDITIONS for UAT. NO-GO for production with real customer financial data.**

---

## 2. PHASE 0 — Inventory (VERIFIED)

| Metric | Value | How measured |
|---|---:|---|
| Python files (excl. migrations) | 1,078 | `find apps core finai_backend -name '*.py'` |
| Python LOC | 178,609 | `find ... -exec cat + \| wc -l` |
| Django models | 199 | `django.apps.apps.get_models()` |
| Migrations | 156 | `find apps -path '*/migrations/*.py'` |
| URL patterns | 1,214 | resolver walk |
| API endpoints (`api/*`) | 405 | resolver walk |
| Page routes | 809 (575 = Django admin) | resolver walk |
| Templates | 261 | `find templates -name '*.html'` |
| Test files / LOC | 249 / 60,506 | `find -name 'test_*.py'` |
| Local apps | 37 | `INSTALLED_APPS` filter |

**Model concentration:** `audit` 41 · `documents` 36 · `cms` 15 · `rule_engine` 11 ·
`storage_management` 7 · `invoices` 6 · `billing` 6.

**API concentration:** `audit` 103 · `documents` 50 · `reports` 33 · `auth` 21 · `invoices` 19.

---

## 3. PHASE 3 — Multi-Tenancy (VERIFIED)

### ✅ Isolation holds on the live financial paths

Live probe: authenticated as `demo@finai.sa` (org *Demo Audit Firm*), requesting an invoice
owned by org *Mohammed Kamal* (`7df9e784-…`, total 2,438.00 SAR):

```
404  /api/v1/invoices/7df9e784-.../
404  /invoices/7df9e784-.../
404  /api/v1/invoices/7df9e784-.../download/
404  /api/v1/documents/7df9e784-.../
```

**No cross-tenant leak on any routed invoice or document endpoint.**

### Scan result

145 direct object lookups (`get_object_or_404`, `objects.get(pk=…)`) in production code;
87 carry no organization term on the same line. Two were examined in depth. **Both are dead
code** — see ARCH-001 and SEC-001. No exploitable IDOR was demonstrated.

⚠️ The remaining 85 candidates are **UNVERIFIED**. The scan is a starting list, not a finding.

---

## 4. Findings

### ARCH-001 — An entire app's API is unreachable

```text
Finding ID:  ARCH-001
Severity:    P2 — HIGH
Component:   apps.audit_engine
File:        apps/audit_engine/urls.py
Problem:     A DefaultRouter registers AuditJobViewSet ("jobs") and AuditResultViewSet
             ("results"), but no URLconf ever includes apps.audit_engine.urls.
Evidence:    grep -n "audit_engine" finai_backend/urls.py        -> no match
             grep -rn "audit_engine.urls" --include=*.py .       -> no match
             Resolver walk: AuditJob appears only under /admin/audit_engine/...
Impact:      The app is in INSTALLED_APPS, owns 4 models and migrations that exist in the
             production schema, and ships views + permissions that can never be invoked over
             HTTP. Dead surface that reads as implemented.
Root Cause:  Router authored, include() never added.
Fix:         Either include the router under /api/v1/audit-engine/ and tenant-scope it first
             (see SEC-002), or delete the app and its migrations behind a CTO decision.
Verify:      Resolver walk shows the routes; a live GET returns 200 for an owner and 404 across
             tenants.
```

### SEC-001 — Latent IDOR in unrouted report code

```text
Finding ID:  SEC-001
Severity:    P3 — MEDIUM (latent, NOT exploitable today)
Component:   Reports
File:        apps/reports/views/executive_report_views.py:115
Function:    ExecutiveReportDetailView._fetch_document_audit_data
Problem:     Invoice.objects.get(id=document_id) with no organization filter, returning
             company, total_amount, compliance_score, risk_score. document_id arrives straight
             from the URL. The class declares no permission_classes, inheriting only
             IsAuthenticated.
Evidence:    Resolver walk: only ExecutiveReportGenerate/Latest/PDF/HTML are routed.
             The class docstring advertises
             "GET /api/v1/reports/{document_type}/{document_id}/executive-report/"
             — a path no URLconf maps.
Impact:      None today: unreachable. Becomes a P1 cross-tenant financial disclosure the moment
             anyone routes it, and the docstring invites exactly that.
Root Cause:  View written and never wired; no tenant filter in the query.
Fix:         Add the organization filter now, whether or not it is routed.
Verify:      Cross-tenant GET returns 404 once routed.
```

### SEC-002 — Unscoped AuditFile lookup (dead, but the pattern is wrong)

```text
Finding ID:  SEC-002
Severity:    P3 — MEDIUM (latent)
File:        apps/audit_engine/views.py:86
Function:    AuditJobViewSet.run
Problem:     get_object_or_404(AuditFile, id=file_id) with no org filter. Line 89 then reads
             organisation = request.user.organization or audit_file.organization — so a user
             with an org would create an AuditJob under their OWN org while operating on
             another org's file.
Evidence:    Line 41 scopes the list queryset by organization; the run action does not.
Impact:      Dead today (ARCH-001). Cross-tenant processing if routed.
Fix:         Filter AuditFile by request.user.organization.
```

### FIN-001 — Audit rules that pass without measuring (the headline risk)

```text
Finding ID:  FIN-001
Severity:    P1 — CRITICAL
Component:   core/services/invoice_validator.py + apps/invoices/models.py
Problem:     Six rules return PASS on an invoice carrying nothing but model defaults.
Evidence:    run_all_rules() against an invoice with only defaults: 20 of 34 rules passed,
             validation_score 58.82. On the runtime database, vat_rate = 15 on 71 of 71
             invoices — a single distinct value — so VAT-001 has passed 71/71 and has never
             once discriminated.
             VAT-001 compares invoice.vat_rate (models.py default=15) against expected 15.
             CTL-003 is a literal ok = True.
             CTL-006 computes has_trail = invoice.audit_events.exists() and then passes a
             literal True to _rule(), ignoring its own evidence — and the audit trail is a
             sacred invariant per EXECUTION_TRACKER §1.
             INV-005 tests total_amount is not None on a field defaulting to 0, so the
             condition can never be false.
Impact:      An auditor sees "نسبة الضريبة 15.0% ✓" on a USD invoice with no VAT line. This is
             the archetype named in CLAUDE.md: a claim read as evidence.
Fix:         A precondition per rule: no extracted value ⇒ not PASS. Requires a third result
             state; score = n_passed / TOTAL_RULES and _record() accepts only a bool, so this
             is a result-structure change, not a one-line guard.
Verify:      docs/VAT001_SCAN.md holds the full 34-rule table.
Status:      OPEN — CTO decision pending.
```

### FIN-002 — Float arithmetic on money in reporting

```text
Finding ID:  FIN-002
Severity:    P2 — HIGH
Component:   Reporting / aggregation
Evidence:    65 sites cast Decimal money to float, e.g.
             apps/reports/services/invoice_audit_service.py:426
               total_amount = sum(float(inv.total_amount or 0) for inv in invoices)
             also :794, :800, :874, :881, :884, :940
Positive:    Storage is correct — every money column is DecimalField. The only FloatField
             found is price_discrepancy_pct (a percentage, acceptable).
Impact:      Binary float accumulation error in reported totals. Invisible on small sets,
             material on large ones, and these feed executive/spend reports.
Fix:         Aggregate in Decimal (or database Sum) and convert only at serialization.
```

### OPS-001 — QR scanning impossible in the shipped image

```text
Finding ID:  OPS-001
Severity:    P1 — CRITICAL (functional)
File:        Dockerfile
Problem:     libzbar0 is absent from the apt list. pyzbar is a ctypes binding; without the
             native library its import raises and qr_scanner.py disables QR scanning entirely.
Evidence:    Before install: ImportError: Unable to find zbar shared library.
             Runtime DB: has_qr_code = 1 on 0 of 79 invoices.
             DOC-004 and VAT-005 — both ZATCA e-invoicing rules — therefore fail on every
             invoice regardless of the document.
             qr_scanner.py:97 logs "Run: pip install pyzbar", which points at the wrong layer:
             pyzbar IS pip-installed.
Impact:      A ZATCA compliance platform cannot verify ZATCA QR codes.
Fix:         Add libzbar0 to the image (uncommitted edit already staged in the working tree).
Verify:      After install, scan_pdf_for_qr decoded a ZATCA TLV correctly (seller_name,
             vat_number, invoice_date, total_with_vat) — confirmed live this session.
```

### TEST-001 — A test that was green because an external service was down

```text
Finding ID:  TEST-001
Severity:    P2 — HIGH
File:        tests/test_upload_single_request.py::test_one_upload_creates_one_invoice
Evidence:    Passes with OPENAI_API_KEY disabled; fails with a working key (dup=1.00 from
             Tier-1 extraction). Demonstrated by two runs differing only in the key.
Impact:      Suite colour depends on whether an external API is reachable. Same archetype as
             EXECUTION_TRACKER §15.
Fix:         Pin the AI tier in the test rather than depending on ambient credentials.
```

### QUAL-001 — Silent failure sites

```text
Finding ID:  QUAL-001
Severity:    P3 — MEDIUM
Evidence:    59 occurrences of `except Exception:` followed by `pass`; 2 bare `except:`
             across apps/ and core/.
Impact:      Swallowed errors on a platform whose defect archetype is "a claim read as
             evidence". A silent except is a claim of success.
```

### QUAL-002 — Monolithic view module

```text
Finding ID:  QUAL-002
Severity:    P3 — MEDIUM
Evidence:    apps/frontend/page_views.py = 5,869 LOC. Next: document_report_service.py 1,968,
             apps/reports/views.py 1,675, apps/documents/typed_views.py 1,673,
             apps/invoices/views.py 1,415.
Positive:    TODO 3, FIXME 0, HACK 1 — unusually low debt markers for 178K LOC.
```

---

## 5. Positives (verified, not assumed)

- **Tenant isolation on live financial endpoints** — cross-tenant probe returned 404 on all four.
- **Money is `Decimal` at rest** — no money `FloatField` in any model.
- **Secrets hygiene** — `.env` is gitignored; no hardcoded secret literals in `apps/`, `core/`,
  `finai_backend/`; only `.example` files are tracked.
- **CORS is an explicit allowlist**, not `CORS_ALLOW_ALL_ORIGINS`. `X_FRAME_OPTIONS = DENY`.
- **Throttling configured** — anon 100/day, user 1000/day, plus per-endpoint rates.
- **Quota gate exists and is installed by monkey-patch** at `apps/billing/quota_gate.py`
  (`install_gate()` wraps `run_audit_compat`), with an explicit comment about the recursion
  hazard it previously caused.
- **Low debt markers** — 3 TODO, 0 FIXME across 178K LOC.
- **Test scale** — 249 files, 60,506 LOC; 4,077 passing.

---

## 6. Scoring — evidence-weighted

Scores are given only where evidence exists.

```text
Multi-Tenancy:        78/100   isolation holds live; 85 lookups unreviewed
Financial Integrity:  52/100   Decimal at rest, but rules pass without measuring (FIN-001)
                               and 65 float aggregations (FIN-002)
Audit Engine:         55/100   rules issue verdicts on unpopulated fields; one whole app dead
Security (config):    74/100   secrets/CORS/headers sound; no OWASP sweep performed
Testing:              66/100   large and green, but one test green for the wrong reason
Code Quality:         71/100   very low debt markers; one 5,869-LOC module; 59 silent excepts
DevOps:               58/100   ZATCA QR impossible in the image (OPS-001)

Architecture:         UNVERIFIED
Backend:              UNVERIFIED
Database:             UNVERIFIED
API (405 endpoints):  UNVERIFIED
AI Engineering:       UNVERIFIED
Billing:              UNVERIFIED (gate located, never exercised)
Performance:          UNVERIFIED
```

**No overall score is issued.** Averaging seven measured dimensions with nine unmeasured ones
would be exactly the kind of number this codebase's contract forbids: a figure that cannot be
recomputed from evidence.

---

## 7. GO / NO-GO

```text
Deploy to UAT?                    GO WITH CONDITIONS
Deploy to Production?             NO-GO
Onboard real customers?           NO-GO
Process real financial data?      NO-GO
Support enterprise customers?     NO-GO
```

**Why UAT is acceptable:** tenant isolation holds where it was tested, money is typed correctly
at rest, secrets are handled properly, and the suite is large and green. Nothing found would
corrupt another tenant's data.

**Why production is not:** FIN-001 means the platform can report a clean audit verdict on fields
it never read. On a financial-audit product that is not a bug class, it is a product-integrity
failure. OPS-001 means ZATCA QR compliance cannot be checked at all in the shipped image.

### Conditions to clear before production

| # | Condition | Finding |
|---|---|---|
| 1 | No rule may return PASS on an unextracted field | FIN-001 |
| 2 | `libzbar0` in the image; DOC-004/VAT-005 proven to measure | OPS-001 |
| 3 | Reporting aggregates in Decimal | FIN-002 |
| 4 | Route or delete `apps.audit_engine`; tenant-scope before routing | ARCH-001, SEC-002 |
| 5 | Add the organization filter in the report view regardless of routing | SEC-001 |
| 6 | `test_upload_single_request` must not depend on ambient credentials | TEST-001 |
| 7 | **Complete Phases 1, 2, 4, 5, 7, 8, 9, 11, 13, 15, 16** — production sign-off on 5 of 17 phases is not sign-off | — |

---

## 8. Remediation roadmap

- **Phase A — Blockers:** FIN-001 (rule preconditions, needs a third result state), OPS-001.
- **Phase B — Security:** SEC-001, SEC-002; review the 85 unexamined lookups; run a real OWASP
  API sweep against all 405 endpoints.
- **Phase C — Financial integrity:** FIN-002; retroactive decision on the 79 existing invoices
  whose stored figures predate the arithmetic rules.
- **Phase D — Architecture:** ARCH-001; split `page_views.py`.
- **Phase E — Performance:** UNVERIFIED — no N+1 or load analysis was performed.
- **Phase F — Testing:** TEST-001; assert business outcomes, not HTTP status.
- **Phase G — Production hardening:** backups, monitoring, health checks — UNVERIFIED.
- **Phase H — Enterprise:** not assessable until A–G close.

---

## 9. What this audit did **not** cover

Stated plainly so no one reads absence as a clean bill:

- 11 of 17 phases untouched.
- 85 of 87 candidate unscoped lookups unreviewed.
- 401 of 405 API endpoints not individually audited.
- 199 models: none audited for indexes, constraints, or delete behaviour.
- No N+1, load, or concurrency testing.
- No CI/CD, backup, or disaster-recovery review.
- No AI cost/token/quota enforcement testing.
- No state-machine verification for audit engagements.
