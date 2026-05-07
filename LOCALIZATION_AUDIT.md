# Tadgeeg Localization Audit — Stage 1 Inventory

**Read-only audit. No code modified.**

Date: 2026-05-06
Scope: full repo scan (templates, apps, static, locale, reports, emails)

---

## 1. Executive summary

Tadgeeg is **already substantially internationalized**, but unevenly — there is mature i18n infrastructure (LocaleMiddleware, `LOCALE_PATHS`, both `ar` and `en` `.po`/`.mo` files with **~2,630 message strings each**, a `TADGEEG_I18N` JS payload partial, dynamic `LANGUAGE_BIDI`-driven RTL on key layouts) and large pockets of mature translation in templates. The gap is uneven: a handful of pages and dialogs are still hardcoded Arabic, several Python apps have **zero** `_()` usage, the rule-engine catalog uses a non-standard parallel-fields pattern (`description_ar`/`description_en`) that needs a strategy decision, and a number of admin-facing pages are pinned to `dir="rtl"`.

**Headline numbers**

| Metric | Value |
|---|---|
| Total HTML templates | 163 |
| Templates with `{% load i18n %}` | 163 / 163 |
| Total `{% trans %}` / `{% blocktrans %}` tags | ~5,400+ |
| Templates with hardcoded `dir="rtl"` (must become dynamic) | **20** |
| Templates with hardcoded Arabic strings | **25** (top offender: `users/index.html` with 117 Arabic literals) |
| Python files with `gettext` / `_()` | ~510 refs across 7 apps |
| Apps with **zero** `_()` usage | **27 of 39** |
| Python files with hardcoded Arabic | 84 (rule_engine: 48, documents: 11, reports: 10) |
| Standalone JS files | 4 (all third-party vendor — none of ours) |
| Existing `.po` strings (ar/en) | 2,630 |
| Existing JS i18n payload | ✅ `templates/partials/i18n_strings.html` (`window.TADGEEG_I18N`) |

---

## 2. Current i18n configuration

| Item | Status |
|---|---|
| `USE_I18N = True` | ✅ ([finai_backend/settings.py:224](finai_backend/settings.py#L224)) |
| `LANGUAGE_CODE = "ar"` | ✅ ([finai_backend/settings.py:217](finai_backend/settings.py#L217)) |
| `LANGUAGES = [("ar", ...), ("en", ...)]` | ✅ ([finai_backend/settings.py:218](finai_backend/settings.py#L218)) |
| `LOCALE_PATHS = [BASE_DIR / "locale"]` | ✅ ([finai_backend/settings.py:222](finai_backend/settings.py#L222)) |
| `LocaleMiddleware` registered | ✅ ([finai_backend/settings.py:153](finai_backend/settings.py#L153)) |
| Middleware order | ✅ after Session, before Common |
| `i18n_patterns` in URLs | ❌ Not used — language is set via cookie `tadgeeg_language` |
| Compiled `.mo` files present | ✅ [locale/ar/LC_MESSAGES/django.mo](locale/ar/LC_MESSAGES/django.mo), [locale/en/](locale/en/LC_MESSAGES/django.mo) |

**Verdict:** infrastructure is sound. No settings work needed for Stage 2.

---

## 3. Templates — gap inventory

### 3.1 Templates with hardcoded Arabic strings (priority order)

| File | Arabic literals | Notes |
|---|---:|---|
| [templates/users/index.html](templates/users/index.html) | **117** | Whole admin user-management page never internationalized — labels, x-text, placeholders, validation. Highest priority. |
| [templates/invoices/detail.html](templates/invoices/detail.html) | 30 | **Intentional bilingual dual-display** pattern (e.g. `جاري التحليل... / Approval Blocked`) — needs design decision (see §8). |
| [templates/settings/index.html](templates/settings/index.html) | 19 | Country/timezone/currency option labels (e.g. `العربية`, `السعودية`). Mostly enum display — convert via `{% trans %}` or context-built choices. |
| [templates/cms_admin/homepage.html](templates/cms_admin/homepage.html) | 18 | CMS admin page labels. |
| [templates/layouts/dashboard_base.html](templates/layouts/dashboard_base.html) | 14 | Sidebar label `<span class="ar">تدقيق</span>` (CSS-toggled bilingual span — not gettext-driven), and AI assistant greeting strings wrapped by `{% trans "..." %}` with **Arabic source** instead of English. **Anti-pattern** — must flip source to English. |
| [templates/cms_admin/about.html](templates/cms_admin/about.html) | 13 | |
| [templates/layouts/base_vendor_dashboard.html](templates/layouts/base_vendor_dashboard.html) | 7 | |
| [templates/audit/detail.html](templates/audit/detail.html) | 7 | |
| [templates/reports/partials/_report_header.html](templates/reports/partials/_report_header.html) | 4 | **Status comparison against Arabic literal**: `{% if report.status == "عالي المخاطر" or report.status == "high_risk" ... %}` — should compare to enum keys only. |
| 16 more | 1–3 each | CMS/admin pages, landing fragments. |

### 3.2 Templates with fixed `dir="rtl"` (must become dynamic)

20 templates — mostly platform_admin / cms_admin / vendor_dashboard / two PDF reports:

```
templates/reports/document_audit_report.html
templates/reports/invoice_audit_report_v2.html
templates/platform_admin/jobs.html
templates/platform_admin/seo.html
templates/platform_admin/cms/{pricing,faq,services,intro_video,homepage,pages,about}.html
templates/cms_admin/{jobs,pricing,services_editor,homepage,faq,pages,about,seo}.html
templates/vendor_dashboard/settings.html
```

Required change everywhere: `dir="rtl"` → `dir="{% if LANGUAGE_BIDI %}rtl{% else %}ltr{% endif %}"`.

### 3.3 Templates with already-correct dynamic dir (reference good)

[templates/base.html](templates/base.html), [templates/404.html](templates/404.html), [templates/500.html](templates/500.html), [templates/403.html](templates/403.html), [templates/layouts/base_vendor_dashboard.html](templates/layouts/base_vendor_dashboard.html), [templates/reports/report_pdf.html](templates/reports/report_pdf.html), [templates/reports/invoice_audit_report_pdf.html](templates/reports/invoice_audit_report_pdf.html), [templates/reports/invoice_audit_report.html](templates/reports/invoice_audit_report.html), [templates/reports/document_audit_report.html](templates/reports/document_audit_report.html), [templates/reports/executive_report_error.html](templates/reports/executive_report_error.html). Pattern: `{% if LANGUAGE_BIDI %}rtl{% else %}ltr{% endif %}`.

### 3.4 `{% trans %}` density per template directory

```
reports             18 files |  944 trans tags     ✅ heavy coverage
documents           18 files |  625 trans tags     ✅
cms_admin           13 files |  568 trans tags     ✅ but 20 hardcoded dir
platform_admin      17 files |  516 trans tags     ✅ but hardcoded dir
invoices            10 files |  358 trans tags
phase2               8 files |  351 trans tags
vendor_dashboard    12 files |  310 trans tags
audit                6 files |  229 trans tags
auth                10 files |  192 trans tags
storage_management   7 files |  164 trans tags
settings             5 files |  159 trans tags
auditing             6 files |  156 trans tags
partials             3 files |   98 trans tags
working_papers       3 files |   63 trans tags
landing              2 files |   79 trans tags
users                1 file  |   76 trans tags     ⚠ but 117 Arabic literals — drastic gap
dashboard            1 file  |   67 trans tags
top-level            5 files |   62 trans tags
compliance           1 file  |   57 trans tags
analytics            1 file  |   21 trans tags
ledger               1 file  |   29 trans tags
banking              1 file  |   34 trans tags
streaming            1 file  |   30 trans tags
zatca                1 file  |   40 trans tags
alerts               1 file  |   45 trans tags
vendors              2 files |   59 trans tags
layouts              7 files |   44 trans tags     ⚠ low — base layouts
components           2 files |    9 trans tags     ⚠ low
```

---

## 4. Python source — gap inventory

### 4.1 `gettext` / `gettext_lazy` coverage by app

| Tier | Apps | Refs |
|---|---|---|
| ✅ Mature | frontend (188), reports (137), authentication (91), documents (32), invoices (30), audit (17), notifications (12) | 507 |
| ⚠ Zero coverage — high user-facing impact | rule_engine, audit_engine, auditing, alerts, compliance, banking, ledger, **procurement** (new), **tax_engine** (new), zatca, transactions, vendor_dashboard, organization_admin, organization_users, organization_settings, platform_admin, platform_management, file_management, storage_management, leads, jobs, cms, analytics, api_mobile, streaming, system_monitoring, webhooks, workflow, data_export, reporting, assistant, core_engine, activity_logs | 0 |

### 4.2 Hardcoded Arabic in Python by app

| App | Files w/ Arabic | Notes |
|---|---:|---|
| **rule_engine** | **48** | Mostly **dual-field pattern** (`description_ar` + `description_en` siblings) in [apps/rule_engine/catalog.py](apps/rule_engine/catalog.py) and rule definitions. Architectural decision needed — see §8. |
| documents | 11 | Mix of dual-field and column-name parsing (e.g. `_col(df, "currency", "العملة")` — parsing user uploads, **acceptable**). |
| **reports** | **10** | [apps/reports/services/](apps/reports/services/) has **136** Arabic literals in `executive_ai_report_service.py`, **90** in `invoice_audit_service.py` — anti-pattern `txt("متوسط", "Medium")` and `is_ar` branching. Must convert to `gettext_lazy`. |
| auditing | 6 | |
| frontend | 2 | |
| audit, authentication, cms, invoices, workflow, zatca, assistant | 1 each | |

### 4.3 New apps with no i18n (added in commit `11fc3a1`)

| File | Strings to translate |
|---|---|
| [apps/procurement/models.py](apps/procurement/models.py) | help_text on PR/PO/three-way match models, status choices labels |
| [apps/procurement/services.py](apps/procurement/services.py) | error/exception messages |
| [apps/procurement/views.py](apps/procurement/views.py) | response messages |
| [apps/ledger/models.py](apps/ledger/models.py) | help_text, status choices, AccountingPeriod labels |
| [apps/ledger/tax_engine.py](apps/ledger/tax_engine.py) | error messages, member-state labels |
| [apps/ledger/services.py](apps/ledger/services.py) | period close / journal validation messages |

### 4.4 Serializers without `_()` (likely user-facing error strings)

```
apps/audit_engine/serializers.py     6 strings, 0 translations
apps/invoices/serializers.py         4 strings, 0 translations
apps/file_management/serializers.py  15 strings, 0 translations
apps/documents/serializers.py        8 strings, 0 translations
apps/auditing/serializers.py         7 strings, 0 translations
```

### 4.5 Hardcoded API responses

```
apps/frontend/page_views.py:1403   JsonResponse({"error": "POST required"})
apps/invoices/views.py:1156         Response({"detail": "Not found."})
apps/cms/views.py: 8x               Response({"detail": "Not found."})
apps/vendor_dashboard/api_views.py  ~5x  "Folder not found.", "Folder name is required.", ...
```

These are short and may be acceptable as-is for developer-facing responses, but for any UI-consumed endpoint they should be wrapped in `_()`.

---

## 5. JavaScript / AlpineJS

### 5.1 JS infrastructure already in place ✅

[templates/partials/i18n_strings.html](templates/partials/i18n_strings.html) emits `window.TADGEEG_I18N` with `risk`, `severity`, `status`, `msg` groups, sourced from `{% trans 'Low' %}` etc. Loaded in `<head>` by [base.html](templates/base.html) and [layouts/dashboard_base.html](templates/layouts/dashboard_base.html). Most pages correctly use:
```js
severityLabel(s) { return (window.TADGEEG_I18N?.severity?.[s]) || s; }
```

### 5.2 Pages with hardcoded Arabic in inline `<script>` / `x-text`

[templates/users/index.html](templates/users/index.html) is the worst offender — 5+ Alpine `x-text` ternaries with Arabic literals. Must convert to `TADGEEG_I18N` keys.

```html
<span x-text="u.is_active ? 'إيقاف الحساب' : 'تفعيل الحساب'"></span>
<h2 x-text="editUser.id ? 'تعديل بيانات المستخدم' : 'إضافة مستخدم جديد'"></h2>
<span x-text="editUser.is_active ? 'الحساب نشط حالياً' : 'الحساب موقوف حالياً'"></span>
```

### 5.3 Outlier — page-local severityLabel function

[templates/invoices/detail.html:868](templates/invoices/detail.html#L868) defines its own `severityLabel(severity)` instead of using the shared `TADGEEG_I18N.severity` lookup. Should be unified.

---

## 6. Reports / PDF / Excel / email

### 6.1 PDF/HTML reports

| File | Arabic | Notes |
|---|---|---|
| [templates/reports/executive_report.html](templates/reports/executive_report.html) | 0 chars, 0 trans | All content rendered from context — verify context strings are translated server-side. |
| [templates/reports/invoice_audit_report.html](templates/reports/invoice_audit_report.html) | dynamic dir ✅ | |
| [templates/reports/invoice_audit_report_v2.html](templates/reports/invoice_audit_report_v2.html) | hardcoded `dir="rtl"` ❌ | English render will break layout. |
| [templates/reports/document_audit_report.html](templates/reports/document_audit_report.html) | hardcoded `dir="rtl"` ❌ | |
| [templates/reports/report_pdf.html](templates/reports/report_pdf.html) | dynamic dir ✅ | |
| [templates/reports/invoice_audit_report_pdf.html](templates/reports/invoice_audit_report_pdf.html) | dynamic dir ✅ | |
| [templates/reports/partials/_report_header.html](templates/reports/partials/_report_header.html) | compares `report.status == "عالي المخاطر"` literal ❌ | Must compare to enum keys only. |

### 6.2 Report-generation services (Python)

`apps/reports/services/executive_ai_report_service.py` (136 Arabic literals) and `invoice_audit_service.py` (90) use a `txt(ar_str, en_str)` helper and `is_ar` branching. **Must be replaced with `gettext_lazy`-based translation** so the message catalog is the source of truth, not Python code.

Examples:
```python
return "مرتفع" if is_ar else "High"          # apps/reports/views.py:230
"weight": txt("متوسط", "Medium"),             # apps/reports/views.py:363
"note": txt("توفر رقم الفاتورة...", "..."),   # apps/reports/views.py:364
```

### 6.3 Excel exports

Excel-export code lives in `apps/reports/views.py`, `apps/invoices/views.py`, `apps/banking/views.py`, `apps/documents/typed_views.py`, `apps/file_management/selectors.py`, `apps/vendor_dashboard/page_views.py`, `apps/audit_engine/services/parsers/excel_parser.py`. Headers and labels appear to be hardcoded; need per-file pass to wrap headers in `gettext_lazy` and emit translated headers based on active locale.

### 6.4 Email templates

```
templates/auth/otp_email.html               (English-only currently)
templates/auth/emails/password_reset_email.txt
templates/auth/emails/password_reset_subject.txt
```

These are tiny but **user-facing**. Need `{% trans %}` wrapping and the auth code needs `activate(user.preferred_language)` before rendering.

---

## 7. Severity / status / risk label inventory

### 7.1 Internal keys used (DO NOT translate — these are stable)

```
risk:       low, medium, high, critical
severity:   low, medium, high, critical, info
status:     pending, processing, validated, flagged, approved, rejected,
            completed, failed, partial, received, extracting, normalizing
purchase_requisition.status:  draft, submitted, approved, rejected, closed
accounting_period.status:     open, closing, closed, locked
```

### 7.2 Translated labels — single source of truth

[templates/partials/i18n_strings.html](templates/partials/i18n_strings.html). New status keys (procurement, ledger periods) need to be added there.

### 7.3 Recommended API pattern

```jsonc
{
  "severity": "high",            // stable enum key
  "severity_label": "High Risk"  // localized via gettext on the response
}
```

Many serializers don't yet emit `*_label` fields. Procurement / ledger / tax_engine serializers (don't exist yet) should be built with this pattern.

---

## 8. Architectural decisions needed before Stage 2

These are **strategy choices** I need from you before touching code, because the answer changes 100s of edits.

### Q1. Rule-engine catalog — `description_ar`/`description_en` parallel-field pattern

[apps/rule_engine/catalog.py](apps/rule_engine/catalog.py) and 47 other rule_engine files store both languages as separate fields on the data class. Two options:

- **(A) Keep the dual-field pattern** — it's actually fine for *user-editable rule content* (think CMS). Just normalize all consumers to read `description_ar` when `LANGUAGE_CODE == 'ar'`, else `description_en`. No `.po` work for this content.
- **(B) Migrate to `gettext_lazy` source = English** — collapse to a single `description` field with English source, translations live in `.po`. Cleaner, but you lose the "rule author can write any free text" property.

**My recommendation: (A) for catalog/rule content (this is data, not UI text), (B) for everything else.**

### Q2. Bilingual dual-display pages (e.g. invoices/detail.html)

[templates/invoices/detail.html](templates/invoices/detail.html) shows both languages simultaneously: `جاري التحليل... / Approval Blocked`. This is **product UX**, not a translation gap. Three options:

- **(A) Keep dual-display, fix the inversion** — mark each side individually (`{% trans "Audit Pending" %} / {% trans "Audit Pending" lang="ar" %}`) — but Django doesn't have a per-site language tag. Practical fix: each pair becomes `{% trans "Audit Pending (Arabic)" %} / {% trans "Audit Pending" %}` with the `_ar` source string in the catalog. Ugly.
- **(B) Drop dual-display, use single localized text** — respect `LANGUAGE_CODE`. Simpler, more standard.
- **(C) Keep dual-display via context** — view passes `text_ar`/`text_en` pairs.

**My recommendation: (B) — switch to standard single-language UI driven by user preference.** Confirm or override.

### Q3. Reports services `txt(ar, en)` helper

[apps/reports/views.py:363](apps/reports/views.py#L363) and 5 services in [apps/reports/services/](apps/reports/services/). Replace `txt("متوسط", "Medium")` with `gettext("Medium")` everywhere. Simple, just tedious. Approve?

### Q4. Sidebar `<span class="ar">…</span>` / `<span class="en">…</span>` CSS-toggled spans

[templates/layouts/dashboard_base.html](templates/layouts/dashboard_base.html) shows pattern of two spans, one shown via CSS based on language. Replace with `{% trans %}`?

### Q5. URL strategy

Currently no `i18n_patterns` — language is set via the `tadgeeg_language` cookie ([finai_backend/settings.py:227](finai_backend/settings.py#L227)). Switching languages doesn't change URLs. Want to keep this, or move to `/ar/foo`, `/en/foo`?

**My recommendation: keep cookie-based.** Switching the URL strategy at this stage breaks every external link. Confirm.

---

## 9. Stage 2 implementation plan — proposed chunks

Doing all of this in one PR is unreviewable and risky. I recommend chunking like this — **each chunk is a separate commit, each can be deployed independently, each leaves the app in a working state**. Tell me which to start with.

| # | Chunk | Files | Risk | Effort |
|---|---|---|---|---|
| **1** | **Quick wins — RTL/LTR fixes** | 20 templates with hardcoded `dir="rtl"` | Low | Small |
| **2** | **Layouts + sidebar + navbar i18n** | dashboard_base.html, base_vendor_dashboard.html, components/ | Low | Small |
| **3** | **users/index.html full pass** | 117 Arabic literals, Alpine x-text rewrites | Medium | Medium |
| **4** | **Bilingual dual-display unification** (invoices/detail.html) | dependent on Q2 decision | Medium | Medium |
| **5** | **Reports services — kill `txt()`/`is_ar`** | 5 service files in apps/reports/services/ | Medium | Medium |
| **6** | **PDF reports — fix v2 + document_audit dir** | 2 templates | Low | Small |
| **7** | **Reports `_report_header.html` — drop status literal compare** | 1 template + tracking down callers | Medium | Small |
| **8** | **New apps i18n** — procurement / ledger / tax_engine models, services, error messages | 6 files, ~50 strings | Low | Small |
| **9** | **Serializers** — wrap user-facing strings in 5 serializer files | 5 files, ~40 strings | Low | Small |
| **10** | **API hardcoded JsonResponse/Response** strings | ~25 sites across views | Low | Small |
| **11** | **Email templates** — wrap auth emails in `{% trans %}` + `activate()` in send code | 3 templates + 1-2 callers | Low | Small |
| **12** | **Excel export headers** | 7 Excel-emitting files | Medium | Medium |
| **13** | **CMS admin / platform admin pages** — finish translating Arabic literals + dynamic dir | 22 templates | Low | Medium |
| **14** | **Rule-engine policy** (Q1 decision) — formalize Arabic/English consumption | rule_engine + catalog | High | Medium |
| **15** | **Apps with zero `_()` — model/form/view labels** — auditing, audit_engine, alerts, compliance, banking, etc. | 27 apps | Low | **Large** |
| **16** | **Tests** — i18n smoke tests (Stage 3) | tests/test_i18n.py | Low | Medium |
| **17** | **`makemessages` / `compilemessages` + manual translation review** | locale/.po files | Low | Medium-Large |

---

## 10. What I will NOT do

- Translate database **enum values** (`status`, `severity`, `risk_level`).
- Touch audit calculations or business logic.
- Change DB schema.
- Move to `i18n_patterns` URLs unless you explicitly ask.
- Do all 17 chunks in one session — unreviewable.
- Auto-translate `.po` strings using machine translation. Human-quality Arabic translations for finance domain need a native reviewer; I'll fill `msgstr` for trivially-derivable strings only.

---

## 11. Manual QA checklist (for Stage 3)

```
[ ] Login page — Arabic
[ ] Login page — English
[ ] Register page — both
[ ] Dashboard — both
[ ] Sidebar — both, RTL/LTR correct
[ ] Navbar — both
[ ] Upload pages — both
[ ] Invoice list — both
[ ] Invoice detail — both (post-Q2 decision)
[ ] Purchase order pages — both
[ ] Purchase requisition pages — both
[ ] Accounting period pages — both
[ ] Compliance pages — both
[ ] Analytics pages — both
[ ] Reports list — both
[ ] PDF report — Arabic renders correctly (font, RTL)
[ ] PDF report — English renders correctly (font, LTR)
[ ] Excel export — headers translated
[ ] OTP email — Arabic and English versions
[ ] JavaScript severity/status labels — both
[ ] Toast notifications — both
[ ] Form validation messages — both
[ ] Mobile (≤640px) — both languages, no overflow
[ ] No raw Arabic in English mode (grep)
[ ] No raw English in Arabic mode where translated string exists (manual)
```

---

## End of Stage 1.

**Awaiting answers to Q1–Q5 in §8 and which chunk(s) from §9 to start with.**
