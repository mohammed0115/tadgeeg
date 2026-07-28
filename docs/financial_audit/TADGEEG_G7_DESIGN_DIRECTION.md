# TADGEEG-G7 — Proposed Design Direction (to unblock G7)

> **Direction only — no mockups, no code.** This is the decision artifact that unblocks G7. Once approved, the page‑by‑page rework proceeds as additive slices.
> **Principle:** the product must feel **calm, precise, and professional** (a financial‑audit tool), not a dense KPI/crypto dashboard.

---

## 1. Information Architecture — engagement‑centric
Collapse the two competing homes (invoice `dashboard` vs `engagement_workspace`) into **one spine anchored on the Engagement**. Top‑level navigation (Arabic‑first labels):

```
الرئيسية            (role-aware home)
عمليات التدقيق       Engagements  ← the center
  └─ داخل الارتباط:  نظرة عامة · التخطيط · البيانات المالية · المخاطر ·
                    الإجراءات · الأدلة · الملاحظات · المراجعة · التقرير
التحليلات           Analytics (journal + invoice/fraud as a tool INSIDE procedures)
الإدارة             Admin (users, org, billing)
```

Everything hangs off the engagement; the invoice/fraud engine becomes an **analysis tool inside Procedures/Evidence** (G5), not a separate home. The ~20 flat ERP document routes move under **البيانات المالية** inside an engagement, not top‑level.

## 2. Role‑aware home (not one dashboard)
- **Auditor:** "what needs me" — assigned procedures, reviews due, open findings, missing evidence, significant risks, stage.
- **Client (G4):** only "requests to fulfil, deadlines, statuses" — the FK‑scoped portal is their home.
- **Admin:** accounts, usage, anomalies, billing.

Each KPI must answer a question or be removed. No 6‑equal‑weight KPI rows.

## 3. Design system (tokens — one set, not many variants)
- **Spacing:** 4px base scale (4/8/12/16/24/32). Generous whitespace; section spacing ≥ 24px.
- **Container:** max‑width ~1180px; content not full‑bleed.
- **Radius:** one card radius (12px), one control radius (8px).
- **Typography:** one Arabic‑first family (e.g. the existing Cairo/Noto stack). Heading scale 24/18/14; body 13–14; table 12–13. Numbers tabular. No tiny‑text density hacks.
- **Elevation:** one subtle card shadow; borders `#e8edf3`. No glow, no decorative gradients (hero gradients only on section headers, sparingly).

## 4. Semantic color system (separate scales per meaning)
Never reuse one hue for two meanings. Define **distinct** scales:
- **Status** (workflow): neutral/blue/green/amber/red mapped to draft/in‑progress/done/attention/blocked.
- **Severity** (findings): low→green, medium→amber, high→orange, critical/material→red.
- **Risk** (assessed): low/medium/high/significant — its **own** ramp (e.g. teal→amber→orange→red), visually distinct from severity so "high risk" ≠ "high severity" by accident.
- Brand primary reserved for navigation/primary actions only.

Deliver as CSS custom properties (`--status-*`, `--sev-*`, `--risk-*`) so the three current style idioms (`_evidence_styles`, `isa/_style`, `modules/_shared`) converge on **one** token file.

## 5. Tables first (Tadgeeg is table‑heavy)
Tables are more important than cards. Standard table: sortable columns, sticky header, inline status chips, right‑aligned tabular numbers, row actions, pagination; a defined mobile pattern (stacked key/value, not card‑soup). Do **not** turn desktop tables into cards.

## 6. Component inventory (one variant each)
Buttons (primary/secondary/ghost/danger), form fields (label+help+error), table, status/severity/risk chips, tabs, card, drawer (for detail), modal (confirm only), toast, empty state, skeleton loader, breadcrumb. That's the whole kit — resist proliferation.

## 7. Arabic / RTL / a11y (baked in, see G8)
Logical properties everywhere; LTR‑islands for IDs/emails/invoice numbers/codes; tabular numerals; correct date/currency direction; localized via `{% trans %}` only (remove hardcoded "EN · عربي" titles); AA contrast; keyboard + focus + ARIA on interactive components.

## 8. What G7 execution looks like (after approval, additive)
1. Ship the **token file** + converge the 3 style idioms onto it (no visual regression tests first).
2. Rebuild the **engagement Overview** as the spine home (reuse existing data).
3. Standardize **one table component**; migrate module pages to it.
4. Role‑aware homes (auditor/client/admin).
5. Page‑by‑page: risk register → procedures → evidence → findings → report.

Each step is a separate, reviewable slice — **no big‑bang redesign.**

---
**Decision needed to start G7 execution:** approve (a) the engagement‑centric IA, (b) the three‑scale semantic color model, and (c) tables‑first. On approval I begin with the token file + engagement Overview.
