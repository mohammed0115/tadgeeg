# 🎯 مجموعة Prompts احترافية لمنصة تدقيق (Tadgeeg AI)

> دليل شامل لتطوير وتحديث منصة Tadgeeg AI / FinAI - منصة الذكاء الاصطناعي للتدقيق المالي

---

## 📋 محتويات الحزمة

| # | الملف | الوصف | الحالة |
|---|-------|--------|--------|
| 00 | `00-PROJECT-CONTEXT.md` | **السياق العام (ابدأ هنا!)** | ⭐ أساسي |
| 01 | `01-BRANDING-IDENTITY.md` | توحيد الهوية البصرية | 🎨 |
| 02 | `02-LANDING-PAGE.md` | الصفحة الرئيسية (التسويقية) | 🌐 |
| 03 | `03-AUTH-PAGES.md` | صفحات المصادقة (Login/Register/MFA) | 🔐 |
| 04 | `04-DASHBOARD.md` | لوحة التحكم الرئيسية | 📊 |
| 05 | `05-INVOICES.md` | إدارة الفواتير | 📄 |
| 06 | `06-DOCUMENTS.md` | المستندات (Bank/VAT/Payroll/PO) | 📁 |
| 07 | `07-REPORTS.md` | التقارير والـ PDF | 📈 |
| 08 | `08-AUDIT-ENGINE.md` | محرك التدقيق و30 قاعدة | 🔍 |
| 09 | `09-COMPLIANCE-ZATCA.md` | الامتثال (ZATCA Phase 2) | ✅ |
| 10 | `10-SETTINGS-MFA.md` | الإعدادات والمصادقة الثنائية | ⚙️ |
| 11 | `11-API-DEVELOPMENT.md` | تطوير API + DRF | 🔌 |
| 12 | `12-DJANGO-MODELS.md` | النماذج وقاعدة البيانات | 🗄️ |
| 13 | `13-AI-OCR-PIPELINE.md` | الذكاء الاصطناعي + OCR | 🤖 |
| 14 | `14-TESTING.md` | الاختبارات (pytest) | 🧪 |
| 15 | `15-DEPLOYMENT.md` | النشر والـ Docker | 🚀 |

---

## 🚀 كيف تستخدم هذه الحزمة؟

### الخطوة 1: احفظ السياق
في **بداية كل محادثة جديدة** مع Claude (أو Cursor / Copilot)، انسخ محتوى:
```
00-PROJECT-CONTEXT.md
```
هذا يضمن أن المساعد يفهم بنية مشروعك بالضبط.

### الخطوة 2: اختر الـ Prompt المناسب
حدد الميزة التي تريد تطويرها واذهب للملف المقابل (مثلاً للـ Dashboard اذهب لـ `04-DASHBOARD.md`).

### الخطوة 3: انسخ الـ Prompt + ارفق الكود
- انسخ الـ Prompt من الملف
- ارفق ملف الـ template / Python الذي تريد تعديله
- أضف أي تخصيصات إضافية في النهاية

### الخطوة 4: راجع الناتج
- قارن مع الكود القديم
- اختبر محلياً قبل الـ commit
- استخدم `14-TESTING.md` للتأكد من عدم كسر شيء

---

## 💡 نصائح ذهبية للحصول على أفضل النتائج

### ✅ افعل:
- **اطلب التعديل على ملف واحد في كل مرة** بدلاً من 5 ملفات معاً
- **حدد المسار الكامل** للملف (`templates/dashboard/index.html`)
- **اطلب الإبقاء على `{% trans %}`** و `{% load i18n %}` لدعم الترجمة
- **اطلب اختبارات** مع كل ميزة جديدة (`pytest tests/`)
- **اذكر إصدار Django** (4.2 LTS) عند الحاجة

### ❌ تجنب:
- لا تطلب تغيير `apps/` و `templates/` و `static/` معاً في prompt واحد
- لا تنسى ذكر أنك تستخدم **Tailwind + Alpine.js** (مش React!)
- لا تطلب من المساعد "خمن البنية" - أرفق الملف الفعلي
- لا تكسر `migrations/` بدون قراءة `09-DJANGO-MODELS.md`

---

## 🎨 الهوية البصرية (مرجع سريع)

```css
/* الألوان الأساسية */
--primary: #003366;       /* أزرق كحلي */
--primary-dark: #002244;
--primary-light: #1a4d80;
--accent: #10B981;        /* أخضر زمردي */
--accent-dark: #059669;

/* الخلفيات */
--bg: #ffffff;
--bg-soft: #f8fafc;
--bg-softer: #f1f5f9;

/* النصوص */
--text: #1e293b;
--text-muted: #64748b;
--text-light: #94a3b8;

/* الحدود */
--border: #e2e8f0;
--border-soft: #f1f5f9;

/* الحالات */
--success: #10B981;
--warning: #f59e0b;
--danger: #ef4444;
--info: #3b82f6;
```

```css
/* الخطوط */
font-family: 'Tajawal', 'Cairo', 'Segoe UI', sans-serif;
/* العناوين الكبيرة: Cairo */
/* النصوص العادية: Tajawal */
```

---

## 📞 سيناريوهات شائعة

### "أبغى أحول الصفحة الرئيسية لهوية تدقيق"
→ افتح `02-LANDING-PAGE.md` واستخدم **Prompt 2.1**

### "محتاج أضيف صفحة جديدة لإدارة الموردين"
→ افتح `06-DOCUMENTS.md` واستخدم **Prompt 6.5**

### "Tests فاشلة بعد التعديل"
→ افتح `14-TESTING.md` واستخدم **Prompt 14.3**

### "أبغى أضيف rule جديد لمحرك التدقيق"
→ افتح `08-AUDIT-ENGINE.md` واستخدم **Prompt 8.2**

### "محتاج أحدّث النماذج (Models)"
→ افتح `12-DJANGO-MODELS.md` واستخدم **Prompt 12.1**

---

## 🛡️ تحذيرات مهمة

1. **قبل تعديل أي Migration:** خذ نسخة احتياطية من `db_runtime.sqlite3`
2. **قبل نشر التحديثات:** شغّل `pytest tests/` وتأكد من نجاحها
3. **عند تعديل branding:** حدّث `core/branding.py` و `settings.py` معاً
4. **عند تعديل الترجمات:** شغّل `python manage.py makemessages -l ar` ثم `compilemessages`

---

## 📚 ملفات المرجع في المشروع

| الموضوع | الملف |
|---------|-------|
| الإعدادات الرئيسية | `finai_backend/settings.py` |
| الـ URLs | `finai_backend/urls.py` |
| الـ Branding | `core/branding.py` |
| الـ Base Template | `templates/base.html` |
| الـ Landing | `templates/landing/index.html` |
| الـ Dashboard | `templates/dashboard/index.html` |
| نماذج الفواتير | `apps/invoices/models.py` |
| 30 قاعدة تدقيق | `Docs/SYSTEM_AUDIT_RULES_VALIDATION.json` |
| البنية المعمارية | `Docs/ARCHITECTURE_REVIEW.md` |

---

## 🎯 خارطة الطريق المقترحة (إذا كنت تبدأ من الصفر)

```
أسبوع 1: هوية بصرية موحدة
├── يوم 1-2: 01-BRANDING-IDENTITY.md
├── يوم 3-4: 02-LANDING-PAGE.md
└── يوم 5-7: 03-AUTH-PAGES.md

أسبوع 2: الصفحات الأساسية
├── يوم 8-10: 04-DASHBOARD.md
├── يوم 11-12: 05-INVOICES.md
└── يوم 13-14: 06-DOCUMENTS.md

أسبوع 3: الميزات المتقدمة
├── يوم 15-17: 07-REPORTS.md
├── يوم 18-19: 08-AUDIT-ENGINE.md
└── يوم 20-21: 09-COMPLIANCE-ZATCA.md

أسبوع 4: التطوير الخلفي + النشر
├── يوم 22-23: 11-API-DEVELOPMENT.md
├── يوم 24-25: 13-AI-OCR-PIPELINE.md
├── يوم 26: 14-TESTING.md
└── يوم 27-28: 15-DEPLOYMENT.md
```

---

**🌟 تم إعداد هذه الحزمة خصيصاً لمشروع Tadgeeg AI - حزمة تتطور مع تطور مشروعك**

**النسخة:** 1.0  
**التاريخ:** 2026  
**اللغة:** عربي + English

---

**نصيحة أخيرة:** الـ Prompts الذكية = نتائج ذكية. كلما كانت تعليماتك أوضح، كان الكود الناتج أنظف وأقرب لما تريد. لا تتردد في تخصيص هذه الـ Prompts حسب احتياجك! 🚀
