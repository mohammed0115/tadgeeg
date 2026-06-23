# TADGEEG-FIN-AUDIT-5B — Safe ISA-700 Wording Hardening

> **Phase type:** Wording hardening (legal safety) of the existing ISA-700 report service. No new models, no migrations.
> **Date:** 2026-06-23 · **Builds on:** `62d40d2` (5A). · **Predecessors:** [5A](TADGEEG_FIN_AUDIT_5A_AUDIT_READINESS_OPINION_PREPARATION_WORKPAPER.md), [0B](TADGEEG_FIN_AUDIT_0B_RUNTIME_VERIFICATION_AND_SOURCE_OF_TRUTH.md).
> **Honored:** the system assists the auditor, not replaces them; final opinion belongs to a licensed auditor; **no** automatic formal opinion; **no** ledger/payment/CRM changes.

---

## 1. What was implemented

Hardened the automated wording in `apps/reports/services/isa700_opinion_service.py` so the output reads as an **audit-readiness / opinion-preparation draft** ("suggested direction, subject to auditor review") rather than an issued formal opinion. Field structure and the `opinion_type` code are preserved (API compatibility); only emitted prose and human-facing labels changed, plus new disclaimer/flag fields. Added a DB-free wording-safety test.

## 2. Wording risks found (all in one file)

A blast-radius scan found risky wording **only** in `apps/reports/services/isa700_opinion_service.py` (templates/serializers contained no literal phrases — they render service fields). Risky emitted prose:
- `_build_opinion_paragraph`: **"In our opinion … present fairly / do not present fairly"** (EN) and **"في رأينا … "** (AR), for all four types.
- `_build_basis_for_opinion`: **"Basis for Our Opinion: During the audit we conducted … we exercised…"** (implied the system performed the audit).
- `AUDITOR_RESPONSIBILITY_EN/AR`: **"Our responsibility is to express an audit opinion … We conducted our audit"** (implied the system is the auditor).
- Metadata labels `opinion_type_en/ar`: "Unqualified/Qualified/Adverse Opinion", "Disclaimer of Opinion".
- `auditor_signature_block`: "Report prepared by: Tadgeeg Automated Audit System".

## 3. Safe wording changes

- **Opinion paragraphs** → "Audit readiness — suggested draft direction: LIKELY UNMODIFIED / POSSIBLE MODIFICATION / POSSIBLE ADVERSE MODIFICATION / insufficient basis, **subject to auditor review** … This is not a formal audit opinion; a licensed auditor must prepare the final opinion." (EN + AR). No "in our opinion"/"present fairly".
- **Direction labels** (`opinion_type_en/ar`, both in the paragraph dict and metadata) → "… direction — subject to auditor review" / "… رهن مراجعة المدقّق".
- **Basis** → "Basis for the suggested direction (subject to auditor review): Tadgeeg automated analysis applied structured procedures … A licensed auditor must evaluate these results and prepare the final opinion."
- **Auditor responsibility** → reframed: expressing the opinion is the licensed auditor's responsibility; Tadgeeg provides a preparation aid only and does not replace the auditor.
- **Signature block** → "Audit-readiness draft prepared by Tadgeeg automated analysis … for licensed-auditor review. Not a formal audit opinion." + `requires_licensed_auditor_review: True`.
- **New fields** on the paragraph and the top-level report: `is_formal_opinion: False`, `subject_to_auditor_review: True`, `suggested_opinion_direction` (the code), `disclaimer_en`, `disclaimer_ar`.
- **Preserved for compatibility:** the internal `opinion_type` code values (`unqualified/qualified/adverse/disclaimer`), the `_determine_opinion_type` logic, and the overall field/section structure.

## 4. Safe wording policy & disclaimer

Automated output uses: *audit readiness assessment · opinion preparation draft · suggested direction subject to auditor review · auditor review required · final opinion must be approved by a licensed auditor · this is not a formal audit opinion.* Required disclaimer (constants `SAFE_DISCLAIMER_EN/AR`, attached to every paragraph and the report):

> "This output is an audit readiness and opinion preparation aid. It does not constitute a formal audit opinion. The final audit opinion must be prepared and approved by a licensed auditor based on professional judgment and sufficient appropriate audit evidence."

Forbidden in automated output (verified absent by test): "in our opinion", "present fairly", "do not present fairly", "we express an audit opinion", "opinion issued" (+ Arabic "في رأينا", "تعرض بعدالة").

## 5. Why this does not issue a formal audit opinion

The service now emits a *draft direction* with an explicit disclaimer and `is_formal_opinion: False`; every direction is "subject to auditor review", and the auditor-responsibility text states the opinion is the licensed auditor's. The opinion-type classification logic is retained as an internal aid, but no text asserts an issued opinion.

## 6. Relation to the 5A Audit Readiness Workpaper

5A's `AuditReadinessWorkpaper` is the canonical engagement-level readiness aid (built from the SAD). 5B aligns the older `apps/reports` ISA-700 *report* wording with the same safe policy and disclaimer, so both surfaces consistently say "subject to auditor review / not a formal opinion". This phase kept the change wording-only and did **not** wire the report service to consume `AuditReadinessWorkpaper` (deferred — see §9), to keep the change minimal and non-breaking.

## 7. Tests run

New DB-free `apps/reports/tests/test_isa700_wording_safety.py` (7 tests): no unsafe EN/AR phrases across all four direction paragraphs; disclaimer + review flags present; direction labels are not formal-opinion labels; basis paragraph carries no "our opinion" assertion; disclaimer constants correct; auditor-responsibility is preparation-framed. Existing `tests/test_report_generation.py` re-run to confirm the report flow still works; full `apps/audit` suite re-run.

**Pre-existing breakage (not caused by this phase):** `tests/test_isa700_opinion.py` errors at collection on a stale `org` fixture (`Organization(country_code=…)` — the field is now `country`); all 27 tests error regardless of this phase. It was already broken before 5B and is out of scope (touches an unrelated test fixture). The new wording-safety test deliberately avoids that fixture.

## 8. What was intentionally NOT implemented

New formal-opinion issuance · public final-opinion workflow · wiring the report service to `AuditReadinessWorkpaper` · template/serializer field renames beyond wording · AI · ledger posting · evidence upload · bank/VAT reconciliation · frontend redesign · fixing the unrelated `tests/test_isa700_opinion.py` fixture bug.

## 9. Recommended next phase

**TADGEEG-FIN-AUDIT-5C — Readiness/opinion export & report integration:** (a) fix the stale `org` fixture in `tests/test_isa700_opinion.py` and update its wording assertions to the safe phrasing; (b) optionally render the 5A workpaper + hardened ISA-700 draft to PDF/HTML with the disclaimer banner; (c) consider feeding `AuditReadinessWorkpaper` into the report service as the single source of the suggested direction. Separately, an **evidence-upload** phase tied to `needs_evidence`.

## 10. What NOT to change (carried forward)

No formal opinion issuance; no "in our opinion"/"present fairly"/"opinion issued" in automated output; no second `AuditEngagement`; no `apps/financial_audit`; no ledger posting / `ledger.JournalEntry` change; no AI; no frontend redesign; no payments/subscriptions/CRM/Moyasar/manual-payments/legal-page changes; no production-readiness claim.
