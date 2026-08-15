# 🎨 01 — توحيد الهوية البصرية

> Prompts لتحويل ألوان وخطوط المشروع من البنفسجي/الوردي للهوية الزرقاء/الخضراء الموحدة

---

## 🎯 Prompt 1.1 — تحديث ملف `core/branding.py`

```
أعمل على مشروع Django اسمه Tadgeeg AI.

المطلوب: عدّل ملف `core/branding.py` ليُرجع معلومات branding كاملة 
لمنصة تدقيق بدلاً من القيم العامة الحالية.

أضف للـ context الراجع من `get_branding_context()` المفاتيح التالية:

1. الألوان:
   - primary_color: "#003366"
   - primary_dark: "#002244"  
   - accent_color: "#10B981"
   - accent_dark: "#059669"

2. الخطوط:
   - font_arabic: "Tajawal, Cairo, sans-serif"
   - font_english: "Inter, sans-serif"
   - font_heading: "Cairo, sans-serif"

3. اللوقو:
   - logo_svg: HTML SVG للوقو (دائرة زرقاء + علامة صح خضراء)
   - logo_url: "/static/img/logo-tadgeeg.svg"

4. URLs:
   - support_email: "support@tadgeeg.com"
   - sales_email: "sales@tadgeeg.com"
   - website_url: "https://tadgeeg.com"

5. حدّث القيم الافتراضية:
   - PRODUCT_TAGLINE_AR: "ذكاء مالي بلا حدود"
   - PRODUCT_TAGLINE_EN: "Intelligent financial auditing without limits"

أعطني الكود الكامل للملف الجديد مع المحافظة على البنية القديمة 
(`is_arabic` logic, الـ getattr pattern). 
لا تكسر أي استدعاء حالي للـ context_processor.
```

---

## 🎯 Prompt 1.2 — تحديث `templates/base.html` لاستخدام الهوية الجديدة

```
في مشروع Tadgeeg AI، الـ template الأساسي `templates/base.html` 
يستخدم Tailwind config بألوان قديمة:

```javascript
colors: {
  primary: { 50:'#eff6ff',...,900:'#1e3a8a' },  // أزرق فاتح
  ...
}
```

المطلوب: استبدل قيم `primary` لتعكس هوية تدقيق:

```javascript
window.tailwind.config = {
  darkMode: 'class',
  theme: { extend: {
    colors: {
      primary: {
        50: '#e6edf5',
        100: '#cdd9eb',
        200: '#9bb3d7',
        300: '#688dc3',
        400: '#3667af',
        500: '#003366',  // الأساسي
        600: '#002952',
        700: '#001f3d',
        800: '#001429',
        900: '#000a14',
      },
      accent: {
        50: '#ecfdf5',
        100: '#d1fae5',
        200: '#a7f3d0',
        300: '#6ee7b7',
        400: '#34d399',
        500: '#10B981',  // الأخضر
        600: '#059669',
        700: '#047857',
        800: '#065f46',
        900: '#064e3b',
      },
      // احتفظ بـ surface, sidebar, vendor كما هي
      surface: { light: '#f8fafc', dark: '#0f172a' },
      sidebar: '#003366',  // غيّر من #0f1729 للأزرق الكحلي
      vendor: { /* احتفظ بنفس القيم */ },
    },
    fontFamily: {
      sans: ['Tajawal', 'Cairo', 'Inter', '"Segoe UI"', 'system-ui', 'sans-serif'],
      heading: ['Cairo', 'Tajawal', 'sans-serif'],
      mono: ['Consolas', '"Courier New"', 'monospace'],
    },
  }}
};
```

أضف Google Fonts للـ Tajawal + Cairo في الـ <head>:
```html
<link href="https://fonts.googleapis.com/css2?family=Tajawal:wght@400;500;700;800;900&family=Cairo:wght@600;700;800;900&display=swap" rel="stylesheet">
```

في الـ <style> داخل `base.html`:
- استبدل `font-family: 'Cairo', 'Inter'...` 
- بـ `font-family: 'Tajawal', 'Cairo', 'Inter', 'Segoe UI', system-ui, sans-serif;`

في nav-item.active:
- استبدل `background: rgba(37,99,235,0.2); color: #60a5fa;`
- بـ `background: rgba(16,185,129,0.15); color: #10B981;`

في .btn-primary:
- استبدل أي gradient بنفسجي
- بـ `background: linear-gradient(135deg, #003366 0%, #002244 100%);`

أعطني الكود الكامل المعدّل مع المحافظة على:
- جميع `{% load %}` و `{% block %}` tags
- منطق `darkMode: 'class'`
- كل الـ animations والـ classes الموجودة
- نظام الترجمة `{% trans %}`
```

---

## 🎯 Prompt 1.3 — إنشاء ملف CSS موحد للهوية

```
في مشروع Tadgeeg AI، أحتاج ملف CSS موحد للهوية البصرية.

المطلوب: أنشئ ملف `static/css/tadgeeg-theme.css` يحتوي على:

1. CSS Variables في :root:
   --tg-primary: #003366
   --tg-primary-dark: #002244
   --tg-primary-light: #1a4d80
   --tg-accent: #10B981
   --tg-accent-dark: #059669
   --tg-bg: #ffffff
   --tg-bg-soft: #f8fafc
   --tg-text: #1e293b
   --tg-text-muted: #64748b
   --tg-border: #e2e8f0
   /* وكل الألوان من 00-PROJECT-CONTEXT.md */

2. Dark Mode Variables (داخل .dark أو [data-theme="dark"]):
   --tg-bg: #0f172a
   --tg-bg-soft: #1e293b
   --tg-text: #e2e8f0
   /* إلخ */

3. Utility Classes:
   .tg-btn-primary { background: var(--tg-accent); color: white; }
   .tg-btn-secondary { background: var(--tg-primary); color: white; }
   .tg-card { background: white; border-radius: 18px; box-shadow: ...; }
   .tg-input { padding: 12px 16px; border-radius: 12px; }
   .tg-badge-success { background: #dcfce7; color: #166534; }
   .tg-badge-warning { background: #fef3c7; color: #92400e; }
   .tg-badge-danger { background: #fee2e2; color: #991b1b; }

4. Logo Component:
   .tg-logo { display: flex; align-items: center; gap: 12px; }
   .tg-logo-mark { width: 40px; height: 40px; }
   .tg-logo-text-ar { font-family: Cairo; font-weight: 800; color: var(--tg-primary); }
   .tg-logo-text-en { font-family: Cairo; font-weight: 700; color: var(--tg-primary); }

5. Typography:
   .tg-h1, .tg-h2, .tg-h3 { font-family: Cairo; }
   body { font-family: Tajawal, Cairo, sans-serif; }

6. RTL Support:
   [dir="rtl"] .tg-icon-arrow { transform: scaleX(-1); }
   [dir="rtl"] .tg-card { text-align: right; }

7. Animations:
   @keyframes tg-fadeIn { ... }
   @keyframes tg-slideUp { ... }
   .tg-animate-fade { animation: tg-fadeIn 0.5s ease both; }

أعطني الملف الكامل مرتب ومعلّق بشكل واضح. سأضيفه في base.html بعد Tailwind.
```

---

## 🎯 Prompt 1.4 — إضافة Logo SVG كـ Static File

```
في مشروع Tadgeeg AI:

المطلوب: أنشئ ملف `static/img/logo-tadgeeg.svg` يحتوي على لوقو تدقيق:
- دائرة زرقاء (#003366) فارغة بـ stroke 8px
- علامة صح خضراء (#10B981) داخلها بـ stroke 9px
- Width: 100, Height: 100
- ViewBox: "0 0 100 100"

كذلك أنشئ نسخات إضافية:
- `logo-tadgeeg-light.svg` (للخلفيات الداكنة - أبيض + أخضر)
- `logo-tadgeeg-mark.svg` (الرمز فقط بدون نص)
- `logo-tadgeeg-full-ar.svg` (الرمز + كلمة "تدقيق" بخط Cairo)
- `logo-tadgeeg-full-en.svg` (الرمز + كلمة "Tadgeeg")

أعطني الكود الكامل لكل ملف SVG.
```

---

## 🎯 Prompt 1.5 — تحديث Settings للـ Branding

```
في مشروع Tadgeeg AI، ملف `finai_backend/settings.py`:

المطلوب: راجع وحدّث المتغيرات التالية:

```python
# Branding
PRODUCT_NAME = "Tadgeeg"
PRODUCT_NAME_AR = "تدقيق"
PRODUCT_TAGLINE_AR = "ذكاء مالي بلا حدود"
PRODUCT_TAGLINE_EN = "Intelligent Financial Auditing without Limits"
PRODUCT_DESCRIPTION_AR = "منصة الذكاء الاصطناعي الرائدة للتدقيق المالي والامتثال في دول الخليج"
PRODUCT_DESCRIPTION_EN = "Leading AI platform for financial auditing and compliance in GCC"

COMPANY_NAME = "Get Solution Company"
COMPANY_NAME_AR = "شركة أحصل الحل"
COMPANY_WEBSITE = "https://tadgeeg.com"
COMPANY_SUPPORT_EMAIL = "support@tadgeeg.com"
COMPANY_SALES_EMAIL = "sales@tadgeeg.com"
COMPANY_PHONE = "+966 XX XXX XXXX"

# Brand Colors (للاستخدام في التقارير والإيميلات)
BRAND_PRIMARY_COLOR = "#003366"
BRAND_ACCENT_COLOR = "#10B981"

# Default Language
LANGUAGE_CODE = "ar"
TIME_ZONE = "Asia/Riyadh"

# Email From (لإرسال OTP والإشعارات)
DEFAULT_FROM_EMAIL = "Tadgeeg AI <noreply@tadgeeg.com>"
SERVER_EMAIL = "alerts@tadgeeg.com"
```

تحقق من:
1. عدم تكرار أي مفتاح
2. القيم تستخدم `os.environ.get(...)` للـ override من البيئة
3. الـ defaults معقولة للتطوير المحلي

أعطني الكود الكامل للقسم المُحدّث (لا تعطني الملف كاملاً، بس قسم Branding).
```

---

## 🎯 Prompt 1.6 — تحديث Email Templates للـ Branding

```
في مشروع Tadgeeg AI، الـ email templates في `templates/auth/emails/`.

المطلوب: حدّث كل قوالب الإيميل (OTP, Password Reset, Welcome) لتستخدم 
الهوية الجديدة:

1. الترويسة (Header):
   - خلفية: linear-gradient(135deg, #003366 0%, #002244 100%)
   - اللوقو: SVG inline (الدائرة الزرقاء + علامة الصح)
   - العنوان: "Tadgeeg تدقيق" بخط Cairo

2. الجسم (Body):
   - خلفية: #f8fafc
   - بطاقة بيضاء وسطية بـ border-radius 16px
   - النصوص: Tajawal لو عربي، Inter لو إنجليزي
   - الأزرار: خلفية #10B981 (أخضر) للـ primary, #003366 للـ secondary

3. التذييل (Footer):
   - خلفية: #003366
   - نص: "© 2026 Tadgeeg by Get Solution Company"
   - روابط: Support, Privacy, Terms

4. للـ OTP email:
   - عرض الكود في صندوق كبير مع حدود متقطعة
   - خط الكود: Cairo Bold 32px
   - لون الكود: #10B981

استخدم inline CSS فقط (الإيميل client compatibility).
احرص على responsiveness للجوال.
احتفظ بالنصوص المترجمة `{% trans %}`.

ابدأ بـ OTP email template، ثم انتقل للباقي.
```

---

## 🎯 Prompt 1.7 — إضافة Favicon وApp Icons

```
في مشروع Tadgeeg AI:

المطلوب: أنشئ كل ملفات الـ Favicon والـ App Icons المطلوبة:

في `static/img/`:
- favicon.ico (16x16, 32x32, 48x48 multi-resolution)
- favicon-16x16.png
- favicon-32x32.png
- apple-touch-icon.png (180x180)
- android-chrome-192x192.png
- android-chrome-512x512.png
- mstile-150x150.png
- safari-pinned-tab.svg

كلها بهوية تدقيق:
- خلفية #003366
- علامة صح بيضاء أو خضراء (#10B981) واضحة

في `static/`:
- site.webmanifest:
```json
{
  "name": "Tadgeeg AI",
  "short_name": "Tadgeeg",
  "description": "AI Financial Auditing Platform",
  "icons": [...],
  "theme_color": "#003366",
  "background_color": "#ffffff",
  "display": "standalone",
  "lang": "ar",
  "dir": "rtl"
}
```
- browserconfig.xml لـ Microsoft

ثم أضف في `templates/base.html` داخل <head>:
```html
<link rel="apple-touch-icon" sizes="180x180" href="{% static 'img/apple-touch-icon.png' %}">
<link rel="icon" type="image/png" sizes="32x32" href="{% static 'img/favicon-32x32.png' %}">
<link rel="icon" type="image/png" sizes="16x16" href="{% static 'img/favicon-16x16.png' %}">
<link rel="manifest" href="{% static 'site.webmanifest' %}">
<link rel="mask-icon" href="{% static 'img/safari-pinned-tab.svg' %}" color="#003366">
<meta name="msapplication-TileColor" content="#003366">
<meta name="theme-color" content="#003366">
```

نظراً لأنك مساعد نصي، أعطني فقط:
1. كود الـ SVG لكل أيقونة
2. الـ webmanifest JSON
3. الـ HTML للـ base.html
وأخبرني كيف أحوّل الـ SVG لـ PNG/ICO باستخدام أدوات مثل ImageMagick.
```

---

## 🎯 Prompt 1.8 — Search & Replace شامل للألوان القديمة

```
في مشروع Tadgeeg AI، الألوان البنفسجية والوردية منتشرة في عدة templates.

المطلوب: ابحث في كل ملفات `templates/` عن الألوان القديمة واستبدلها 
بمكافئاتها الجديدة من هوية تدقيق:

استبدالات الألوان:
| القديم | الجديد |
|--------|--------|
| `#7c3aed` | `#003366` |
| `#6d28d9` | `#002244` |
| `#8b5cf6` | `#1a4d80` |
| `#a855f7` | `#10B981` |
| `#9333ea` | `#059669` |
| `#ec4899` | `#10B981` |
| `#f472b6` | `#34d399` |
| `from-violet-` | `from-primary-` |
| `to-violet-` | `to-primary-` |
| `bg-violet-` | `bg-primary-` |
| `text-violet-` | `text-primary-` |
| `from-purple-` | `from-primary-` |
| `bg-purple-` | `bg-primary-` |
| `text-purple-` | `text-primary-` |
| `from-pink-` | `from-accent-` |
| `bg-pink-` | `bg-accent-` |
| `text-pink-` | `text-accent-` |

أعطني سكريبت bash يستخدم `sed` للقيام بهذه الاستبدالات بأمان:
1. يأخذ نسخة احتياطية من المجلد قبل التعديل (templates.bak/)
2. يتجاهل الـ backups والـ .git
3. يطبع كل ملف تم تعديله مع عدد الاستبدالات
4. يدعم التراجع (undo) عبر استرجاع backups

استخدم find + sed بشكل آمن (POSIX-compatible).
```

---

## ✅ Checklist بعد تطبيق هذا القسم

- [ ] `core/branding.py` محدّث بالألوان والمعلومات الجديدة
- [ ] `templates/base.html` يستخدم #003366 بدل البنفسجي
- [ ] `static/css/tadgeeg-theme.css` موجود ومُحمّل في base.html
- [ ] `static/img/logo-tadgeeg.svg` موجود وكل أحجامه
- [ ] `finai_backend/settings.py` فيه كل المتغيرات الجديدة
- [ ] Email templates محدّثة للهوية الجديدة
- [ ] Favicons + manifest محدّثة
- [ ] لا توجد ألوان `#7c3aed`, `#ec4899`, `violet-`, `purple-`, `pink-` في templates
- [ ] الموقع يعمل بدون أخطاء بعد التحديث
- [ ] الـ Dark mode يعمل مع الألوان الجديدة

---

**📌 بعد إكمال هذا القسم، انتقل لـ `02-LANDING-PAGE.md`**
