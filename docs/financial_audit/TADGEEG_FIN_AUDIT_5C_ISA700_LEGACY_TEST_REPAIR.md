# TADGEEG-FIN-AUDIT-5C — ISA-700 Legacy Test Repair & Safe Readiness Compatibility

> **Phase type:** Test & compatibility hardening only — no production behavior change.
> **Date:** 2026-06-23 · **Builds on:** `b88731c` (5B). · **Predecessors:** [5B](TADGEEG_FIN_AUDIT_5B_SAFE_ISA700_WORDING_HARDENING.md), [5A](TADGEEG_FIN_AUDIT_5A_AUDIT_READINESS_OPINION_PREPARATION_WORKPAPER.md).
> **Honored:** no formal opinion, no unsafe wording reintroduced, no PDF/HTML export, no frontend, no AI, no ledger/payment/CRM changes.

---

## 1. Summary
Repaired the legacy `tests/test_isa700_opinion.py` suite so it runs and aligns with the 5B safe-wording hardening. Two problems were fixed **in the test file only**: a stale `Organization(country_code=…)` fixture (collection-time error on all 27 tests), and four assertions that still expected the old formal-opinion wording. No production code was changed; the ISA-700 service already emits safe draft-direction wording from 5B.

## 2. What was broken & why
- **Stale fixture (root cause of the 27 errors):** the `org` fixture called `Organization.objects.create(name=…, slug=…, country_code="SA")`. The model field is `country` (`apps/authentication/models.py:293`; `slug` is accepted-and-ignored via `__init__`'s `kwargs.pop("slug")`), so `country_code` raised `TypeError: got unexpected keyword arguments: 'country_code'` at fixture setup → every test errored. This predated 5B.
- **Stale wording assertions (4 failures after the fixture fix):** four tests still asserted the pre-5B formal-opinion text — `"رأينا"` / `"امتثالاً عادلاً"` (unqualified AR), `"except for"` / `"Basis for Our Opinion"` (qualified EN), `"unable to express"` (disclaimer EN), and `"رأينا"` / `"our responsibility"` in the responsibility sections. 5B intentionally replaced that text with safe draft-direction wording, so these assertions no longer matched.

## 3. Fixture fixes
`tests/test_isa700_opinion.py` `org` fixture: `country_code="SA"` → `country="SA"`, and dropped the no-op `slug` kwarg. Minimal and consistent with the current model. **No production model was changed to satisfy the test.**

## 4. Wording expectation changes (test assertions only)
| Test | Old expectation (removed) | New safe expectation |
|---|---|---|
| `test_unqualified_opinion_paragraph_arabic` | `"رأينا"`, `"امتثالاً عادلاً"` | `"رهن مراجعة المدقّق"` present; `"في رأينا"`/`"تعرض بعدالة"` absent; `is_formal_opinion is False`; `subject_to_auditor_review is True`; score retained |
| `test_qualified_opinion_paragraph_english` | `"except for"`, `"Basis for Our Opinion"` | `"subject to auditor review"` + `"not a formal audit opinion"` present; `"in our opinion"`/`"present fairly"` absent; score retained |
| `test_disclaimer_opinion_paragraph` | `"unable to express"` | `"subject to auditor review"` + `"insufficient basis"` present; `is_formal_opinion is False`; `disclaimer_en` present |
| `test_opinion_report_bilingual_content` | `"رأينا"` in management resp; `"our responsibility"` in auditor resp | management resp has `"المسؤولية"` and no `"في رأينا"`; auditor resp has `"licensed auditor"` + `"not a formal audit opinion"` and not `"our responsibility is to express"`; report-level `is_formal_opinion=False`, `subject_to_auditor_review=True`, `disclaimer_en` present |

`opinion_type` compatibility checks (`unqualified`/`qualified`/`adverse`/`disclaimer`) and all structural/risk/compliance/KAM/going-concern assertions were left unchanged (they pass).

## 5. Compatibility fields preserved
No fields removed. The service still returns `opinion_type` (internal CODE), `opinion_type_en/ar` (now safe direction labels), `opinion_ar/en`, `basis_phrase`, plus the 5B-added `suggested_opinion_direction`, `subject_to_auditor_review=True`, `is_formal_opinion=False`, `disclaimer_en/ar`. Tests now assert these compatibility/safety fields explicitly.

## 6. Hard-stop check
The legacy tests did **not** reveal production code emitting unsafe formal-opinion wording — 5B already neutralised it (verified: `grep` finds the forbidden phrases only in policy comments/docstrings, and the wording-safety suite passes). So no broad refactor was needed and the hard-stop condition did not trigger.

## 7. Tests run
`tests/test_isa700_opinion.py` (repaired), `apps/reports/tests/test_isa700_wording_safety.py` (5B), `tests/test_report_generation.py` (existing report flow), `apps/audit/tests/test_audit_readiness_workpaper.py` (5A), full `apps/audit/tests/`. See response §7 for results.

## 8. Intentionally NOT implemented
Formal opinion issuance · automatic final opinion · PDF/HTML export · evidence upload · bank/VAT reconciliation · frontend · ledger posting · AI · production model changes · broad service refactor · template changes.

## 9. Recommended next phase
**TADGEEG-FIN-AUDIT-5D — Readiness/opinion export & report integration:** render the 5A workpaper + hardened ISA-700 draft to PDF/HTML (with the disclaimer banner), and optionally feed `AuditReadinessWorkpaper` into the report service as the single source of the suggested direction. Separately, an evidence-upload phase tied to `needs_evidence`.

## 10. What NOT to change (carried forward)
No formal opinion; no `"in our opinion"`/`"present fairly"`/`"opinion issued"` (or Arabic equivalents) in automated output; no removal of compatibility fields; no PDF/HTML/frontend; no AI; no ledger/`JournalEntry`; no payments/subscriptions/CRM/Moyasar/manual-payments/legal-page changes; no production-readiness claim.
