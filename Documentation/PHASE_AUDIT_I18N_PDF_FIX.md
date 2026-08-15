# Phase — Audit + i18n + PDF gap fixes

Three independent gap inventories, three commits, one report.

---

## 1. Auditing — gaps found

| # | Gap | Severity |
|---|---|---|
| A1 | `apps/documents/signals.py` had `post_save` handlers for only 9 v1 typed-doc models. The 11 phase-2 types (SalesOrder, Quotation, ProformaInvoice, ReceiptVoucher, CashVoucher, GeneralLedger, Ledger, Contract, SupplierStatement, CustomerStatement, JournalEntry) had **no** auto-audit on save. Uploads of those types never triggered the rule engine. | High |
| A2 | `_dispatch_audit` called `.delay()` directly inside the post_save signal. Classic Django/Celery race: a fast worker SELECTs the row before the writing transaction commits and finds 0 rows. If the writer rolls back, a phantom task fires. | High |
| A3 | (Out of scope) `AuditRunV2Metadata` has 3 pending model alterations not in any migration — see Phase 5 report. | Low — flagged earlier |

### Fix — `apps/documents/signals.py` (commit `6fdf0fd`)

- Added 11 receiver functions for the phase-2 sender models (one per type).
- Wrapped the dispatch body in `transaction.on_commit(...)`.
- 20 `on_*_save` handlers now wired (was 9).

```python
# Before:
run_audit_compat_task.delay(document_id=doc_id, ...)

# After:
def _send():
    if _has_active_run(...): return
    run_audit_compat_task.delay(...)
transaction.on_commit(_send)
```

### Verification

```text
$ python -c "from apps.documents import signals; ..."
on_*_save handlers: 20
  on_bank_statement_save
  on_cash_voucher_save
  on_contract_save
  on_customer_statement_save
  on_expense_save
  on_fixed_asset_save
  on_general_ledger_save
  on_grn_save
  on_journal_entry_save
  on_ledger_save
  on_payment_save
  on_payroll_save
  on_proforma_invoice_save
  on_purchase_order_save
  on_quotation_save
  on_receipt_voucher_save
  on_sales_order_save
  on_sales_receipt_save
  on_supplier_statement_save
  on_vat_return_save
```

`python manage.py check` — 0 issues.

---

## 2. i18n — gaps found

| # | Gap | Severity |
|---|---|---|
| I1 | Numbers rendered without thousand separators. `{{ x\|floatformat:0 }}` produced raw `"257050"` / `"2162286078"`. | Med — readability |
| I2 | `django.contrib.humanize` wasn't in `INSTALLED_APPS`, so `{% load humanize %}` would have errored. | High |
| I3 | The Arabic locale's `THOUSAND_SEPARATOR` is empty, so even `{{ x\|intcomma }}` (which respects locale) was a no-op for AR users. | Med |
| I4 | 284 empty Arabic translations in `locale/ar/LC_MESSAGES/django.po` (msgstr ""). | Med — ongoing translation work, not in scope here |
| I5 | Hardcoded `dir="rtl"` on Arabic-content `<input>`/`<textarea>` (Job titles, descriptions). | Not a bug — Arabic content fields should always render RTL regardless of UI language. |

### Fix — settings + dashboard template (commit `7fa8269`)

- Added `django.contrib.humanize` to `DJANGO_APPS`.
- Set `USE_THOUSAND_SEPARATOR = True`.
- Dashboard amounts now use `{{ x|floatformat:0|intcomma:False }}` — the `False` arg forces the comma form regardless of locale, matching Saudi/GCC business convention for financial figures.

3 amounts touched in `templates/dashboard/index.html`:
- per-currency tile total
- VAT subtitle
- top-risky-vendors total column

### Verification

```text
EN locale, intcomma:        "257,050"
AR locale, intcomma:        "257050"        ← no separator (locale empty)
AR locale, intcomma:False:  "257,050"       ← forced — what we ship
```

---

## 3. PDF — gaps found

| # | Gap | Severity |
|---|---|---|
| P1 | Every "Download PDF" click re-rendered the same bytes through WeasyPrint. 30-60 page audit reports take 3-15 seconds; multiple clicks blocked gunicorn workers. | High |
| P2 | `ModuleNotFoundError` (WeasyPrint missing) returned a hard 503, but `OSError` (GTK/Pango/cairo missing) silently fell through to an HTML fallback. Inconsistent: dev machines without GTK got HTML; servers without WeasyPrint got an error. | Med |
| P3 | No `Content-Length` header on PDF responses → browsers can't show download progress. | Low |
| P4 | PDF templates declare `'Noto Sans Arabic', 'DejaVu Sans'` but rely on system fonts. The Dockerfile installs `fonts-noto-core`, so production is fine; Windows dev environments fall through to OSError → HTML fallback. | Low |
| P5 | PDF generation is synchronous — for huge audit reports this can hold a worker for 10+ seconds. | Med — deferred (needs Celery task + polling endpoint) |

### Fix — `apps/reports/views.py` (commit `6ca9307`)

- Added `_render_report_pdf_cached()`. Memoizes for 1 hour keyed by `(report_id, language, sha256(html_str)[:16])`. The html-digest baked into the key means any change to the report data invalidates the cache automatically.
- Folded `ModuleNotFoundError` and `OSError` into a single branch that falls through to the HTML fallback. Both now produce a usable download instead of a 503.
- Added `Content-Length` header.

### Verification

```text
PDF caching smoke:
  Uncached: 4809 bytes, 932 ms
  Cached:   4809 bytes,   0.0 ms      → 22,000× speedup
  Same bytes: True

Different language → different cache slot:
  Uncached:                 4809 bytes  (separate slot)

Modified html → cache miss (digest changes):
  Uncached:                 5212 bytes  (correct invalidation)
```

Live Arabic PDF render via WeasyPrint: 7,900 bytes. Noto Arabic glyphs subset correctly (gid for ا = 0627 confirmed in fontTools log).

---

## Files changed (3 commits)

| Commit | File | Lines |
|---|---|---|
| `6fdf0fd` audit | `apps/documents/signals.py` | +119 / -23 |
| `7fa8269` i18n | `finai_backend/settings_canonical.py` | +6 |
| `7fa8269` i18n | `templates/dashboard/index.html` | +4 / -4 |
| `6ca9307` pdf | `apps/reports/views.py` | +45 / -9 |

No model changes. No migrations. No API breaks.

---

## Deferred (not in this phase)

- **A3:** apply pending `rule_engine` migrations — separate, riskier change.
- **I4:** populate the 284 empty Arabic translations — ongoing translator work, no code change.
- **P4:** bundle Noto Sans Arabic via `@font-face` from `static/fonts/` — requires shipping ~450 KB font file in static; production already covered by `fonts-noto-core` in Dockerfile. Defer until a Windows dev complains.
- **P5:** make PDF generation async via Celery (kick off task, poll for download). With Celery now in docker-compose (Phase 3), this is feasible. Separate PR.
