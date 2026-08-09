# Tadgeeg Dashboard Frontend Architecture - Comprehensive Guide

## Executive Summary
The Tadgeeg Executive Dashboard is a **single-page HTML template with Alpine.js state management**, built with **Tailwind CSS** and **Chart.js**. It serves as the main entry point for financial and audit leadership, aggregating real-time data from 5+ backend API endpoints.

---

## 1. Dashboard Template Structure

### Main Template File
- **Location**: [templates/dashboard/index.html](templates/dashboard/index.html)
- **Type**: Django template extending `base.html`
- **Size**: ~1100 lines
- **Blocks Used**:
  - `{% block title %}` — "Dashboard"
  - `{% block page_title %}` — "Dashboard"
  - `{% block nav_dashboard %}` — Navigation highlight
  - `{% block content %}` — Main dashboard content
  - `{% block page_js %}` — Alpine.js state management

### Template Architecture
```
base.html (main layout with sidebar, nav, toast system)
  └── dashboard/index.html (extends base)
      ├── Inline styles (dashboard-specific CSS classes)
      ├── Hero section with status badges
      ├── 4 KPI cards (gradient backgrounds)
      ├── Quick action buttons
      ├── Alert panel
      ├── Mini stats
      ├── Cash flow chart (Chart.js)
      ├── Risk distribution visualization
      ├── Top vendors panel
      ├── Rule compliance breakdown
      ├── Audit findings summary
      ├── Recent audit sessions
      ├── Big Four compliance matrix (conditional)
      ├── Industry benchmark comparison (conditional)
      └── Alpine.js state factory: `dashboard()`
```

---

## 2. Template Sections & Components

### 2.1 Hero Header Section
- **Location**: Lines 45-120
- **Content**:
  - Executive branding: "Financial leadership and compliance in one screen"
  - Status badge (dynamic: "High-risk items", "Review active", or "Stable")
  - Today's date badge
  - Compliance status badge (ZATCA alignment or needs follow-up)
  - CTA buttons: "Review queue" & "Upload new invoices"
  
- **Data Bindings**:
  - `organizationName` — Current org name
  - `todayLabel` — Date in i18n format
  - `dashboardStatusMeta()` — Returns badge styling based on risk level

### 2.2 KPI Cards (4-column grid)
- **Location**: Lines 96-158
- **Cards**:
  1. **Total Invoices**: `stats.total_invoices`
  2. **Total Amount Spent**: `stats.total_amount` (formatted SAR)
  3. **Compliance Rate**: `stats.compliance_rate` (%)
  4. **High-Risk Items**: `stats.high_risk`

- **Styling**:
  - Gradient backgrounds (blue, violet, orange, green)
  - Growth indicator pill showing monthly trend
  - Min-height: 196px

### 2.3 Quick Actions Panel
- **Location**: Lines 160-180
- **Actions**:
  - "Upload new invoices" → Links to `/invoices/upload/`
  - "Review flagged invoices" → Links to `/invoices/?status=flagged`
  - "Compliance details" → Links to `/compliance/`

### 2.4 Critical Alerts Panel
- **Location**: Lines 182-204
- **Content**:
  - Duplicate invoice counts
  - Top 3 flagged invoices summary
  - Fallback: "No critical alerts"
  
- **Alert Types**: `critical` | `warning` | `info` | `success`
- **Icons**: Animated Lucide icons

### 2.5 Cash Flow Chart
- **Location**: Lines 223-276
- **Chart Type**: Line chart via Chart.js
- **Data**: 6-month trend of spending (last 6 months)
- **Features**:
  - Responsive canvas `#cashFlowChart`
  - Gradient fill (blue)
  - Tooltip with SAR formatting
  - RTL-aware (Arabic support)

- **Instance Management**: `spendChartInst` stored in state

### 2.6 Risk Distribution Panel
- **Location**: Lines 327-358
- **Content**: 4-column risk breakdown
  - Critical (red)
  - High (orange)
  - Medium (amber)
  - Low (green)
  
- **Data**: `riskDist[]` array with color-coded stats

### 2.7 Top Vendors Panel
- **Location**: Lines 359-389
- **Content**: Top 5 vendors by spend
- **Data Fields**:
  - `vendor_name`
  - `total_amount`
  - `invoice_count`
  - `pct` (calculated percentage of total spend)
  - `color` (from palette)

### 2.8 Rule Compliance Breakdown
- **Location**: Lines 390-417
- **Content**: 6 rule groups with pass rates (%)
  - INV (Invoice Header): 88%
  - DUP (Duplicates): 94%
  - VAT (Taxation): 79%
  - ANO (Anomalies): 65%
  - CTL (Controls): 82%
  - DOC (Document): 91%

- **Data Source**: `ruleGroups[]` — comes from audit overview API or hardcoded defaults

### 2.9 Audit Sessions Summary
- **Location**: Lines 224-250
- **Content**:
  - Latest audit session summary (AI-generated)
  - Finding totals by severity (critical, high, medium, low)
  - Recent findings (max 6)
  
- **Data**:
  - `recentSessions[]` — last 5 audit sessions
  - `latestSessionSummary` — narrative summary
  - `findingTotals` — aggregated findings by level

### 2.10 Big Four Compliance Panel (Conditional)
- **Location**: Lines 418-461
- **Visible When**: `bigFourFirms.length > 0`
- **Content**:
  - KPMG, Deloitte, PwC, EY compliance status
  - Pass rate % per firm
  - Status badges (Compliant, At-risk, Non-compliant)
  - Progress bars
  - Passed/Failed/Total counts

- **Data Fields**: `bigFourFirms[]`
  - `firm` (firm name)
  - `description`
  - `standard` (e.g., "IFRS 16")
  - `pass_rate`
  - `status` ('compliant'|'at_risk'|'non_compliant')
  - `passed`, `failed`, `total`

### 2.11 Industry Benchmark Panel (Conditional)
- **Location**: Lines 463-510
- **Visible When**: `benchmarkMetrics.length > 0`
- **Content**:
  - Comparison against Saudi industry benchmarks
  - 4 metrics:
    - Compliance rate %
    - Duplicate rate %
    - Average risk score
    - VAT compliance %
  
- **Each Metric Shows**:
  - Organization value vs. Benchmark value
  - Status (Above/Below/At benchmark)
  - Progress bar
  - Color-coded (green/red/gray)

- **Metadata**:
  - `benchmarkIndustryLabel` — e.g., "Finance & Banking"
  - `benchmarkPosition` — 'above_average' | 'below_average' | 'average'

---

## 3. Alpine.js State Management

### 3.1 Main State Factory: `dashboard()`
- **Location**: Lines 511-827
- **Type**: Alpine.js component factory function
- **Lifecycle**: Initialized with `x-init="init()"`

### 3.2 State Object Properties

#### Internationalization (`i18n` object)
```javascript
{
  thisMonth: "this month",
  noUrgentItems: "No urgent items need review.",
  highRiskItems: "high-risk items",
  zatcaCompliant: "Aligned with ZATCA",
  needsFollowUp: "Needs follow-up and improvement",
  statusHighRisk: "High-risk items under review",
  statusReviewActive: "Review queue is active",
  statusStable: "Financial landscape is stable",
  // ... 30+ translation keys
}
```

#### Statistics Object
```javascript
stats: {
  total_invoices: 0,
  total_amount: 0,
  flagged: 0,
  duplicates: 0,
  compliance_rate: 100,
  high_risk: 0,
}
```

#### Data Arrays
```javascript
cashTrend: [],          // 6+ months of { month, total, count, flagged }
flaggedInvoices: [],    // Recent flagged invoices (max 5)
topVendors: [],         // Top 5 vendors
riskDist: [],          // Risk distribution by level
alerts: [],            // Display alerts (max 4)
ruleGroups: [],        // 6 audit rule groups
recentSessions: [],    // Last 5 audit sessions
latestSessionSummary: null,
findingTotals: { critical: 0, high: 0, medium: 0, low: 0 }
```

#### Computed Properties (getters)
```javascript
get todayLabel() {
  // Returns: "Monday, 25 March 2026" (i18n aware)
}

get growthPillText() {
  // Returns: "+12.0% ↗" or "-5.3% ↘"
}

get growthPillClass() {
  // Returns: "bg-emerald-50 text-emerald-600" or "bg-red-50 text-red-600"
}

get growthDescription() {
  // Returns: "+12.0% ↗ this month"
}

get reviewDescription() {
  // Returns: "No urgent items need review." or "5 high-risk items"
}

get complianceDescription() {
  // Returns: "Aligned with ZATCA" (if >= 90%) or "Needs follow-up"
}
```

### 3.3 Methods

#### `dashboardStatusMeta()`
Returns status badge metadata based on:
- High-risk items count → Amber badge
- Flagged items count → Blue badge
- Else → Green badge

#### `formatInteger(value)` 
Locale-aware number formatting (EN: "1,000" | AR: "١،٠٠٠")

#### `formatPercent(value)`
Formats as "95.5%"

#### `formatSar(value)`
Formats as "ر.س 1,234,567.89" (AR) or "SAR 1,234,567.89" (EN)

#### `formatAmount(value, currency)`
Generic currency formatting

#### `riskLabel(level)` & `riskBadge(level)`
Maps risk level to display text and CSS class

#### `sessionStatusLabel(status)` & `sessionStatusBadge(status)`
Maps session status to display text and CSS

#### `alertIcon(type)` & `alertClass(type)` & `alertIconWrapClass(type)`
Maps alert type to Lucide icon and styling

#### `initRuleGroups()`
Initializes `ruleGroups[]` with hardcoded defaults (6 audit rules)

#### Lifecycle Method: `init()`
Called on component mount:
1. `initRuleGroups()` — Initialize rule defaults
2. `Promise.all([loadSpendReport(), loadReviewQueues(), loadAuditOverview()])`
3. `lucide.createIcons()` — Re-render Lucide icons

#### `updateDerivedMetrics()`
Recalculates compliance_rate and rebuilds alerts after data update

#### `loadSpendReport()`
**Endpoint**: `/invoices/reports/spend/`
**Returns**:
```javascript
{
  overall: { total_invoices, grand_total },
  monthly_trend: [{ month, total, count, flagged }, ...],
  by_vendor: [{ vendor_name, total, count }, ...]
}
```

**Processing**:
- Calculates `stats.total_invoices` and `stats.total_amount`
- Builds `cashTrend` array (6+ months)
- Computes `monthlyGrowth` (last month vs previous)
- Creates `topVendors` (top 5 with percentages)
- Calls `updateDerivedMetrics()` and `buildCashFlowChart()`

#### `loadReviewQueues()`
**Endpoints** (parallel):
- `/invoices/?status=flagged&page_size=5`
- `/invoices/?is_duplicate=true&page_size=1`
- `/invoices/?risk_level=low|medium|high|critical&page_size=1`

**Processing**:
- Sets `stats.flagged` and `flaggedInvoices`
- Sets `stats.duplicates`
- Aggregates risk level counts → `riskDist`
- Calculates `stats.high_risk` (high + critical)
- Calls `updateDerivedMetrics()`

#### `loadAuditOverview()`
**Endpoint**: `/audit/dashboard/overview/`
**Returns**:
```javascript
{
  recent_sessions: [AuditSession, ...],
  latest_summary: string (HTML-safe),
  finding_totals: { critical, high, medium, low },
  recent_findings: [AuditFinding, ...],
  rule_groups: [{ code, label, pct, color, ... }, ...]
}
```

**Processing**:
- Sets `recentSessions`, `latestSessionSummary`
- Sets `findingTotals`
- Optionally updates `ruleGroups` if rule data present

#### `buildCashFlowChart()`
**Purpose**: Render Chart.js line chart on canvas `#cashFlowChart`
**Data**:
- X-axis: Last 6 months (month names in current language)
- Y-axis: Total spend values
- Series: Blue line with gradient fill

**Chart.js Config**:
```javascript
{
  type: 'line',
  data: {
    labels: ['Jan', 'Feb', 'Mar', ...],
    datasets: [{
      label: 'Total Flow',
      data: [1000000, 1200000, ...],
      borderColor: '#2563eb',
      backgroundColor: gradient (blue to transparent),
      fill: true,
      borderWidth: 3,
      tension: 0.42,
    }]
  },
  options: {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: 'index' },
    plugins: { legend: false, tooltip: {} },
    scales: { x: {...}, y: {...} }
  }
}
```

#### `buildAlerts()`
Constructs alert items:
1. If duplicates > 0 → warning alert
2. Top 3 flagged invoices → info/critical alerts
3. Else → success alert (no issues)

Limits to 4 alerts for display

#### `computeMonthlyGrowth(trend)`
Compares last 2 months in cash trend to calculate growth %

#### `formatMonth(value)`
Converts "2024-01" to localized month name

### 3.4 Extended State (Override Pattern)
**Location**: Lines 965-1034
```javascript
const originalDashboardFactory = dashboard;
dashboard = function() {
  const state = originalDashboardFactory();
  
  // Extensions:
  state.bigFourFirms = [];
  state.bigFourOverall = 0;
  state.loadBigFour = async function() { ... }
  
  state.benchmarkMetrics = [];
  state.benchmarkIndustryLabel = '';
  state.benchmarkPosition = '';
  state.loadBenchmark = async function() { ... }
  
  // Override init to load new panels
  const _origInit = state.init.bind(state);
  state.init = function() {
    _origInit();
    this.loadBigFour();
    this.loadBenchmark();
  };
  
  return state;
};
```

#### `loadBigFour()`
**Endpoint**: `/audit/big-four/`
**Returns**:
```javascript
{
  firms: [
    {
      firm: "KPMG",
      description: "...",
      standard: "IFRS 16",
      pass_rate: 85,
      status: "at_risk",
      passed: 50,
      failed: 9,
      total: 59
    },
    // ... Deloitte, PwC, EY
  ],
  overall_pass_rate: 82
}
```

#### `loadBenchmark()`
**Endpoint**: `/analytics/benchmark/?industry=finance`
**Returns**:
```javascript
{
  industry_label: "Finance & Banking",
  metrics: {
    compliance_rate_pct: { value, benchmark, delta, status },
    duplicate_rate_pct: { ... },
    avg_risk_score: { ... },
    vat_compliance_rate_pct: { ... }
  },
  summary: {
    overall_position: "above_average|below_average|average",
    metrics_above_benchmark: 2,
    metrics_below_benchmark: 0
  }
}
```

**Processing**:
- Maps metrics to display format with labels and units
- Sets `benchmarkPosition` ('above'|'below'|'at')
- Color-codes progress bars

---

## 4. Backend Views & Data Flow

### 4.1 Main Dashboard View

**File**: [apps/frontend/frontend_views.py](apps/frontend/frontend_views.py)

```python
@login_required(login_url='/login/')
def dashboard(request):
    ctx = _ctx(request, 'dashboard', monthly_growth=12)
    return render(request, 'dashboard/index.html', ctx)
```

**Context Variables** (from `_ctx()` helper):
- `pending_count` — Flagged invoices count
- `active` — Page identifier ('dashboard')
- `monthly_growth` — Hardcoded growth override (12%)
- `product_name` — Branding name
- `company_byline` — Org description

### 4.2 API Endpoints

All endpoints are **JSON REST APIs** that the Alpine.js component fetches

#### 1. Spend Analysis Report
**Endpoint**: `GET /invoices/reports/spend/`
**View**: [apps/invoices/views.py](apps/invoices/views.py) → `SpendAnalysisReportView`
**Returns**:
```json
{
  "overall": {
    "total_invoices": 234,
    "grand_total": 5000000
  },
  "monthly_trend": [
    { "month": "2026-01", "total": 800000, "count": 45, "flagged": 3 },
    { "month": "2026-02", "total": 920000, "count": 52, "flagged": 5 }
  ],
  "by_vendor": [
    { "vendor_name": "Supplier A", "total": 1200000, "count": 78 },
    ...
  ]
}
```

#### 2. Audit Dashboard Overview
**Endpoint**: `GET /audit/dashboard/overview/`
**View**: [apps/audit/views.py](apps/audit/views.py) → `AuditDashboardOverviewView`
**Returns**:
```json
{
  "recent_sessions": [
    {
      "id": "uuid",
      "name": "Batch 2026-03-25",
      "status": "completed",
      "processed_count": 50,
      "total_count": 50,
      "open_findings": 3,
      "critical_findings": 1,
      "created_at": "2026-03-25T10:30:00Z"
    }
  ],
  "latest_summary": "ملخص تنفيذي شامل للجلسة...",
  "finding_totals": {
    "critical": 1,
    "high": 5,
    "medium": 12,
    "low": 8
  },
  "rule_groups": [
    { "code": "INV", "label": "رأس الفاتورة", "pct": 88, "color": "#2563eb", ... },
    ...
  ]
}
```

**Key Features**:
- Fetches last 5 audit sessions
- Generates AI summary for latest session (Arabic)
- Aggregates findings by severity
- Builds rule compliance percentages

#### 3. Big Four Compliance
**Endpoint**: `GET /audit/big-four/`
**View**: [apps/audit/views.py](apps/audit/views.py) → `BigFourComplianceView`
**Returns**:
```json
{
  "firms": [
    {
      "firm": "KPMG",
      "description": "Kingdom Scope of Operations",
      "standard": "IFRS 16 / SOCPA Guidelines",
      "pass_rate": 85,
      "status": "at_risk",
      "passed": 50,
      "failed": 9,
      "total": 59
    }
  ],
  "overall_pass_rate": 82
}
```

#### 4. Industry Benchmark
**Endpoint**: `GET /analytics/benchmark/?industry=finance`
**View**: [apps/analytics/views.py](apps/analytics/views.py) → `IndustryBenchmarkView`
**Returns**:
```json
{
  "industry_label": "Finance & Banking (KSA)",
  "metrics": {
    "compliance_rate_pct": {
      "value": 94.2,
      "benchmark": 88.5,
      "delta": 5.7,
      "status": "above"
    },
    "duplicate_rate_pct": {
      "value": 2.1,
      "benchmark": 3.5,
      "delta": -1.4,
      "status": "above"
    },
    "avg_risk_score": {
      "value": 42.3,
      "benchmark": 50.0,
      "delta": -7.7,
      "status": "above"
    },
    "vat_compliance_rate_pct": {
      "value": 97.1,
      "benchmark": 95.0,
      "delta": 2.1,
      "status": "above"
    }
  },
  "summary": {
    "overall_position": "above_average",
    "metrics_above_benchmark": 4,
    "metrics_below_benchmark": 0
  }
}
```

#### 5. Invoices List (Flagged)
**Endpoint**: `GET /invoices/?status=flagged&page_size=5`
**View**: [apps/invoices/views.py](apps/invoices/views.py) → `InvoiceListView`
**Returns**:
```json
{
  "count": 12,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": "uuid",
      "invoice_number": "INV-001",
      "vendor_name": "Supplier XYZ",
      "total_amount": 50000,
      "currency": "SAR",
      "invoice_date": "2026-03-20",
      "status": "flagged",
      "risk_level": "high",
      "is_duplicate": false
    },
    ...
  ]
}
```

---

## 5. URL Routing

### Frontend URLs
**File**: [apps/frontend/frontend_urls.py](apps/frontend/frontend_urls.py)

```python
urlpatterns = [
    path('',          views.dashboard,     name='home'),
    path('dashboard/', views.dashboard,    name='dashboard'),
    # ... other pages
]
```

### API URLs
**File**: [finai_backend/urls.py](finai_backend/urls.py)

```python
path("api/v1/compliance/dashboard/", ComplianceDashboardView.as_view(), name="compliance-dashboard-compat"),
path("audit/dashboard/overview/", AuditDashboardOverviewView.as_view(), name="dashboard-overview-compat"),
```

**App-Specific URLs**:
- [apps/invoices/urls.py](apps/invoices/urls.py) → `/invoices/reports/spend/`
- [apps/audit/urls.py](apps/audit/urls.py) → `/audit/dashboard/overview/`, `/audit/big-four/`
- [apps/analytics/urls.py](apps/analytics/urls.py) → `/analytics/benchmark/`

---

## 6. HTML/CSS/JS Framework

### 6.1 HTML Markup
- **Method**: Django template tags (`{% ... %}`)
- **Direction**: RTL/LTR aware (controlled by `html[dir="ltr"]` and `html[dir="ar"]`)
- **Icons**: Lucide icons via `data-lucide="icon-name"`
- **Localization**: `{% trans "..." %}` and `{% blocktrans %}` tags

### 6.2 Tailwind CSS
**Classes Used**:
```
Spacing: px-4, py-6, gap-3, mb-8, mt-4
Display: flex, grid, grid-cols-1, md:grid-cols-2, lg:grid-cols-4
Typography: text-sm, font-bold, font-semibold, text-slate-600
Colors: bg-slate-50, text-blue-600, border-slate-200, bg-emerald-50
Borders: border, rounded-2rem, border-slate-200/80
Shadows: shadow-md, shadow-[0_24px_70px_-30px_...]
Gradients: bg-gradient-to-b, from-slate-50 via-white to-slate-100/80
Responsive: sm:, md:, lg:, xl:, 2xl:
Dark mode: dark:bg-slate-800, dark:text-slate-100
```

### 6.3 Alpine.js
**Version**: Modern Alpine (v3+)
**Directives**:
- `x-data="dashboard()"` — Initialize state
- `x-init="init()"` — Lifecycle hook
- `x-show="condition"` — Conditional rendering (CSS display)
- `x-for="item in array"` — Loop rendering
- `x-text="property"` — Text binding
- `@click="method()"` — Event binding
- `:class="condition ? 'class1' : 'class2'"` — Dynamic classes
- `:style="'prop:' + value"`  — Dynamic styles

### 6.4 Chart.js
**Chart Types**: Line chart (cash flow trend)
**Features**:
- Responsive container
- Gradient fill backgrounds
- Tooltip callbacks with SAR formatting
- RTL-aware axis labels
- Custom color schemes (blue primary)

### 6.5 Inline Styles
**Location**: Dashboard template `<style>` block (lines 13-43)

Custom CSS classes for dashboard:
```css
.dashboard-page .dashboard-surface { ... }         /* Card container */
.dashboard-page .dashboard-gradient-card { ... }   /* KPI cards */
.dashboard-page .dashboard-gradient-blue { ... }   /* Blue gradient */
.dashboard-page .dashboard-soft-button { ... }     /* Action buttons */
.dashboard-page .dashboard-alert-item { ... }      /* Alert styling */
.dashboard-page .dashboard-mini-stat { ... }       /* Small stats boxes */
```

---

## 7. Complete File Tree - Dashboard Related

### Templates
```
templates/
├── dashboard/
│   └── index.html                    ← Main dashboard template (1100 lines)
├── base.html                         ← Base layout (extends all pages)
├── partials/
│   └── language_switcher.html        ← Language toggle component
└── ...other app templates
```

### Static Files
```
static/
├── vendor/
│   └── lucide.min.js                ← Icon library (bundled)
└── ...other vendor libs
```

### Backend (Views & URLs)
```
apps/
├── frontend/
│   ├── frontend_views.py            ← dashboard() view function
│   ├── frontend_urls.py             ← URL route: 'dashboard/'
│   └── page_views.py
│
├── invoices/
│   ├── views.py                     ← SpendAnalysisReportView
│   └── urls.py                      ← '/invoices/reports/spend/'
│
├── audit/
│   ├── views.py                     ← AuditDashboardOverviewView, BigFourComplianceView
│   ├── urls.py                      ← '/audit/dashboard/overview/', '/audit/big-four/'
│   └── services/
│       └── summaries.py             ← AuditSessionSummaryService
│
└── analytics/
    ├── views.py                     ← IndustryBenchmarkView
    └── urls.py                      ← '/analytics/benchmark/'

finai_backend/
└── urls.py                          ← Main URL configuration (includes all app URLs)
```

### Configuration
```
core/
├── context_processors.py            ← Injects product_name, company_byline
├── services/
│   ├── pipeline.py
│   ├── financial_ai_engine.py
│   └── ...other services
└── ...
```

---

## 8. Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│  User Accesses /dashboard/  (Django)                            │
└────────────┬────────────────────────────────────────────────────┘
             │
             ├─→ frontend_views.dashboard(request)
             │   ├─ Checks @login_required
             │   ├─ Creates context (ctx)
             │   └─ Renders 'dashboard/index.html'
             │
             └─→ Template Loaded: dashboard/index.html
                 │
                 ├─→ Extends base.html
                 ├─→ Renders hero section, KPI cards, action buttons
                 ├─→ Canvas for Chart.js
                 │
                 └─→ Alpine.js Initialization <div x-init="init()">
                     │
                     └─→ dashboard() factory function
                         │
                         ├─→ init() called
                         │   │
                         │   ├─→ Promise.all([
                         │   │       loadSpendReport(),      │ Parallel
                         │   │       loadReviewQueues(),     │ API
                         │   │       loadAuditOverview()     │ Calls
                         │   │   ])
                         │   │
                         │   ├──→ GET /invoices/reports/spend/
                         │   │    ↓ SpendAnalysisReportView
                         │   │    Returns: overall, monthly_trend, by_vendor
                         │   │    ↓
                         │   │    - stats.total_invoices ✓
                         │   │    - stats.total_amount ✓
                         │   │    - cashTrend[] ✓
                         │   │    - topVendors[] ✓
                         │   │    - monthlyGrowth ✓
                         │   │    - buildCashFlowChart()
                         │   │
                         │   ├──→ GET /invoices/?status=flagged
                         │   │    GET /invoices/?is_duplicate=true
                         │   │    GET /invoices/?risk_level=critical|high|medium|low
                         │   │    ↓ InvoiceListView (4 parallel queries)
                         │   │    - stats.flagged ✓
                         │   │    - flaggedInvoices[] ✓
                         │   │    - stats.duplicates ✓
                         │   │    - riskDist[] ✓
                         │   │
                         │   └──→ GET /audit/dashboard/overview/
                         │        ↓ AuditDashboardOverviewView
                         │        Returns: recent_sessions, latest_summary, finding_totals, rule_groups
                         │        - recentSessions[] ✓
                         │        - latestSessionSummary ✓
                         │        - findingTotals ✓
                         │        - ruleGroups[] (optional override) ✓
                         │
                         ├─→ loadBigFour() (Extended state)
                         │   │
                         │   └─→ GET /audit/big-four/
                         │        ↓ BigFourComplianceView
                         │        - bigFourFirms[] ✓
                         │        - bigFourOverall ✓
                         │
                         ├─→ loadBenchmark() (Extended state)
                         │   │
                         │   └─→ GET /analytics/benchmark/?industry=finance
                         │        ↓ IndustryBenchmarkView
                         │        - benchmarkMetrics[] ✓
                         │        - benchmarkIndustryLabel ✓
                         │        - benchmarkPosition ✓
                         │
                         └─→ lucide.createIcons()
                             Re-render all <i data-lucide="..."> icons
```

---

## 9. API Endpoint Summary

| Endpoint | Method | View | Purpose | Returns |
|----------|--------|------|---------|---------|
| `/invoices/reports/spend/` | GET | `SpendAnalysisReportView` | Dashboard spend & vendor data | overall, monthly_trend, by_vendor |
| `/invoices/?status=flagged` | GET | `InvoiceListView` | Flagged invoices | Paginated results with invoice details |
| `/invoices/?is_duplicate=true` | GET | `InvoiceListView` | Duplicate count | Count of duplicates |
| `/invoices/?risk_level=*` | GET | `InvoiceListView` | Risk level distribution | By level: low, medium, high, critical |
| `/audit/dashboard/overview/` | GET | `AuditDashboardOverviewView` | Audit summary | recent_sessions, latest_summary, finding_totals, rule_groups |
| `/audit/big-four/` | GET | `BigFourComplianceView` | Big Four compliance | firms[], overall_pass_rate |
| `/analytics/benchmark/` | GET | `IndustryBenchmarkView` | Industry comparison | metrics, summary, industry_label |

---

## 10. Key Styling Details

### Hero Section
- Gradient background: `from-slate-50 via-white to-slate-100/80`
- Rounded corners: `rounded-[2rem]`
- Subtle blur effects on decorative circles
- Direction-aware text (RTL for Arabic)

### KPI Cards
- 4-column grid (2x2 on mobile, 1x4 on desktop)
- Gradient backgrounds (blue, violet, orange, green)
- White text on colored backgrounds
- Box shadow: `0 24px 60px -24px rgba(15,23,42,0.45)`
- Progress bars for each metric

### Buttons
- CTA buttons: Gradient (primary gradient blue-to-purple)
- Secondary buttons: Light border with hover state
- Icons from Lucide library (18px)

### Charts & Visualizations
- Chart.js: Blue line chart with gradient fill
- Progress bars: Color-coded (green/amber/red)
- Percentage displays: Monospace font, right-aligned

---

## 11. Localization & Internationalization

### Supported Languages
- **English (EN)**: LTR direction
- **Arabic (AR)**: RTL direction

### Implementation
```javascript
// In state.i18n object (30+ keys)
{
  thisMonth: "{% trans 'this month' %}",
  noUrgentItems: "{% trans 'No urgent items need review.' %}",
  // ...
}

// Currency formatting
formatSar(value) {
  return `${document.documentElement.lang === 'ar' ? 'ر.س' : 'SAR'} ${...}`
}

// Date formatting
todayLabel {
  return new Intl.DateTimeFormat(window.APP_LOCALE || 'en-US', {...})
}

// Font families
// AR: 'IBM Plex Sans Arabic'
// EN: 'IBM Plex Sans'
```

---

## 12. Performance Considerations

### Optimizations
1. **Parallel API Loading**: All 4-5 endpoints load simultaneously via `Promise.all()`
2. **Lazy Rendering**: Conditional sections use `x-show` (CSS) vs `x-if` (DOM)
3. **Chart Reuse**: Chart instance destroyed and recreated only on data update
4. **No Full Page Refresh**: SPA-like behavior (Alpine.js handles updates)
5. **Efficient Pagination**: Endpoints return limited results (5-100 items)

### Load Times
- Initial template: ~50KB (gzipped)
- Lucide icons: ~15KB minified
- Chart.js: ~20KB minified
- Total JS payload: ~85KB

---

## 13. Common Customizations

### Changing KPI Card Order
Edit template lines 96-158 to reorder gradient-card divs

### Adding New Dashboard Section
1. Add new `<div class="dashboard-surface p-6">` block
2. Use `x-show="yourData.length"` for conditional rendering
3. Add state properties to `dashboard()` factory (lines 511+)
4. Create API endpoint and call in `init()` or as separate method
5. Format data with existing helpers (formatSar, formatPercent, etc.)

### Theming
- Edit gradient colors in `<style>` block (lines 22-25)
- Adjust Tailwind colors (bg-blue-50 → bg-indigo-50)
- Chart.js colors in `buildCashFlowChart()` method

---

## 14. Security & Access Control

### Authentication
- Requires `@login_required(login_url='/login/')`
- Django session-based or JWT token

### Data Filtering
- All API endpoints filter by `organization=request.user.organization`
- Multi-tenant isolation enforced at view level

### CSRF Protection
- Django CSRF middleware enabled
- Forms include `{% csrf_token %}`

---

## 15. Debugging & Troubleshooting

### Console Logs
Dashboard logs errors to console:
```javascript
loadSpendReport() {
  // ... try block
  catch (error) {
    console.warn('dashboard spend report', error);
    this.cashTrend = [];
  }
}
```

### Check Network Requests
Open DevTools → Network tab → Monitor these endpoints:
- `/invoices/reports/spend/`
- `/invoices/?status=flagged`
- `/audit/dashboard/overview/`
- `/audit/big-four/` (if Big Four data shown)
- `/analytics/benchmark/` (if benchmark data shown)

### Verify Alpine State
In DevTools console:
```javascript
// Access Alpine component  
const dashboardEl = document.querySelector('[x-data]');
console.log(dashboardEl.__x);
```

---

## 16. Migration & Versioning

### Current Version
- Alpine.js: v3+ (using modern syntax)
- Tailwind CSS: v3+
- Chart.js: v3+
- Lucide Icons: Latest bundle

### Breaking Changes to Watch
- Chart.js major versions may change rendering API
- Alpine.js v4 may introduce syntax changes
- Tailwind CSS v4 changed color naming

---

## Summary

**The Tadgeeg Dashboard is a modern, responsive Alpine.js-powered executive dashboard that:**

✅ Loads via Django template render with authentication  
✅ Initializes Alpine.js state component on page load  
✅ Fetches 5+ JSON API endpoints in parallel  
✅ Renders reactive UI with Tailwind CSS classes  
✅ Visualizes data with Chart.js and Lucide icons  
✅ Supports bilingual Arabic/English with RTL layout  
✅ Shows 10+ dashboard panels with conditional rendering  
✅ Integrates audit, invoice, and analytics data seamlessly  
✅ Provides real-time KPIs, risk distribution, and compliance metrics  
✅ Scales to handle organizations with 1000s of invoices  

**Key Files:**
- [templates/dashboard/index.html](templates/dashboard/index.html) — Main template (1100 lines)
- [apps/frontend/frontend_views.py](apps/frontend/frontend_views.py) — View function
- [apps/frontend/frontend_urls.py](apps/frontend/frontend_urls.py) — URL route
- Backend API views in audit, invoices, analytics apps
