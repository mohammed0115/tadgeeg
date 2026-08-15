# Dashboard Files - Complete Inventory

## Overview
This document catalogs every file related to the Tadgeeg Executive Dashboard, organized by category.

---

## 1. TEMPLATE FILES

### Main Dashboard Template
```
templates/dashboard/
└── index.html (1,100 lines)
    ├─ Purpose: Primary dashboard UI
    ├─ Extends: base.html
    ├─ Renders: Hero section, KPI cards, charts, panels
    ├─ State Management: Alpine.js x-data="dashboard()"
    ├─ Styling: Tailwind CSS + inline styles
    ├─ Icons: Lucide (layout-dashboard, triangle-alert, etc.)
    ├─ Charts: Chart.js (cash flow line chart)
    └─ Features:
       ├─ 4 KPI cards (invoices, amount, compliance, risk)
       ├─ Cash flow visualization (6-month trend)
       ├─ Risk distribution (4 severity levels)
       ├─ Top vendors (top 5)
       ├─ Rule compliance (6 audit rules)
       ├─ Alert panel (critical items)
       ├─ Audit sessions summary
       ├─ Big Four compliance matrix (conditional)
       ├─ Industry benchmark comparison (conditional)
       └─ Quick action buttons
```

### Base Layout Template
```
templates/base.html (1,500+ lines)
   ├─ Purpose: Master layout for entire application
   ├─ Contains: Sidebar, navigation, toast system, script tags
   ├─ Sidebar Navigation:
   │  └─ Dashboard link: {% url 'frontend:dashboard' %}
   ├─ Toast System: x-data="toastStore()" for notifications
   ├─ Global Styles: Tailwind, animations, scrollbars
   ├─ Script Includes:
   │  ├─ Alpine.js
   │  ├─ Chart.js
   │  ├─ Lucide icons
   │  ├─ TailwindCSS (via CDN or build)
   │  └─ Custom apiFetch() wrapper
   └─ Block Overrides:
      ├─ {% block title %} → "Dashboard"
      ├─ {% block nav_dashboard %} active
      ├─ {% block page_title %} → "Dashboard"
      ├─ {% block content %} → dashboard-specific content
      └─ {% block page_js %} → Alpine.js state
```

### Partial Templates
```
templates/partials/
└── language_switcher.html
    ├─ Purpose: Language toggle (EN/AR)
    ├─ Affects: html[lang] and html[dir]
    └─ Used in: Base layout
```

---

## 2. BACKEND VIEW FILES

### Frontend Views
```
apps/frontend/
├── frontend_views.py
│   ├─ dashboard(request) [Lines: 113-115]
│   │  ├─ Decorator: @login_required(login_url='/login/')
│   │  ├─ Context Variables:
│   │  │  ├─ pending_count (flagged invoices)
│   │  │  ├─ active: 'dashboard'
│   │  │  ├─ monthly_growth: 12 (override)
│   │  │  ├─ product_name
│   │  │  └─ company_byline
│   │  └─ Template: 'dashboard/index.html'
│   │
│   └─ _ctx(request, active, **extra) [Helper Function]
│      ├─ Builds shared template context
│      ├─ Counts pending flagged invoices
│      └─ Returns dict with all context vars
│
└── frontend_urls.py
    ├─ path('',            views.dashboard, name='home')
    ├─ path('dashboard/',  views.dashboard, name='dashboard')
    └─ Note: '' and 'dashboard/' both route to same view
```

### Invoice Views
```
apps/invoices/views.py
│
├── SpendAnalysisReportView [APIView - Lines: 1373+]
│   ├─ Endpoint: GET /invoices/reports/spend/
│   ├─ Authentication: IsAuthenticated
│   ├─ Query Params: None (auto-filters org)
│   ├─ Returns JSON:
│   │  ├─ overall: { total_invoices, grand_total }
│   │  ├─ monthly_trend: [{ month, total, count, flagged }, ...]
│   │  └─ by_vendor: [{ vendor_name, total, count }, ...]
│   ├─ Dashboard Usage: loadSpendReport()
│   └─ Features:
│      ├─ 6+ month historical trend
│      ├─ Top 5 vendors breakdown
│      └─ Aggregated invoice stats
│
├── InvoiceListView [ListAPIView]
│   ├─ Endpoint: GET /invoices/
│   ├─ Query Filters:
│   │  ├─ status (flagged, approved, rejected, validated, etc.)
│   │  ├─ risk_level (low, medium, high, critical)
│   │  ├─ vendor_name
│   │  ├─ is_duplicate (true/false)
│   │  ├─ date_from / date_to
│   │  ├─ min_amount / max_amount
│   │  ├─ search (vendor or invoice number)
│   │  └─ batch_id
│   ├─ Dashboard Usage: 
│   │  ├─ loadReviewQueues() [4 parallel queries]
│   │  │  ├─ ?status=flagged&page_size=5
│   │  │  ├─ ?is_duplicate=true&page_size=1
│   │  │  ├─ ?risk_level=low&page_size=1
│   │  │  ├─ ?risk_level=medium&page_size=1
│   │  │  ├─ ?risk_level=high&page_size=1
│   │  │  └─ ?risk_level=critical&page_size=1
│   └─ Serializer: InvoiceListSerializer
│
└── VendorListView [APIView]
    ├─ Endpoint: GET /invoices/vendors/
    ├─ Dashboard Usage: None (but related)
    └─ Returns: Vendor profiles with stats
```

### Audit Views
```
apps/audit/views.py
│
├── AuditDashboardOverviewView [APIView - Lines: 327+]
│   ├─ Endpoint: GET /audit/dashboard/overview/
│   ├─ Authentication: JWTAuthentication, SessionAuthentication
│   ├─ Returns JSON:
│   │  ├─ recent_sessions: Last 5 AuditSessions
│   │  ├─ latest_summary: HTML-safe narrative (Arabic)
│   │  ├─ finding_totals: { critical, high, medium, low }
│   │  ├─ recent_findings: Top 6 findings
│   │  └─ rule_groups: Compliance breakdown (6 rules)
│   ├─ Dashboard Usage: loadAuditOverview()
│   └─ Features:
│      ├─ Session summaries via AuditSessionSummaryService
│      ├─ Finding aggregation by severity
│      └─ Rule group compliance percentages
│
├── BigFourComplianceView [APIView - Lines: 375+]
│   ├─ Endpoint: GET /audit/big-four/
│   ├─ Returns JSON:
│   │  ├─ firms: [{ firm, description, standard, pass_rate, status, passed, failed, total }, ...]
│   │  └─ overall_pass_rate: Percentage
│   ├─ Dashboard Usage: loadBigFour() [Extended state]
│   └─ Features:
│      ├─ KPMG, Deloitte, PwC, EY compliance scores
│      ├─ Per-firm audit standards
│      └─ Overall compliance percentage
│
└── [Other audit views use AuditSession, AuditFinding models]
```

### Analytics Views
```
apps/analytics/views.py
│
└── IndustryBenchmarkView [APIView - Lines: 494+]
    ├─ Endpoint: GET /analytics/benchmark/?industry=finance
    ├─ Returns JSON:
    │  ├─ industry_label: "Finance & Banking (KSA)"
    │  ├─ metrics:
    │  │  ├─ compliance_rate_pct: { value, benchmark, delta, status }
    │  │  ├─ duplicate_rate_pct: { ... }
    │  │  ├─ avg_risk_score: { ... }
    │  │  └─ vat_compliance_rate_pct: { ... }
    │  └─ summary: { overall_position, metrics_above_benchmark, ... }
    ├─ Dashboard Usage: loadBenchmark() [Extended state]
    └─ Features:
       ├─ Saudi industry benchmark data
       ├─ Above/below/at comparison status
       └─ Delta calculations
```

### Audit Services
```
apps/audit/services/

├── summaries.py
│   └── AuditSessionSummaryService [Class]
│       ├─ Static Method: generate_summary(session, language="ar", use_ai=False)
│       │  ├─ Returns: HTML-formatted narrative summary
│       │  ├─ Language Support: Arabic (ar), English (en)
│       │  ├─ AI Integration: Optional (use_ai flag)
│       │  └─ Dashboard Usage: loadAuditOverview() → latestSessionSummary
│       ├─ Static Method: sync_session_context(session)
│       └─ Model: Stores summary narratives in AuditSession.context
│
└── audit_sessions.py
    └── AuditSessionService [Class]
        ├─ Methods:
        │  ├─ create_session(organization, created_by, name, total_count, context)
        │  ├─ advance_to_extracting(session)
        │  ├─ advance_to_validating(session)
        │  ├─ record_success(session, invoice, review_required)
        │  ├─ record_failure(session, message)
        │  ├─ finalize_if_ready(session)
        │  └─ [Session state management methods]
        └─ Used by: Invoice upload pipeline
```

---

## 3. URL CONFIGURATION FILES

```
finai_backend/urls.py (Main URL Config)
├─ from apps.audit.views import AuditDashboardOverviewView
├─ from apps.compliance.views import ComplianceDashboardView
├─ Routes:
│  ├─ path("api/v1/compliance/dashboard/", ComplianceDashboardView.as_view(), ...)
│  └─ path("audit/dashboard/overview/", AuditDashboardOverviewView.as_view(), ...)
│
apps/frontend/frontend_urls.py
├─ path('', views.dashboard, name='home')
├─ path('dashboard/', views.dashboard, name='dashboard')
├─ [Other frontend page routes]
│
apps/invoices/urls.py
├─ path("reports/spend/", views.SpendAnalysisReportView.as_view(), name="spend-analysis-report")
│
apps/audit/urls.py
├─ path("dashboard/overview/", views.AuditDashboardOverviewView.as_view(), name="dashboard-overview")
├─ path("big-four/", views.BigFourComplianceView.as_view(), name="big-four-compliance")
│
apps/analytics/urls.py
└─ path("benchmark/", views.IndustryBenchmarkView.as_view(), name="industry-benchmark")
```

---

## 4. STATIC FILES

```
static/
├── vendor/
│   └── lucide.min.js
│       ├─ Size: ~50KB (minified)
│       ├─ Icons Used:
│       │  ├─ layout-dashboard (hero section)
│       │  ├─ triangle-alert (flagged invoices)
│       │  ├─ bell-ring (alerts)
│       │  ├─ shield-alert (compliance)
│       │  ├─ badge-check (good status)
│       │  ├─ calendar-days (date)
│       │  ├─ file-plus-2 (upload)
│       │  ├─ x (close buttons)
│       │  └─ [50+ other icons]
│       └─ Usage: x-init="lucide.createIcons()" in template
│
├── img/
│   ├─ logo.png (Tadgeeg branding)
│   └─ flags/ (language flags)
│
└── js/
    ├─ Chart.js (via CDN or vendored)
    ├─ Alpine.js (via CDN or vendored)
    └─ TailwindCSS (via CDN or build output)
```

---

## 5. CONTEXT PROCESSORS

```
core/context_processors.py
│
├─ Function: dashboard_ctx(request)
│  ├─ Returns dict:
│  │  ├─ product_name: "Tadgeeg" (or configured)
│  │  ├─ company_byline: "AI-Powered Audit"
│  │  ├─ current_year: timezone.now().year
│  │  └─ [Other global context]
│  └─ Registered in: settings.TEMPLATES[0]['OPTIONS']['context_processors']
│
└─ Django Loads: {% load i18n %} for translations
```

---

## 6. MODELS (Referenced)

### Invoice Model
```python
# Path: apps/invoices/models.py
class Invoice(models.Model):
    organization = ForeignKey(Organization)
    uploaded_by = ForeignKey(User)
    batch = ForeignKey(InvoiceBatch)
    audit_session = ForeignKey(AuditSession)
    
    # Fields displayed on dashboard
    invoice_number = CharField(max_length=100)
    invoice_date = DateField()
    due_date = DateField()
    vendor_name = CharField(max_length=255)
    vendor_vat_number = CharField(max_length=15)
    customer_name = CharField(max_length=255)
    customer_vat_number = CharField(max_length=15)
    
    subtotal = DecimalField()
    vat_amount = DecimalField()
    vat_rate = DecimalField()
    discount = DecimalField()
    total_amount = DecimalField()
    currency = CharField(default="SAR")
    
    status = CharField(choices=["approved", "rejected", "flagged", "validated"])
    risk_level = CharField(choices=["low", "medium", "high", "critical"])
    risk_score = DecimalField()
    is_duplicate = BooleanField()
    ai_summary = TextField()
```

### AuditSession Model
```python
# Path: apps/audit/models.py
class AuditSession(models.Model):
    organization = ForeignKey(Organization)
    created_by = ForeignKey(User)
    name = CharField(max_length=255)
    status = CharField(choices=["pending", "extracting", "normalizing", "validating", "completed"])
    total_count = IntegerField()
    processed_count = IntegerField()
    context = JSONField()  # Stores summary narratives
    created_at = DateTimeField(auto_now_add=True)
```

### AuditFinding Model
```python
# Path: apps/audit/models.py
class AuditFinding(models.Model):
    audit_session = ForeignKey(AuditSession)
    invoice = ForeignKey(Invoice)
    organization = ForeignKey(Organization)
    severity = CharField(choices=["critical", "high", "medium", "low"])
    status = CharField(choices=["open", "reviewed", "resolved"])
    last_detected_at = DateTimeField(auto_now=True)
```

### VendorProfile Model
```python
# Path: apps/invoices/models.py
class VendorProfile(models.Model):
    organization = ForeignKey(Organization)
    vendor_name = CharField(max_length=255)
    vendor_vat_number = CharField()
    
    invoice_count = IntegerField()
    total_amount = DecimalField()
    avg_invoice_amount = DecimalField()
    max_invoice_amount = DecimalField()
    flagged_count = IntegerField()
    duplicate_count = IntegerField()
    is_new = BooleanField()
    first_seen = DateField()
    last_seen = DateField()
```

---

## 7. SETTINGS & CONFIGURATION

```
finai_backend/settings.py
│
├─ TEMPLATES Configuration:
│  ├─ BACKEND: 'django.template.backends.django.DjangoTemplates'
│  ├─ DIRS: [BASE_DIR / 'templates']
│  ├─ APP_DIRS: True
│  └─ context_processors:
│     ├─ django.template.context_processors.debug
│     ├─ django.template.context_processors.request
│     ├─ django.contrib.auth.context_processors.auth
│     ├─ django.contrib.messages.context_processors.messages
│     ├─ django.template.context_processors.i18n
│     └─ core.context_processors.dashboard_ctx
│
├─ INSTALLED_APPS:
│  ├─ 'apps.frontend'
│  ├─ 'apps.invoices'
│  ├─ 'apps.audit'
│  ├─ 'apps.analytics'
│  └─ [Others]
│
├─ Internationalization (i18n):
│  ├─ LANGUAGE_CODE: 'ar' (default) or 'en'
│  ├─ LANGUAGES: [('ar', 'العربية'), ('en', 'English')]
│  ├─ USE_I18N: True
│  ├─ USE_L10N: True
│  └─ LOCALE_PATHS: [BASE_DIR / 'locale']
│
└─ REST_FRAMEWORK:
   ├─ DEFAULT_AUTHENTICATION_CLASSES: [JWTAuthentication, SessionAuthentication]
   ├─ DEFAULT_PERMISSION_CLASSES: [IsAuthenticated]
   ├─ DEFAULT_PAGINATION_CLASS: PageNumberPagination
   └─ PAGE_SIZE: 100
```

---

## 8. API DOCUMENTATION FILES

```
docs/
├─ README.md (General overview)
├─ DEPLOYMENT_GUIDE.md (Deployment instructions)
├─ API_REFERENCE.md (Full API documentation)
│  ├─ Includes endpoint definitions
│  ├─ Request/response schemas
│  └─ Authentication details
│
└─ [App-specific docs]
```

---

## 9. DEPENDENCIES & LIBRARIES

### Python Backend
```
Django 4.2+                  → Web framework
djangorestframework         → API views & serializers
djangorestframework-simplejwt → JWT tokens
django-cors-headers        → CORS support
python-decouple            → Environment config
celery                     → Async task queue
redis                      → Cache & broker
```

### Frontend (CDN/Vendored)
```
Alpine.js 3.x              → State management & reactivity
Chart.js 3.x               → Chart visualization
Tailwind CSS 3.x           → Utility-first CSS
Lucide Icons               → Icon library
```

### Build Tools (Optional)
```
TailwindCSS CLI            → Compile Tailwind CSS
PostCSS                    → CSS processing
```

---

## 10. INTERNATIONALIZATION (i18n)

### Arabic Translations
```
locale/ar/LC_MESSAGES/
├─ django.po               ← Translation strings
└─ django.mo               ← Compiled translations
   ├─ Dashboard title & headings
   ├─ Button labels (Upload, Review, etc.)
   ├─ Status labels (Completed, Pending, etc.)
   ├─ Error messages
   └─ All alert text
```

### English Translations
```
locale/en/LC_MESSAGES/
├─ django.po
└─ django.mo
```

### Template Strings
```
{% trans "Dashboard" %}     ← Single-line strings
{% blocktrans %}...{% endblocktrans %}  ← Multi-line blocks
{{ variable|default:"fallback" }}
```

---

## 11. DOCUMENTATION FILES

```
Project Root/
├──  DASHBOARD_ARCHITECTURE.md (This comprehensive guide)
│    ├─ 16 sections covering all aspects
│    ├─ Architecture diagrams
│    ├─ Data flow documentation
│    ├─ API endpoint summary
│    └─ Security & performance notes
│
├──  DASHBOARD_QUICK_REFERENCE.md (Quick lookup guide)
│    ├─ Facts & quick map
│    ├─ State object structure
│    ├─ API response formats
│    ├─ Common issues & solutions
│    └─ Development checklist
│
└──  DASHBOARD_FILES_INVENTORY.md (This file)
     ├─ Complete file catalog
     ├─ Purpose of each file
     ├─ Models & dependencies
     └─ Configuration details
```

---

## 12. TESTING FILES (Not Dashboard-Specific)

```
tests/
├─ test_dashboard.py (if exists)
│  ├─ test_dashboard_access()
│  ├─ test_dashboard_context()
│  └─ test_spend_report_api()
│
├─ test_invoices.py
│  ├─ test_spend_analysis_report()
│  └─ test_invoice_list()
│
└─ test_audit.py
   ├─ test_dashboard_overview()
   └─ test_big_four_view()
```

---

## 13. LOGGING & MONITORING

```
logs/
├─ dashboard.log (if configured)
├─ api.log
└─ errors.log (errors only)

Configuration in settings.py:
LOGGING = {
    'version': 1,
    'handlers': {
        'file': {
            'filename': BASE_DIR / 'logs' / 'dashboard.log',
            'level': 'INFO',
        }
    }
}
```

---

## 14. DATABASE MIGRATIONS

```
apps/*/migrations/
├─ apps/invoices/migrations/
│  ├─ 0001_initial.py
│  ├─ [...migration files...]
│  └─ [Creates Invoice, InvoiceBatch, VendorProfile models]
│
├─ apps/audit/migrations/
│  ├─ 0001_initial.py
│  ├─ [...migration files...]
│  └─ [Creates AuditSession, AuditFinding models]
│
└─ apps/analytics/migrations/
   └─ [Schema for analytics models]

Migration Commands:
python manage.py makemigrations
python manage.py migrate
```

---

## 15. ENVIRONMENT & SECRETS

```
.env (Root directory - NOT in version control)
├─ DEBUG = False
├─ SECRET_KEY = "..."
├─ ALLOWED_HOSTS = "dashboard.example.com"
├─ DATABASE_URL = "postgresql://user:pass@host/dbname"
├─ REDIS_URL = "redis://localhost:6379"
├─ DEFAULT_CURRENCY = "SAR"
├─ TIMEZONE = "Asia/Riyadh"
├─ LANGUAGE_CODE = "ar"
└─ JWT_SECRET_KEY = "..."
```

---

## 16. QUICK FILE SUMMARY TABLE

| File | Type | Lines | Purpose |
|------|------|-------|---------|
| dashboard/index.html | Template | 1,100 | Main dashboard UI |
| frontend_views.py | Python | 150+ | View functions |
| frontend_urls.py | Python | 30+ | URL routing |
| invoices/views.py | Python | 1,500+ | Invoice APIs |
| audit/views.py | Python | 1,500+ | Audit APIs |
| analytics/views.py | Python | 500+ | Analytics APIs |
| audit/services/summaries.py | Python | 200+ | Summary generation |
| base.html | Template | 1,500+ | Base layout |
| lucide.min.js | JS | 50KB | Icon library |
| settings.py | Python | 500+ | Django config |

---

## 17. DEPENDENCIES MAP

```
dashboard/index.html
├─ base.html
│  ├─ Alpine.js v3+
│  ├─ Chart.js v3+
│  ├─ Lucide Icons
│  ├─ TailwindCSS v3+
│  └─ Django i18n
├─ frontend_views.dashboard()
│  └─ core/context_processors.py
├─ 5 API Endpoints
│  ├─ /invoices/reports/spend/ → InvoiceListView + aggregation
│  ├─ /invoices/?status=flagged → InvoiceListView
│  ├─ /audit/dashboard/overview/ → AuditDashboardOverviewView → AuditSessionSummaryService
│  ├─ /audit/big-four/ → BigFourComplianceView
│  └─ /analytics/benchmark/ → IndustryBenchmarkView
└─ Django Models
   ├─ Invoice
   ├─ InvoiceBatch
   ├─ InvoiceValidationResult
   ├─ AuditSession
   ├─ AuditFinding
   ├─ VendorProfile
   └─ Organization
```

---

## 18. FRONTEND ASSET TREE

```
Loaded in <head> of base.html:
├─ TailwindCSS (base styles)
├─ Custom inline <style> block
├─ Alpine.js (state management)
├─ Chart.js (visualization)
├─ Lucide Icons (icons)
└─ jQuery (if used in other pages)

Loaded in <body> or end of <html>:
├─ Dashboard state: dashboard() factory
├─ Toast system: toastStore() factory
├─ Global utilities: apiFetch(), Intl features
└─ Event listeners: window.notify, keyboard shortcuts
```

---

## 19. ASSET FILE SIZES (Approximate)

| Asset | Size | Gzipped | Usage |
|-------|------|---------|-------|
| Tailwind CSS | 500KB | 80KB | Utility classes |
| Alpine.js | 15KB | 6KB | State management |
| Chart.js | 90KB | 20KB | Charts |
| Lucide Icons | 150KB | 50KB | Icon library |
| Dashboard Template | 50KB | 12KB | HTML markup |
| Custom CSS (inline) | 5KB | 2KB | Dashboard styles |
| **Total Payload** | **~810KB** | **~170KB** | First load |

---

## 20. PERFORMANCE CHECKLIST

- [x] API endpoints use pagination (page_size)
- [x] Parallel API loading (Promise.all)
- [x] Chart instance reuse (destroy before recreate)
- [x] Lazy component loading (x-show vs x-if)
- [x] Minified assets (lucide.min.js)
- [x] CSS bundling (Tailwind JIT or PurgeCSS)
- [x] Responsive images (icons are inline)
- [x] No blocking scripts (async defer)
- [x] HTTPS enforcement
- [x] CORS configured
- [x] Rate limiting on APIs

---

## File Organization Summary

```
Tadgeeg Dashboard consists of:
├─ 1 Main Template (dashboard/index.html - 1,100 lines)
├─ 1 Base Layout (base.html - extended)
├─ 1 View Function (frontend_views.dashboard)
├─ 1 URL Pattern (frontend_urls.py)
├─ 5+ API Endpoint Views (audit, invoices, analytics)
├─ 3+ Services (AuditSessionSummaryService, etc.)
├─ 10+ Models (Invoice, AuditSession, etc.)
├─ 4 Frontend Libraries (Alpine.js, Chart.js, Lucide, Tailwind)
├─ 2 Main Configuration Files (settings.py, urls.py)
├─ 2 Documentation Files (Architecture + Quick Reference)
└─ Localization (i18n for AR/EN)
```

Total: **30-40 files** directly related to dashboard
Estimated: **5,000+ lines of code** (templates + views + scripts)
