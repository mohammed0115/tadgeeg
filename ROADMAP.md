# Tadgeeg → Enterprise Roadmap

This document tracks the path from the current state (post-audit-rounds, 18 active
audit rules, ZATCA QR detection, Materiality + Sampling tools) to a true
enterprise-grade audit platform comparable to SAP/Oracle for the GCC market.

**Total scope:** 8 features across **6 phases**, **~26 weeks**, **~52 person-weeks**.

---

## Executive summary

| Phase | Weeks | Features | Effort | Value |
|-------|-------|----------|--------|-------|
| 1 | 1–3   | Audit Hash Chain · Materiality polish · Working Papers      | 6 PW  | Legal-grade audit foundation |
| 2 | 4–7   | Mobile APIs · Custom Rule Builder UI                        | 8 PW  | Customer customisation + field ops |
| 3 | 8–11  | Continuous Auditing engine · Alert channels                 | 8 PW  | Real-time differentiator |
| 4 | 12–16 | ZATCA Live API · Certificate management                     | 10 PW | KSA legal mandate |
| 5 | 17–22 | Bank connectors · Reconciliation engine                     | 12 PW | Deep integrations |
| 6 | 23–26 | React Native mobile app                                     | 8 PW  | Field UX |

> Phases 5 and 6 can run in parallel with a second team. Critical path is 1 → 2 → 3 → 4.

---

## Phase 1 — Audit Foundation (Weeks 1–3, 6 PW)

### 1.1 Immutable Audit Trail Hash Chain (#8) — 2 PW · ✅ DONE

**Scope.** Make every audit-relevant event tamper-evident by chaining each row
to its predecessor via SHA-256. Any later edit, deletion or reordering breaks
the chain and is surfaced on a dedicated integrity page.

**Deliverables.**
- `HashChainMixin` adding `previous_hash`, `event_hash`, `chain_position`.
- Hash formula: `SHA-256(previous_hash + canonical_payload + iso_timestamp + organization_id)`.
- `pre_save` signal computes the hash before any write.
- `pre_delete` signal blocks deletes (or marks tombstone, depending on policy).
- New `/audit/integrity/` page that walks every chain in the org and reports any break.
- Optional "Integrity Certificate" PDF export with the chain head + signature.

**Acceptance.**
- Tampering with any event row in a SQL shell breaks `verify_chain()` and the UI flags the exact row.
- Two-month-old chain with 50k events verifies in < 5 s.
- Cross-tenant attempts (forging an event for another org) fail at chain verification.
- Tests: linear chain, tampering detection, cross-tenant isolation, idempotent re-save.

**Risks.** Postgres timing — signals fire inside the transaction; ensure SELECT
last-row-of-chain uses `SELECT … FOR UPDATE` to prevent races on concurrent inserts.

---

### 1.2 Materiality + Sampling polish (#6) — 1.5 PW · ✅ DONE

**Scope.** Extend the existing `materiality.py` and `sampling.py` services with
the judgment factors and error-projection numbers that turn them from a
calculator into a planning tool.

**Deliverables.**
- `judgment_factors` parameter (industry risk, control environment, prior misstatements, going concern).
- Multi-component allocation across segments / branches.
- Error projection: most-likely error + upper-error-limit (UEL) for sample evaluation.
- Working-paper PDF for each materiality computation, ready to attach to the file.

**Acceptance.**
- High-risk judgment factors automatically pull `pct_low` (more conservative).
- Multi-component allocation sums to 100%.
- Sample evaluation: 5 errors found in 60-item MUS sample → projection within 1% of theoretical.

---

### 1.3 Working Papers + Reviewer Sign-off (#7) — 2.5 PW · ✅ DONE

**Scope.** Persist auditor working papers with a 3-tier sign-off (Preparer →
Senior Reviewer → Partner). Locked papers are immutable (rely on the Phase 1.1
hash chain).

**Deliverables.**
- `WorkingPaper` model: reference, paper_type, status, content (JSON), attachments, sign-offs.
- `WPSignature` model: drawn / typed / X.509 cert-based.
- Templates: Lead Schedule, Substantive Test, Internal Control Test, PBC Request.
- Cross-references between papers (`WP-2026-AR-001` references `WP-2026-AR-200.3`).
- `/working-papers/` index, filter, export-as-bundle PDF.

**Acceptance.**
- Auditor creates → submits → senior reviews → partner signs → paper is locked.
- After lock, the chain hash blocks any edit at the model layer.
- Bundle PDF for an engagement contains all papers in reference order with signatures.

---

## Phase 2 — Mobile + Customisation (Weeks 4–7, 8 PW)

### 2.1 Mobile APIs (#4) — 3 PW · ✅ DONE

- JWT refresh-token rotation + revocation list — uses `simplejwt` with
  `ROTATE_REFRESH_TOKENS=True` + `BLACKLIST_AFTER_ROTATION=True`.
- Biometric token bound to device-keypair — `MobileDevice.biometric_pubkey`
  stores a PEM-encoded ed25519 / WebAuthn-COSE key. Sign-and-verify lives in
  a follow-up story; the foundation is in place.
- Push notifications via FCM and APNs — pluggable `BaseChannel` adapters
  (`FCMChannel`, `APNsChannel`, `MockChannel` default for dev).
- Offline action queue with idempotency keys — `IdempotencyKey` model caches
  (status, body) per (user, key) for 24h. Same key + same body = same response;
  same key + different body = 409.
- Multi-photo capture endpoint — Pillow merges N images into one PDF saved
  under `MEDIA_ROOT/mobile_captures/YYYY/MM/`, max 30 photos per request.

Endpoints under `/api/v1/mobile/`: `auth/login`, `auth/refresh`, `auth/logout`,
`devices/register`, `devices/biometric`, `inbox/`, `invoices/<id>/<action>/`,
`captures/`. Tests: 13/13 pass.

### 2.2 Custom Rule Builder (#5) — 5 PW · ✅ DONE

- JSON DSL implemented in `apps/audit/services/rule_dsl.py` — `when` / `then`
  with nested `all` / `any` / `not` combinators and 17 operators across four
  categories (comparison, string, list, existence). Bounded recursion depth
  (`MAX_DEPTH = 10`) so a malicious nesting can't blow the stack; never
  `eval()`'s anything; field paths support dotted notation
  (`line_items.0.amount`).
- Visual builder UI at `/audit/rule-builder/` — Alpine.js shell that drives
  the JSON via `/api/v1/audit/rule-builder/*` endpoints. Conditions are
  authored row-by-row with field/op/value drop-downs; combinator switches
  between AND / OR; the schema for fields + operators is fetched from
  `/api/v1/audit/rule-builder/dsl-schema/` so the UI stays in lock-step
  with whatever the back-end accepts.
- Sandboxed evaluator runs a draft rule against the last 100 invoices via
  `POST /rule-builder/<id>/test/` — returns per-row pass/fail plus aggregate
  trigger count + rate.
- Rule versioning lives on `CustomRuleDefinition.version`, auto-increments on
  every save; published rules are immutable to PUT (409). Admins can create
  a fresh draft as a "new version" if they need to change a published rule.
- Admin-only publish: only `Admin` and `Chief Audit Officer` roles can flip
  a rule to PUBLISHED. Drafts are sandbox-testable by everyone in the org.
- Audit-engine integration: `_evaluate_custom_rules()` in `apps/audit/audit_engine.py`
  loads every PUBLISHED DSL rule for the org and evaluates them alongside the
  built-in 18 rules. Triggers show up as `RuleResult` rows with
  `rule_id="CUSTOM-<8-hex>"` and the same severity → AuditCase plumbing. 23/23
  tests pass.

---

## Phase 3 — Continuous Auditing (Weeks 8–11, 8 PW)

### 3.1 Streaming engine (#1) — 5 PW · ✅ DONE

- Event bus in `apps/streaming/bus.py` — `publish(event_type, payload, stream, organization_id)`.
  Backed by Redis Streams when `REDIS_URL` is reachable; in-memory deque
  fallback for unit tests and single-process dev runs. Both backends offer the
  same API plus a `drain()` test helper. Streams: `invoices`, `audit`,
  `cases`, `dlq`. Maxlen-based trimming keeps Redis memory bounded.
- Workers in `apps/streaming/worker.py` — `handle_event()` for one event,
  `run_once()` for tests, `run_consumer()` for the long-lived loop. Each
  event is timed and a row is written to `StreamProcessingLog` so the dashboard
  can compute throughput, error rate, avg / p95 / max latency.
- Window detectors in `apps/streaming/detectors.py`:
  - **Velocity** — fires when a vendor exceeds N invoices in M minutes (default 10/60).
  - **Sudden-spike** — fires when an amount exceeds μ + kσ of the vendor's own
    last-30-day distribution (default 5σ, ≥5 historical samples required).
  - **Vendor concentration** — fires when one vendor crosses X% of the org's
    total spend in the last Y days (default 30%/30 days, ≥10 invoices).
  Each trigger persists an `AnomalyHit` row and re-publishes `audit.anomaly_detected`
  back to the bus so Phase 3.2 alert channels can fan out.
- Live-ops dashboard at `/audit/streaming/` — KPI strip (throughput, error rate,
  avg/p95/max latency, anomaly count), per-stream queue depth, recent hits
  table, time-window selector. Pipeline integration: every invoice upload
  publishes `invoice.uploaded` from `apps/invoices/services/processor.py`.
- Failure handling: the consumer writes any rejected entries to a DLQ
  stream so on-call can replay them. 11/11 tests pass.

### 3.2 Alert channels — 3 PW · ✅ DONE

- Five channel adapters in `apps/alerts/channels/` — `EmailChannel`,
  `SMSChannel` (Twilio when configured, mock fallback), `SlackChannel` and
  `TeamsChannel` (incoming-webhook JSON), and `WebhookChannel`
  (HMAC-SHA256-signed POST with retry).
- `AlertRule` + `AlertEvent` models in `apps/alerts/models.py`. Each rule
  has trigger filters (`trigger_type`, `trigger_detector`, `min_severity`),
  a list of channels, and a cooldown. Events persist every dispatch attempt
  including suppressed ones, so the audit trail of who-was-told-what is
  complete.
- `apps/alerts/dispatcher.py` — selects matching rules, applies the
  severity floor + per-detector filter, deduplicates via
  `(rule, dedup_key)` cooldown, fans out to channels, and writes one
  `AlertEvent` per (rule, channel). Channel failures are isolated.
- Streaming worker hook: every persisted `AnomalyHit` calls
  `dispatch_for_anomaly` automatically, so live anomalies route to the
  configured channels in real time.
- API at `/api/v1/alerts/*` — list / create / update / delete / test
  rules, view event log with status filter, acknowledge events. UI at
  `/audit/alerts/` (Alpine + form-driven channel editor + per-rule "Send
  test" button).
- 16/16 tests covering matching, cooldown, dispatch fan-out, channel
  fallbacks, HMAC signature verification, and the worker→dispatcher
  end-to-end.

---

## Phase 4 — ZATCA Live API (Weeks 12–16, 10 PW) · ✅ DONE

> Highest legal-risk phase. Errors here = ZATCA fines.

Implemented in `apps/zatca/`. Live network calls are gated behind
``settings.ZATCA_LIVE_MODE`` — when ``False`` (the default) every Fatoora
request short-circuits to a recorded mock so the rest of the pipeline
exercises end-to-end without a portal account. To go live, set
``ZATCA_LIVE_MODE=True`` and provide ``ZATCA_FERNET_KEY`` for cert/key
encryption at rest.

- **4.1** Certificate management — `EGSDevice` model + `crypto.generate_csr_and_key`
  (RSA-2048 with ZATCA's required Subject DN + custom-OID UTF8String SAN
  extensions, DER-encoded as ZATCA expects). Private key + CSID secret
  encrypted with Fernet before persistence. Onboarding hits
  `/compliance/csids` (live) or returns a fake CSID (mock). Renew flow
  exchanges compliance request id → production CSID. (2 PW)
- **4.2** UBL 2.1 XML generator — `ubl.render_invoice_xml` produces a
  schema-shaped invoice with PIH chain pointer, supplier + customer parties,
  tax totals, line items. `crypto.canonicalise_xml` + `hash_invoice_xml`
  feed the chain. TLV-encoded QR via `ubl.build_tlv_qr` (5 mandatory tags +
  optional hash + signature + public-key tags) with a `decode_tlv_qr`
  inverse for debugging. (3 PW)
- **4.3** Clearance + Reporting API — `ZATCAClient.clear_invoice`
  (B2B sync) and `report_invoice` (B2C async). Response parser
  normalises ZATCA's payload into `ZATCAResponse`. Rejection-code
  translator (`rejection_codes.py`) turns codes like `BR-KSA-09` into
  Arabic + English title / description / fix-hint via a seeded lookup
  table — auto-seeds on first dashboard load. (3 PW)
- **4.4** Compliance dashboard at `/compliance/zatca/` — KPI strip
  (cleared / reported / warning / rejected / pending / 30-day clearance
  rate), 5-step readiness checklist, certificate-expiry warnings (< 30
  days), top rejection causes table with fix hints, EGS device list with
  inline "Onboard" + "Renew" actions, recent submissions table. JSON
  endpoint at `/api/v1/zatca/dashboard/` powers the live counters. (2 PW)
- 14/14 tests covering CSR validity, Fernet round-trip, UBL rendering,
  TLV encode/decode, end-to-end onboarding + submission, hash-chain
  linkage between two sequential submissions, rejection-code
  translation, and the API role-gates.

**Dependency.** EGS registration approval from ZATCA can take 4–8 weeks; start the application **at the same time as Phase 1**.

---

## Phase 5 — Bank Connectors (Weeks 17–22, 12 PW) · ✅ DONE

Implemented in `apps/banking/`. Real network calls live behind each
adapter's live branch; the `mock` environment returns deterministic
synthetic data so the framework, reconciliation, and dashboard exercise
end-to-end without a commercial agreement.

- **5.1** `BaseBankConnector` (apps/banking/connectors/base.py) — abstract
  base with `authenticate`, `fetch_accounts`, `fetch_transactions`, plus
  `AccountInfo` / `TransactionInfo` dataclasses. Registry
  (`connectors/registry.py`) maps `bank_code → connector class`. (2 PW)
- **5.2** Five bank connectors (Al Rajhi, SNB, Riyad, SAB, BSF). Al Rajhi
  carries the live OAuth client_credentials path; the rest are
  mock-backed today and ready for live wiring once API credentials
  arrive. Common-name + IBAN format mimics the real Saudi shape. (6 PW)
- **5.3** Reconciliation engine in `apps/banking/reconcile.py` — four
  scoring signals (amount ±0.5%, date ±3d, reference contains, vendor
  fuzzy) summing to a 0–100 score with high (≥80) / medium (≥60) / low
  bands. `match_window` claims each invoice at most once. (3 PW)
- **5.4** Statement-upload fallback in `apps/banking/parsers.py` — CSV
  + XLSX with header-alias autodetect, best-effort PDF line-regex
  parser. Same `TransactionInfo` shape so persistence is shared with
  live connectors. (1 PW)
- API at `/api/v1/banking/*`: connections CRUD, sync, transactions,
  reconciliations (list / run / confirm / reject), statement upload.
  Dashboard at `/banking/` — KPI strip, connection table with inline
  Sync, reconciliation queue with Confirm/Reject. Credentials encrypted
  at rest via the same Fernet key as ZATCA.
- 14/14 tests cover registry, deterministic mock output, CSV parser,
  fuzzy scoring, end-to-end sync + recon, Fernet round-trip, API gates.

**Risk.** Each bank requires a commercial agreement and 4–12 weeks of onboarding outside our control. **Start commercial negotiations during Phase 1.**

---

## Phase 6 — React Native Mobile App (Weeks 23–26, 8 PW)

- **6.1** RN + Expo build, screens for Login (biometric + MFA), Approval Inbox, Invoice Detail, Capture, Notifications, Profile. (5 PW)
- **6.2** Offline mode — SQLite cache + queued actions with conflict resolution. (2 PW)
- **6.3** QA + App Store / Play Store distribution. (1 PW)

---

## Phase 7 — Tier-1 ERP gaps (post-Roadmap, ~33 PW)

Identified during the global-readiness review. None block the SMB / audit-firm
launch, but each is required before Tadgeeg can replace SAP/Oracle for an
enterprise customer.

### 7.1 General Ledger + Multi-currency core (5 PW) · ✅ DONE

Implemented in `apps/ledger/`. Models:

- `Account` — chart-of-accounts row with parent FK + `account_type`
  (asset/liability/equity/revenue/expense/statistical) driving normal-side
  semantics.
- `ExchangeRate` — per-org daily FX rates; `get_or_create_fx_rate()`
  walks exact → nearest-prior → identity → fallback so posting never
  blocks on a missing rate.
- `JournalEntry(HashChainMixin)` + `JournalLine` — balanced double-entry
  with debit/credit constraints + `idempotency_key` so the same posting
  call can repeat safely.

Service layer (`apps.ledger.services`):
- `ensure_default_accounts(org)` — seeds 28 standard accounts on first use.
- `post_entry(...)` — validates balance, fans into FX, writes header +
  lines atomically, posts (chain hash assigned) or leaves as draft.
- `post_invoice_to_gl(invoice, direction)` — sales (DR AR · CR Revenue
  · CR VAT Output) and purchase (DR Expense · DR VAT Input · CR AP)
  flows. Idempotent per `invoice:<id>:<direction>`.
- `post_bank_payment_to_gl(transaction)` — wires a reconciled bank
  debit/credit into the cash/AP/AR legs.
- `void_entry(entry, user, reason)` — generates a compensating mirror
  entry (both stay POSTED, net to zero on every account) — never edits
  the original.

Reports (`apps.ledger.reports`):
- `trial_balance(org, as_of)` — one row per account with debit + credit
  + signed balance, totals at the bottom, `is_balanced` flag.
- `general_ledger(org, code, from, to)` — per-account ledger with
  running balance, opening + closing.

API (`/api/v1/ledger/`):
- `GET /accounts/`, `POST /accounts/` (finance/admin role)
- `GET /entries/`, `POST /entries/`, `GET /entries/<id>/`,
  `POST /entries/<id>/void/`
- `POST /post-invoice/` { invoice_id, direction }
- `GET /trial-balance/?as_of=YYYY-MM-DD`
- `GET /general-ledger/<code>/?from=…&to=…`
- `GET /exchange-rates/`, `POST /exchange-rates/`

Dashboard at `/ledger/` — KPI strip (balanced/debits/credits/diff),
trial balance, recent entries.

19/19 tests cover: chart seeding · balance validation · idempotency ·
purchase + sale invoice posting · trial balance net-to-zero · general
ledger running balance · void compensation · post-lock immutability ·
chain linkage between two entries · FX fallback chain · multi-currency
base-amount conversion · API role gates.

### 7.2 Procurement workflow (PR → PO → GR → Inv) — 8 PW (deferred)

3-way matching is implemented in audit rule R007 today; full PR/PO
issuance + approval routing + GR posting is the next gap.

### 7.3 Tax engines for non-KSA jurisdictions — 10 PW (deferred)

ZATCA is complete (Phase 4). UAE FTA, EU VIES, US sales tax remain.

### 7.4 Period-close workflow — 6 PW (deferred)

Open/close periods, year-end roll-forward, FX revaluation entries.

### 7.5 HR / Payroll integration — 4 PW (deferred)

Today's payroll ingestion is read-only via the document-upload pipeline.

---

## Cost & resourcing estimate

| Resource | Effort | Cost |
|---|---|---|
| Senior backend engineer (Django + Postgres) | 30 PW | $30K – $50K |
| Frontend engineer (React + Alpine)          | 12 PW | $12K – $20K |
| Mobile engineer (React Native)              |  8 PW | $10K – $15K |
| DevOps (Redis/Kafka, K8s)                   |  4 PW |  $5K –  $8K |
| QA + security review                        |  4 PW |  $5K –  $8K |
| ZATCA compliance consultant                 |  2 PW |  $5K – $10K |
| **Development total**                       | **60 PW** | **$67K – $111K** |
| Bank integration / onboarding               | —     | $20K – $50K |
| ZATCA EGS license + HSM                     | —     | $5K – $15K |
| Apple + Google developer accounts + signing | —     | ~$200/year |

**Grand total:** **$90K – $180K over 6 months.**

---

## Phase-gate criteria

A phase is **closed** only when all of the following are true:

- ✅ All deliverables ship to staging.
- ✅ Tests pass at ≥ 90% (raised from current 116/117 baseline).
- ✅ Security review signed off (especially Phases 4 + 5).
- ✅ Performance benchmarks hit:
  - Phase 1: chain verify of 50k events < 5 s.
  - Phase 3: 1k concurrent uploads → all audited within 5 min.
  - Phase 4: ZATCA clearance round-trip < 5 s p95.
- ✅ Documentation: OpenAPI + dev notes for the new code.
- ✅ User-acceptance test with one beta customer.

---

## Status — current baseline (start of roadmap)

This is the state Tadgeeg ships at the moment this roadmap is written.

- **18 audit rules** active synchronously (R001–R018).
- **23 document types** routed end-to-end through the upload pipeline.
- **6 analytics charts** + **9 compliance frameworks** surfaced.
- **PDF / CSV / XLSX export**, **bulk approve/reject/flag**, **HTML reports** for Risk / Duplicates / Vendor / Spend.
- **ISA 320 materiality** + **ISA 530 sampling** with three methods (Random, Systematic, Monetary-Unit).
- **Cross-tenant isolation** is fail-safe; **R001 self-match** closed; **R005 / R017** correctly skip pre-mandate dates.
- **Test suite:** 116 / 117 passing (the one failure is a pre-existing UI string assertion unrelated to this work).

The roadmap below assumes this baseline. Each phase opens with a "Status" line that
should be updated as work lands.
