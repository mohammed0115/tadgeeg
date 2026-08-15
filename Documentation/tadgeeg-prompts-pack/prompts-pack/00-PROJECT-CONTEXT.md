# 📌 السياق العام لمشروع Tadgeeg AI

> **⚠️ هام جداً:** انسخ هذا الملف بالكامل في **بداية كل محادثة** مع Claude / Cursor / Copilot قبل أي طلب آخر. هذا يضمن فهم المساعد لبنية المشروع بدقة.

---

## 🏢 معلومات المنصة

```yaml
اسم المنتج: Tadgeeg AI (تدقيق)
الكود الداخلي: FinAI
الشركة المطورة: Get Solution Company (شركة أحصل الحل)
الفئة: B2B SaaS - منصة تدقيق مالي بالذكاء الاصطناعي
السوق المستهدف: الشركات والمحاسبين القانونيين في دول الخليج
اللغات: العربية (RTL) + الإنجليزية (LTR)
```

---

## 🛠️ Stack التقنية

```yaml
# Backend
Framework: Django 4.2 LTS
API: Django REST Framework + drf-spectacular (Swagger/ReDoc)
Auth: JWT (simplejwt) + Session + MFA/TOTP
Task Queue: Celery 5 + Redis 7
Database: SQLite 3 (default) — ready for PostgreSQL
Python: 3.11

# AI / OCR
LLM: OpenAI GPT-4o Vision
OCR: Tesseract 5
Image Processing: Pillow + opencv-python

# Frontend (Server-side rendering)
Templates: Django Templates (NOT React/Vue!)
CSS: Tailwind CSS (CDN: vendor/tailwind.browser.js)
JS: Alpine.js 3 (مش React/Vue!)
Charts: Chart.js 4
Icons: Lucide Icons

# Deployment
Containers: Docker + Docker Compose
Web Server: Gunicorn + Nginx
Static: WhiteNoise
SSL: Let's Encrypt (Certbot)
```

---

## 📂 بنية المشروع الكاملة

```
tadgeeg-main/
├── apps/                          # كل الـ Django apps
│   ├── activity_logs/             # سجلات النشاط
│   ├── analytics/                 # التحليلات والإحصائيات
│   ├── audit/                     # جلسات التدقيق
│   ├── audit_engine/              # محرك التدقيق الأساسي
│   ├── auditing/                  # تدقيق المستندات بالذكاء الاصطناعي
│   ├── authentication/            # المصادقة + Organization + User
│   ├── cms/                       # إدارة المحتوى
│   ├── compliance/                # الامتثال (ZATCA, FTA)
│   ├── core_engine/               # المحرك الأساسي
│   ├── documents/                 # المستندات (PO, Bank, VAT, Payroll, ...)
│   ├── file_management/           # إدارة الملفات
│   ├── frontend/                  # صفحات الواجهة (Landing, Dashboard)
│   ├── invoices/                  # الفواتير + 30 قاعدة تدقيق
│   ├── jobs/                      # Background jobs
│   ├── leads/                     # العملاء المحتملين
│   ├── organization_admin/        # إدارة المنظمة
│   ├── organization_settings/     # إعدادات المنظمة
│   ├── organization_users/        # مستخدمين المنظمة
│   ├── platform_admin/            # لوحة Get Solution الإدارية
│   ├── platform_management/       # إدارة المنصة
│   ├── reporting/                 # خدمات التقارير
│   ├── reports/                   # التقارير + PDF generation
│   ├── rule_engine/               # محرك القواعد
│   ├── storage_management/        # إدارة التخزين
│   ├── system_monitoring/         # مراقبة النظام
│   ├── transactions/              # المعاملات المالية
│   ├── vendor_dashboard/          # لوحة المورد/المنظمة
│   └── workflow/                  # مسارات العمل
│
├── core/                          # الأدوات المشتركة
│   ├── auth/
│   ├── branding.py                # ⭐ معلومات العلامة التجارية
│   ├── constants.py               # الثوابت (VAT_RATE = 0.15)
│   ├── context_processors.py
│   ├── dashboard_context.py
│   ├── domain/
│   ├── health_check_views.py
│   ├── mixins.py                  # SoftDeleteModel وغيرها
│   ├── navigation/
│   ├── permissions.py
│   ├── services/                  # الخدمات الأساسية
│   ├── signals.py
│   ├── utils/
│   └── websocket.py
│
├── finai_backend/                 # إعدادات Django
│   ├── settings.py                # ⭐ الإعدادات الرئيسية
│   ├── settings_canonical.py
│   ├── settings/                  # إعدادات بيئية
│   ├── urls.py                    # ⭐ كل الـ URLs
│   ├── celery.py
│   ├── routing.py
│   ├── asgi.py
│   └── wsgi.py
│
├── templates/                     # قوالب Django
│   ├── base.html                  # ⭐ القالب الأساسي
│   ├── 404.html, 500.html
│   ├── analytics/, audit/, auditing/
│   ├── auth/                      # تسجيل الدخول، MFA، إعادة تعيين
│   ├── cms_admin/, compliance/
│   ├── components/                # مكونات قابلة لإعادة الاستخدام
│   ├── dashboard/                 # لوحة التحكم
│   ├── documents/                 # PO, Bank, VAT, Payroll, ...
│   ├── invoices/                  # قوائم وتفاصيل الفواتير
│   ├── landing/                   # الصفحة الرئيسية التسويقية
│   ├── layouts/                   # تخطيطات
│   ├── partials/                  # أجزاء مشتركة
│   ├── phase2/                    # ميزات المرحلة 2
│   ├── platform_admin/            # لوحة الإدارة
│   ├── reports/                   # التقارير + PDF
│   ├── settings/                  # الإعدادات
│   ├── storage_management/
│   ├── transactions.html
│   ├── users/
│   ├── vendor_dashboard/
│   └── vendors/
│
├── static/                        # الملفات الثابتة
│   ├── img/
│   └── vendor/                    # tailwind, alpine, chart, lucide
│
├── locale/                        # الترجمات
│   ├── ar/                        # العربية
│   └── en/                        # الإنجليزية
│
├── tests/                         # الاختبارات (pytest)
│   ├── conftest.py
│   ├── test_*.py                  # ~50 ملف اختبار
│   └── ...
│
├── deployment/                    # سكريبتات النشر
│   ├── 00_env_check.sh
│   ├── 01_git_sync.sh
│   ├── 02_system_setup.sh
│   ├── 03_ocr_setup.sh            # تثبيت Tesseract
│   ├── 04_gunicorn_service.sh
│   ├── 05_nginx_setup.sh
│   ├── 06_ssl_setup.sh
│   ├── 07_monitoring.sh
│   └── server_init.sh
│
├── docker/                        # ملفات Docker
│   ├── entrypoint.sh
│   └── nginx/
│
├── Documentation/                          # التوثيق
│   ├── ARCHITECTURE_REVIEW.md
│   ├── API_REFERENCE.md
│   ├── SYSTEM_AUDIT_RULES_VALIDATION.json  # 30 قاعدة
│   ├── OCR_AI_PIPELINE.md
│   ├── MFA_TOTP_IMPLEMENTATION_GUIDE.md
│   ├── SRS_AI_Financial_Auditing_System.docx
│   ├── ai_implementation_prompts.md
│   └── ...
│
├── Dockerfile, Dockerfile.optimized
├── docker-compose.yml
├── manage.py
├── requirements.txt
├── pytest.ini
└── README.md
```

---

## 🎨 الهوية البصرية المستهدفة (تدقيق)

### ⚠️ المشكلة الحالية
الصفحة الرئيسية (`templates/landing/index.html`) تستخدم **ألوان بنفسجية** غير متوافقة مع هوية تدقيق:
- ❌ `#7c3aed` (بنفسجي)
- ❌ `#ec4899` (وردي)
- ❌ `#3b82f6` (أزرق فاتح)

### ✅ الهوية الصحيحة (تدقيق)
```css
:root {
  /* الأساسية */
  --primary: #003366;        /* أزرق كحلي - الهوية الأساسية */
  --primary-dark: #002244;
  --primary-light: #1a4d80;
  
  /* التمييز */
  --accent: #10B981;         /* أخضر زمردي - علامة الصح */
  --accent-dark: #059669;
  --accent-light: #34d399;
  
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
}
```

### 🔤 الخطوط
```css
font-family: 'Tajawal', 'Cairo', 'Segoe UI', sans-serif;
/* النصوص: Tajawal */
/* العناوين: Cairo (700-900) */
/* English: Inter */
```

### 🎯 اللوقو
```html
<!-- دائرة زرقاء بداخلها علامة صح خضراء -->
<svg viewBox="0 0 100 100">
  <circle cx="50" cy="50" r="40" stroke="#003366" stroke-width="8" fill="none"/>
  <path d="M28 50 L44 66 L72 36" 
        stroke="#10B981" stroke-width="9" 
        fill="none" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
```

---

## 🔑 الميزات الرئيسية للمنصة

1. **OCR + GPT-4o Vision**: استخراج البيانات من PDF/صور
2. **30 قاعدة تدقيق**: تتحقق من الفواتير تلقائياً
3. **كشف التكرار**: SHA-256 hashing + business logic
4. **تقييم المخاطر**: 0-100 score → Low/Medium/High/Critical
5. **توليد روايات**: AI audit narratives بالعربي والإنجليزي
6. **ZATCA Phase 2**: متوافقة مع QR Code, Digital Signature, UUID
7. **Multi-tenant**: عزل البيانات بين المنظمات
8. **MFA / TOTP**: مصادقة ثنائية
9. **GDPR Hard Delete**: حذف البيانات بشكل آمن
10. **Rate Limiting**: حماية من الإفراط في الاستخدام

---

## 🔌 نقاط API الرئيسية

```
/api/v1/auth/                  # المصادقة والمستخدمين
/api/v1/documents/             # المستندات
/api/v1/invoices/              # الفواتير
/api/v1/transactions/          # المعاملات
/api/v1/audit/                 # التدقيق
/api/v1/analytics/             # التحليلات
/api/v1/compliance/            # الامتثال
/api/v1/reports/               # التقارير
/api/v1/rule-engine/           # محرك القواعد
/api/v1/health/                # الفحص الصحي

# Frontend
/                              # Landing page
/login/                        # تسجيل الدخول
/dashboard/                    # لوحة التحكم
/auditor/                      # تدقيق المستندات
/dashboard/                    # لوحة المنظمة
/platform-admin/               # لوحة Get Solution

# Docs
/api/docs/                     # Swagger UI
/api/redoc/                    # ReDoc
/api/schema/                   # OpenAPI Schema
```

---

## 📝 قوانين البرمجة المهمة

### في الـ Templates:
```django
{% load static i18n %}
{% trans "Dashboard" %}              <!-- ✅ للترجمات -->
{% blocktrans %}...{% endblocktrans %} <!-- ✅ للنصوص الطويلة -->
{{ product_name }}                    <!-- ✅ من branding.py -->
```

### في الـ Views:
```python
from django.contrib.auth.decorators import login_required
from django.utils.translation import gettext as _
from rest_framework.permissions import IsAuthenticated

# ✅ استخدم class-based views
# ✅ استخدم DRF لـ API
# ✅ استخدم decorators للحماية
```

### في الـ Models:
```python
from core.mixins import SoftDeleteModel  # ✅ بدل Model
from django.utils.translation import gettext_lazy as _

class MyModel(SoftDeleteModel):
    name = models.CharField(_("Name"), max_length=200)
    
    class Meta:
        verbose_name = _("My Model")
        verbose_name_plural = _("My Models")
```

### للترجمات:
```bash
python manage.py makemessages -l ar
python manage.py makemessages -l en
python manage.py compilemessages
```

---

## ⚙️ المتغيرات الأساسية في settings.py

```python
PRODUCT_NAME = "Tadgeeg"
COMPANY_NAME = "Get Solution Company"
COMPANY_NAME_AR = "شركة أحصل الحل"
LANGUAGE_CODE = "ar"  # العربية افتراضياً
LANGUAGES = [("ar", "العربية"), ("en", "English")]

# Apps المثبتة (مهم: التسلسل!)
INSTALLED_APPS = [
    # Django apps...
    'apps.authentication',  # دائماً قبل المنظمة
    'apps.frontend',        # قبل vendor_dashboard
    'apps.invoices',
    'apps.documents',
    # ...
]
```

---

## 🚨 محاذير عامة

1. **لا تستبدل** Tailwind بـ Bootstrap أو غيره
2. **لا تستبدل** Alpine.js بـ React/Vue
3. **لا تكسر** نظام الترجمات (`{% trans %}`)
4. **لا تكسر** نظام الـ multi-tenant (`organization` field)
5. **لا تحذف** `SoftDeleteModel` من الـ models
6. **لا تنسى** إضافة `migrations` بعد تعديل النماذج
7. **لا تهمل** الاختبارات في `tests/`
8. **لا تستخدم** ألوان بنفسجية! (الهوية أزرق + أخضر)

---

## 🎯 عند طلب أي تعديل، أخبر المساعد:

```
المشروع: Tadgeeg AI - منصة Django 4.2 للتدقيق المالي
الـ Stack: Django + DRF + Tailwind + Alpine.js + Chart.js
اللغات: عربي (RTL) + English (LTR)
الهوية: #003366 (أزرق) + #10B981 (أخضر) + Tajawal/Cairo

[ثم اطلب التعديل المحدد]
```

---

**📌 هذا الملف يجب أن يكون مرجعك الأول. كلما حدث تطوير في المشروع، حدّث هذا الملف.**
