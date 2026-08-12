# فحص الواجهة — 2026-08-12 · `claude @ 2f2098b` · Django 5.2.17

> `FRONTEND_CONTRACT.md` §5 لم يُنفَّذ منذ كُتب. أربعة تقارير متتالية سجّلت
> «لم أفحصها — لا بيئة». هذا أول تنفيذ فعلي.
>
> **فحص فقط. صفر تعديل على شيفرة أو قالب أو إعداد.**

## الحكم

> ## 🟡 **الواجهة سليمة جزئيًا.**
>
> الصفحات الستّ كلها تُعرض بتنسيق كامل، وAlpine ينفّذ، والملفات الساكنة
> تُخدَم من البيان المُهشَّر. **وعطلان في console على صفحتين**، أحدهما
> كامن على مسار الرفع.
>
> ترقية Django 5.2 **لم تكسر شيئًا** — العطلان في القوالب وسابقان لها.

---

## ١. البيئة

| | |
|---|---|
| `manage.py check` | `System check identified no issues (0 silenced)` |
| `DEBUG` | **False** — الاسم الصحيح `DEBUG` لا `DJANGO_DEBUG` (درس المرحلة ٢) |
| `staticfiles` | `whitenoise.storage.CompressedManifestStaticFilesStorage` ✅ |
| `default_storage` | `FileSystemStorage` |
| `ALLOWED_HOSTS` | `localhost · 127.0.0.1 · testserver · test.tadgeeg.com · 69.62.115.97` |
| `SECURE_SSL_REDIRECT` | `False` (الإعدادات الأساسية؛ `production.py` يرفعها) |
| Celery · Redis | **لا يعملان.** المهام غير المتزامنة خارج نطاق هذا الفحص |
| المتصفّح | Google Chrome بلا واجهة · `--virtual-time-budget=15000` · لقطات 1440×2400 |
| الحساب | `demo@finai.sa` — **`is_staff=False` · `is_superuser=False`** · منظمة `Demo Audit Firm` |

## ٢. `collectstatic` — تنفيذ حقيقي لا `--dry-run`

```
127 static files copied to '/home/mohamed/tadgeeg/staticfiles',
307 unmodified, 1116 post-processed.
```

**البيان بُني** — البند المفتوح من المرحلة ٢ صار مُغلقًا:

```
staticfiles/staticfiles.json   26,155 بايت · version 1.1 · 434 مدخلًا
  vendor/alpine.min.js        -> vendor/alpine.min.382e629b180f.js
  vendor/tailwind.browser.js  -> vendor/tailwind.browser.7a614b9a197e.js
```

الملف المُهشَّر يُخدَم بـ200 من whitenoise، وصفر تحذير أو خطأ في الأمر.

## ٣. الصفحات الستّ

| # | المسار | الرمز | العنوان بعد JS | التنسيق | console | شبكة |
|---|---|---|---|---|---|---|
| ١ | `/dashboard/` | 200 | Dashboard \| Tadgeeg | ✅ كامل | **صفر** | صفر 404 |
| ٢ | `/dashboard/files/` | 200 | Files \| Demo Audit Firm | ✅ كامل | 🔴 **11 خطأ** | صفر 404 |
| ٣ | `/invoices/` | 200 | Invoices \| Tadgeeg | ✅ كامل | **صفر** | صفر 404 |
| ٤ | `/reports/` | 200 | Reports \| Tadgeeg | ✅ كامل | **صفر** | صفر 404 |
| ٥ | `/platform-admin/` | 200 | Dashboard \| Tadgeeg | ✅ كامل | **صفر** | صفر 404 |
| ٦ | `/invoices/upload/` | 200 | Upload Documents \| Tadgeeg | ✅ كامل | 🔴 **2 خطأ** | صفر 404 |

`/platform-admin/` أعاد اللوحة لأن الحساب غير مشرف — **سلوك صحيح** لا كسر.

اللقطات فُحصت بصريًّا: الشريط الجانبي كامل بأيقوناته، الألوان والبطاقات
والجداول مُنسَّقة، والعربية والإنجليزية تُعرضان معًا بلا تشوّه.

## ٤. Alpine — نفّذ فعلًا

الدليل قياس لا انطباع:

* لقطة `/dashboard/` تُظهر **نافذة منبثقة مفتوحة بخلفية معتمة** — وهي
  `x-show`. صفحة جامدة تعرضها مخفية أو تعرض ترميزها.
* `style="display: none;"` في الـDOM بعد التنفيذ: dashboard 7 · invoices 8 ·
  reports 13 · upload 14. **هذه الأنماط ليست في القالب** — Alpine يكتبها
  عند تقييم `x-show` كاذبًا. وجودها إثبات تنفيذ.
* CSP يسمح: `script-src 'self' 'unsafe-inline' 'unsafe-eval'` — و`alpine.min.js`
  مُستضاف ذاتيًّا. **صفر انتهاك CSP في console على أي صفحة.**

⚠️ **ما لم أُثبته:** الضغط على زرّ والتحقّق من استجابته. Chrome بلا واجهة عبر
سطر الأوامر لا يقبل حقن أحداث بلا CDP، ولا مكتبة websocket في البيئة. فما
أثبتُّه أن Alpine **يُقيّم ويكتب في الـDOM**، لا أن مُعالِج نقرة يعمل.
هذه الفجوة تُغلق بتثبيت `playwright`، وهي شحنة مستقلة.

## ٥. الأخطاء — حرفيًا

### 🔴 `/dashboard/files/` — 11 تكرارًا

```
"Uncaught (in promise) CssSyntaxError: <css input>:49:19: The
`dark:text-vendor-200` class does not exist. If `dark:text-vendor-200` is a
custom class, make sure it is defined within a `@layer` directive.",
source: http://localhost:8000/static/vendor/tailwind.browser.7a614b9a197e.js (20)
```

الموضعان — **بحث لا ذاكرة**:

* `templates/layouts/base_vendor_dashboard.html:96`
* `templates/layouts/partials/vendor_topbar.html:16`

في كليهما `bg-vendor-50` و`text-vendor-700` تعملان، و`dark:text-vendor-200`
لا. أي أن تدرّج `vendor` معرَّف جزئيًّا في تهيئة Tailwind. الأثر: مُصرِّف
Tailwind في المتصفّح يتوقّف عند تلك المجموعة، فتضيع الأنماط التي بعدها في
الوضع الداكن.

### 🔴 `/invoices/upload/` — تكراران

```
"Uncaught TypeError: Cannot read properties of undefined (reading 'cloneNode')",
source: http://localhost:8000/static/vendor/alpine.min.382e629b180f.js (5)
```

`cloneNode` داخل Alpine يقع في معالجة `<template>` — أي `x-for` أو `x-if`
يشير إلى قالب غير موجود. **الصفحة تُعرض كاملة** (منطقة السحب والإفلات وزر
«Choose Files» ورقاقات الصيغ)، فالعطل **كامن**: القائمة التي يبنيها القالب
فارغة قبل اختيار ملف. سيظهر عند إضافة ملفات.

⚠️ لم أحدّد الـ`<template>` المعطوب — تحديده يحتاج تتبّعًا في القالب، وهو
تشخيص لشحنة الإصلاح لا لهذا الفحص.

## ٦. استدعاءات API من JS

سبع نقاط استُخرجت من الـDOM بعد التنفيذ (`fetch(` )، لا من قائمة مكتوبة:

| النقطة | الرمز | JSON |
|---|---|---|
| `/api/v1/assistant/history/` | 200 | ✅ صالح |
| `/api/v1/notifications/unread-count/` | 200 | ✅ صالح |
| `/api/v1/assistant/chat/` | 405 | ✅ صالح — POST فقط |
| `/api/v1/assistant/reset/` | 405 | ✅ صالح — POST فقط |
| `/invoices/bulk/` | 405 | ✅ صالح — POST فقط |
| `/api/v1/notifications/mark-all-read/` | 405 | ⚠️ ليس JSON |
| `/auditor/upload/` | 200 | صفحة HTML لا API |

405 على نقاط POST سلوك صحيح — فُحصت بـGET. **لا نقطة تُعيد 404 ولا 500.**

## ٧. التحقّق الآلي

```
pytest tests/test_url_resolution.py -q --no-cov
8 passed in 466.17s (0:07:46)
```

متّسق مع الصفحات: ما تحلّه الاختبارات يُعرض، وما يُعرض تحلّه.

## ٨. ملاحظات جانبية — تُسجَّل ولا تُصلَح

1. **9 من 13 حسابًا غير مشرف تُحوَّل إلى `/billing/plans/`** عند `/dashboard/`.
   بوّابة اشتراك تعمل كما صُمِّمت، لكنها تعني أن أغلب حسابات dev لا تصلح
   لفحص واجهة.
2. **النافذة الترحيبية تعلن «236 rules across 21 document types».** والعدد
   الحيّ في `RULE_INVENTORY` **191** في خمس منظومات، و236 هو عدد الكتالوج
   الذي لا يتقاطع مع المحرك بصفر رمز (الانحراف 4). **رقم مكتوب بيد يُعرض
   للمستخدم كقياس.**
3. `upgrade-insecure-requests` في CSP. لم يمنع شيئًا على `localhost` — لكنه
   قد يرفع طلبات HTTP إلى HTTPS على مضيف غير معفى.

## ٩. ما لم يُفحص وسببه

* **التفاعل الفعلي** (نقرة · قائمة منسدلة · تبديل تبويب) — لا CDP ولا
  playwright. §٤ يوضّح ما أُثبت بدلًا منه.
* **كل ما يعتمد على Celery أو Redis** — غير مشغَّلين.
* **تقرير تدقيق كامل مفتوح** — يحتاج `AuditRun` لهذه المنظمة، وعددها ثلاثة
  كلها لمنظمات أخرى.
* **الوضع الداكن** — وهو بالضبط ما يكسره خطأ §٥ الأول. لم أبدّله.
