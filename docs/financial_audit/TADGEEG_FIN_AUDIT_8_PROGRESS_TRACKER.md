# ملف المتابعة الحيّ — Tadgeeg (الواجهات: المرحلة 8–9)

> يُحدَّث مع كل مرحلة. الخطة الكاملة: [`TADGEEG_FIN_AUDIT_8_FRONTEND_COMPLETION_ROADMAP.md`](TADGEEG_FIN_AUDIT_8_FRONTEND_COMPLETION_ROADMAP.md).
> **آخر تحديث:** 2026‑07‑25.

**مفتاح الحالات:** ✅ Done · 🔄 In‑progress · ❌ Failed · ⬜ Pending

---

## أ) الخلفية (مراجع — منفّذة سابقًا)

| المرحلة | الوصف | الحالة |
|---|---|---|
| 1A/1B | Trial Balance import + Account Mapping | ✅ Done |
| 2A/2B | GL import + Risk Analysis | ✅ Done |
| 3A/3B | Materiality + GL Finding Review | ✅ Done |
| 4A/4B | SAD + Management Response/Adjustments | ✅ Done |
| 5A–5D | Readiness Workpaper + ISA700 wording + Export | ✅ Done |
| 6A–6D | Evidence Workflow + Client Portal + Lifecycle + Assurance | ✅ Done |
| 7A | Journal Analytics Foundation | ✅ Done |

---

## ب) إكمال الواجهات (المسار الحالي)

| المرحلة | الصفحة/الوحدة | النوع | الحالة | ملاحظات |
|---|---|---|---|---|
| **8A** | Engagement Workspace (قائمة + لوحة موحّدة + دورة الحياة) | Frontend | ✅ **Done** | `audit/engagements/` · 20 اختبار · تجميع 1A→7A + روابط عميقة + تغيير المرحلة |
| **8B** | Trial Balance Analyzer (رفع + صفوف + ربط الحسابات + حسابات شاذة) | Frontend | ✅ **Done** | `audit/trial-balance/` · يستهلك `trial_balance_import` |
| **8C** | General Ledger Review (رفع + تشغيل مخاطر 2B + مراجعة 3B) | Frontend | ✅ **Done** | `audit/general-ledger/` · `analyze_import` + `review_finding` |
| **8D** | SAD Dashboard (ملخّص + بنود + إعادة حساب) | Frontend | ✅ **Done** | `audit/sad/` · `recalculate_for_engagement` |
| **8E** | Risk Assessment (ISA 315) — نموذج إدخال + محرّك | Frontend | ✅ **Done** | `audit/isa/risk/` · `risk_decomposition.assess` · IR/CR/DR + عدّادات + audit risk % · تصميم مصقول |
| **8E‑part** | Planning (ISA 300) + Responses (ISA 330) | Frontend | 🔄 مؤجّلة | 300 يحتاج context→strategy→plan · 330 مدخلات **قائمة** `List[AssessedRisk]` (واجهة أعقد) |
| **8F** | Going Concern (ISA 570) + Estimates (ISA 540) — نماذج إدخال + محرّكات | Frontend | ✅ **Done** | `audit/isa/going-concern/` + `audit/isa/estimates/` · تصميم مصقول |
| **8F‑part** | Fraud (ISA 240) | Frontend | 🔄 مؤجّلة | مدخلات **قائمة** `List[FraudRiskFactor]` (واجهة أعقد) |
| **8G** | Readiness Generate & Export UI | Frontend | ✅ **Done** | `audit/readiness-generate/` · `generate_for_engagement` + تصدير 5D (JSON/HTML/PDF) |
| **9A** | Financial Statements Review (IAS 1) | Full (خلفية+واجهة) | ✅ **Done** | `audit/financial-statements/` · اشتقاق BS/IS من TB+mappings · نسب · مقارنة سنوية · كشف أخطاء التصنيف · 23 اختبارًا · بلا migration |
| **9B** | Management Letter (ISA 265) | Full | ⬜ Pending | فجوة حقيقية |
| **9C** | External Confirmations (ISA 505) | Full | ✅ **Done** | `audit/confirmations/` + صفحة رد عامة `/confirm/<token>/` · إرسال/تسجيل/مطابقة/فرق · 24 اختبارًا · migration 0028 |
| **9D** | Inventory (ISA 501) + Fixed Assets + Payroll | Full | ⬜ Pending | فجوة حقيقية |

---

## ج) السجل الزمني (Changelog)

| التاريخ | المرحلة | الحدث |
|---|---|---|
| 2026‑07‑25 | 8A | ✅ Engagement Workspace + اختبارات + توثيق الخطة والمتابعة |
| 2026‑07‑25 | 8B/8C/8D/8G | ✅ صفحات TB · GL · SAD · الجاهزية (13 اختبارًا) — تستهلك الخدمات القائمة |
| 2026‑07‑25 | 8E/8F | ✅ صفحات ISA 315/570/540 بنماذج إدخال + **تصميم احترافي مصقول** (12 اختبارًا) |
| 2026‑07‑25 | 8E/8F (part) | 🔄 المتبقّي: ISA 300 · 330 · 240 (مدخلات قائمة) مؤجّل |
| 2026‑07‑25 | 9A | ✅ مراجعة القوائم المالية (IAS 1) — خدمة + API + واجهة مصقولة (23 اختبارًا) |
| 2026‑07‑25 | 9C | ✅ التأكيدات الخارجية (ISA 505) — نموذج + خدمة + API + واجهة مدقّق + **صفحة رد عامة برمز آمن** (24 اختبارًا) |

---

### الخطوة التالية المقترحة
- **9B** خطاب الإدارة (ISA 265) — تجميع أوجه ضعف الرقابة + توليد الخطاب.
- ثم **9D** المخزون/الأصول/الرواتب.
- والمؤجّل: واجهات **ISA 300/330/240** (list-builders).
