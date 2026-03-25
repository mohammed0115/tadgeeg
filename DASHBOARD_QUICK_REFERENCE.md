# Dashboard Quick Reference Guide

## Quick Facts

| Aspect | Details |
|--------|---------|
| **Main Template** | `templates/dashboard/index.html` (1100 lines) |
| **View Function** | `apps/frontend/frontend_views.py::dashboard()` |
| **URL Route** | `GET /dashboard/` → name: `frontend:dashboard` |
| **Framework** | Django + Alpine.js v3+ + Tailwind CSS v3+ + Chart.js v3+ |
| **Language Support** | Arabic (RTL) & English (LTR) |
| **Authentication** | `@login_required(login_url='/login/')` |
| **API Endpoints** | 5+ JSON endpoints (parallel loading) |
| **Panels** | 10+ conditional sections |
| **Mobile Ready** | Fully responsive (sm, md, lg, xl, 2xl) |
| **Dark Mode** | Not implemented (light only) |

---

## Template Sections (Quick Map)

```
dashboard/index.html
│
├─ Lines 13-43:  Inline styles (.dashboard-* classes)
│
├─ Lines 44-44:  Alpine.js initialization <div x-data x-init>
│
├─ Lines 45-120:   HERO HEADER
│  ├─ Branding & title
│  ├─ Status badge (dynamic)
│  ├─ Date & compliance indicators
│  └─ CTA buttons (Upload, Review queue)
│
├─ Lines 90-158:   KPI CARDS (4-column grid)
│  ├─ Total invoices (blue gradient)
│  ├─ Total amount (violet gradient)
│  ├─ Compliance rate (orange gradient)
│  └─ High-risk items (green gradient)
│
├─ Lines 160-180:  QUICK ACTIONS
│  ├─ Upload link
│  ├─ Review queue link
│  └─ Compliance link
│
├─ Lines 182-204:  ALERTS PANEL
│  ├─ Critical/warning alerts
│  ├─ Recent flagged invoices
│  └─ Fallback "no issues" message
│
├─ Lines 205-222:  MINI STATS
│  ├─ Dashboard status label
│  └─ Recent activities
│
├─ Lines 223-276:  CHART.JS CASH FLOW
│  ├─ 6-month spending trend
│  ├─ Canvas element
│  └─ Chart instance management
│
├─ Lines 277-326:  RISK DISTRIBUTION
│  ├─ Critical count (red)
│  ├─ High count (orange)
│  ├─ Medium count (amber)
│  └─ Low count (green)
│
├─ Lines 327-358:  TOP VENDORS
│  ├─ Vendor names & spend
│  ├─ Percentage of total
│  └─ Color-coded items
│
├─ Lines 359-389:  RULE COMPLIANCE
│  ├─ 6 audit rule groups
│  ├─ Pass rate percentages
│  └─ Color-coded progress bars
│
├─ Lines 390-417:  AUDIT SESSION SUMMARY
│  ├─ Recent sessions list
│  ├─ Latest session narrative
│  └─ Finding totals by severity
│
├─ Lines 418-461:  BIG FOUR COMPLIANCE (conditional)
│  ├─ KPMG, Deloitte, PwC, EY
│  ├─ Pass rates & compliance status
│  └─ Overall score
│
├─ Lines 462-510:  INDUSTRY BENCHMARK (conditional)
│  ├─ Compliance rate comparison
│  ├─ Duplicate rate comparison
│  ├─ Risk score comparison
│  └─ VAT compliance comparison
│
└─ Lines 511-1034: ALPINE.JS STATE & METHODS
   ├─ dashboard() factory (511-827)
   ├─ Extended state (965-1034)
   │  ├─ loadBigFour()
   │  └─ loadBenchmark()
   └─ API integrations
```

---

## Data Fetch Timeline

```
Page Loads (GET /dashboard/)
    ↓
Django Template Rendered (dashboard/index.html)
    ↓
Alpine.js Initializes (x-init="init()")
    ↓
Wait for Promise.all([
    loadSpendReport(),         → GET /invoices/reports/spend/
    loadReviewQueues(),        → GET /invoices/?status=flagged + 3 more queries
    loadAuditOverview()        → GET /audit/dashboard/overview/
])
    ↓
Then: loadBigFour()           → GET /audit/big-four/
    ↓
Then: loadBenchmark()         → GET /analytics/benchmark/
    ↓
Finally: lucide.createIcons() → Render all icons
    ↓
UI Fully Rendered
```

---

## State Object Map

```javascript
dashboard() {
  // ═══════════════════════════════════════════════════════════
  // CORE STATE PROPERTIES
  // ═══════════════════════════════════════════════════════════
  
  i18n: {
    // 30+ translation keys for UI strings
    thisMonth, noUrgentItems, zatcaCompliant, etc.
  },
  
  // Main metrics
  stats: {
    total_invoices: 234,
    total_amount: 5000000,
    flagged: 12,
    duplicates: 3,
    compliance_rate: 95.4,
    high_risk: 5
  },
  
  // Data arrays
  cashTrend: [{ month, total, count, flagged }, ...],  // 6+ months
  flaggedInvoices: [...],    // Last 5
  topVendors: [...],         // Top 5
  riskDist: [...],           // 4 severity levels
  alerts: [...],             // Max 4 display items
  ruleGroups: [...],         // 6 rule groups
  recentSessions: [...],     // Last 5
  findingTotals: { critical, high, medium, low },
  
  // Chart instance
  spendChartInst: Chart,     // or null
  
  // ═══════════════════════════════════════════════════════════
  // COMPUTED GETTERS
  // ═══════════════════════════════════════════════════════════
  
  get todayLabel()           // "Monday, 25 March 2026"
  get growthPillText()       // "+12.0% ↗"
  get growthPillClass()      // CSS color class
  get growthDescription()    // "+12.0% ↗ this month"
  get reviewDescription()    // "5 high-risk items" or "No urgent items"
  get complianceDescription()// "Aligned with ZATCA" or "Needs follow-up"
  
  // ═══════════════════════════════════════════════════════════
  // CORE METHODS
  // ═══════════════════════════════════════════════════════════
  
  init()                     // Called on mount (Promise.all + icons)
  
  loadSpendReport()          // Fetch spend data
  loadReviewQueues()         // Fetch flagged, duplicates, risk levels
  loadAuditOverview()        // Fetch audit sessions, findings, rules
  
  updateDerivedMetrics()     // Recalc compliance_rate & rebuild alerts
  buildAlerts()              // Create display alerts
  buildCashFlowChart()       // Render Chart.js chart
  
  // Formatting helpers
  formatInteger(value)       // Locale-aware: "1,000" / "١،٠٠٠"
  formatPercent(value)       // → "95.5%"
  formatSar(value)           // → "SAR 1,234.56" / "ر.س ١،٢٣٤.٥٦"
  formatAmount(value, curr)  // → "USD 1,000"
  
  // Mapping helpers
  riskLabel(level)           // "High" / "عالي"
  riskBadge(level)           // CSS class
  sessionStatusLabel(stat)   // → "Completed" / "مكتمل"
  alertIcon(type)            // Lucide icon name
  alertClass(type)           // CSS class + color
  
  // ═══════════════════════════════════════════════════════════
  // EXTENDED STATE (Lines 965-1034)
  // ═══════════════════════════════════════════════════════════
  
  bigFourFirms: [...]        // KPMG, Deloitte, PwC, EY
  bigFourOverall: 82,        // Overall %
  
  benchmarkMetrics: [...],   // 4 metrics with above/below status
  benchmarkIndustryLabel: "Finance & Banking (KSA)",
  benchmarkPosition: "above_average|below_average|average",
  
  loadBigFour()              // Fetch /audit/big-four/
  loadBenchmark()            // Fetch /analytics/benchmark/
}
```

---

## API Response Formats

### 1. SpendAnalysisReportView (GET /invoices/reports/spend/)
```javascript
{
  "overall": {
    "total_invoices": 234,
    "grand_total": 5000000
  },
  "monthly_trend": [
    { "month": "2025-10", "total": 800000, "count": 45, "flagged": 2 },
    { "month": "2025-11", "total": 920000, "count": 52, "flagged": 4 },
    ...
  ],
  "by_vendor": [
    { "vendor_name": "Supplier A", "total": 1200000, "count": 78 },
    { "vendor_name": "Supplier B", "total": 950000, "count": 62 },
    ...
  ]
}
```

### 2. InvoiceListView (GET /invoices/?status=flagged&page_size=5)
```javascript
{
  "count": 12,
  "results": [
    {
      "id": "abc123",
      "invoice_number": "INV-001",
      "vendor_name": "XYZ Corp",
      "total_amount": "50000.00",
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

### 3. AuditDashboardOverviewView (GET /audit/dashboard/overview/)
```javascript
{
  "recent_sessions": [
    {
      "id": "session-uuid",
      "name": "Batch 2026-03-25",
      "status": "completed",
      "total_count": 100,
      "processed_count": 100,
      "open_findings": 5,
      "critical_findings": 1,
      "created_at": "2026-03-25T10:30:00Z"
    },
    ...
  ],
  "latest_summary": "تم معالجة 100 فاتورة بنجاح...",  // Arabic narrative
  "finding_totals": {
    "critical": 1,
    "high": 5,
    "medium": 12,
    "low": 8
  },
  "rule_groups": [
    {
      "code": "INV",
      "label": "رأس الفاتورة",
      "pct": 88,
      "color": "#2563eb",
      "passed": 88,
      "failed": 12,
      "total": 100
    },
    ...
  ]
}
```

### 4. BigFourComplianceView (GET /audit/big-four/)
```javascript
{
  "firms": [
    {
      "firm": "KPMG",
      "description": "Kingdom Scope of Operations",
      "standard": "IFRS 16",
      "pass_rate": 85,
      "status": "at_risk",
      "passed": 50,
      "failed": 9,
      "total": 59
    },
    // ... Deloitte, PwC, EY
  ],
  "overall_pass_rate": 82
}
```

### 5. IndustryBenchmarkView (GET /analytics/benchmark/?industry=finance)
```javascript
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

---

## Tailwind Classes Used

### Colors (Semantic)
```
Primary: 
  - bg-blue-50, bg-blue-100, text-blue-600, text-blue-700
  - border-blue-200, border-blue-300

Success:
  - bg-emerald-50, bg-emerald-100, text-emerald-600
  - border-emerald-200

Warning:
  - bg-amber-50, bg-amber-100, text-amber-600, text-amber-700
  - border-amber-200

Error/Critical:
  - bg-red-50, text-red-600, text-red-700, border-red-200

Secondary:
  - bg-slate-50, bg-slate-100, text-slate-600, text-slate-700
```

### Layout
```
Grid: grid, grid-cols-1, md:grid-cols-2, lg:grid-cols-4, 2xl:grid-cols-8
Flex: flex, flex-col, gap-3, gap-6, items-center, justify-between
Spacing: px-4, py-6, mb-8, mt-4, p-6, rounded-2rem
Max-width: max-w-7xl, max-w-3xl
```

### Responsive
```
sm: (640px)   → sm:flex-row, sm:px-6
md: (768px)   → md:grid-cols-2
lg: (1024px)  → lg:px-8, lg:flex-row
xl: (1280px)  → xl:p-8
2xl: (1536px) → 2xl:col-span-8
```

### Interactive
```
Hover: hover:bg-slate-50, hover:border-slate-300
Focus: focus:outline-none, focus:ring-2
Transition: transition, duration-300
```

---

## Key Alpine Directives

```html
<!-- State Initialization -->
<div x-data="dashboard()" x-init="init()">

<!-- Conditional Rendering -->
<div x-show="riskDist.length">            <!-- CSS display based -->
<template x-for="item in array">          <!-- DOM loop -->

<!-- Data Binding -->
<div x-text="property"></div>             <!-- Text interpolation -->
<div :class="condition ? 'class' : ''">   <!-- Dynamic class -->
<div :style="'color: ' + color">          <!-- Dynamic style -->

<!-- Event Handling -->
@click="handleClick()"                    <!-- Click event -->
@notify.window="push($event.detail)"      <!-- Custom window event -->

<!-- Computed Properties -->
:class="dashboardStatusMeta().badgeClass" <!-- Method return value -->
```

---

## Form of Alert Items

```javascript
{
  type: "critical|warning|info|success",
  title: "Invoice INV-001",
  subtitle: "XYZ Corp — SAR 50,000.00"
}
```

**Icon Mapping**:
- critical → triangle-alert (red)
- warning → alert-circle (amber)
- info → shield-alert (blue)
- success → badge-check (green)

---

## Development Checklist

- [ ] Verify endpoint responses in Browser DevTools (Network tab)
- [ ] Check Alpine state with `document.querySelector('[x-data]').__x`
- [ ] Confirm translations in `i18n` object match UI text
- [ ] Test RTL layout on Arabic locale
- [ ] Verify Chart.js renders on canvas `#cashFlowChart`
- [ ] Confirm gradient colors render correctly (browsers vary)
- [ ] Test responsive breakpoints (sm 640px, md 768px, lg 1024px)
- [ ] Check Lucide icons load (look for `[data-lucide]` elements)
- [ ] Verify CSRF token present in form submissions
- [ ] Test organization multi-tenancy (different users see different data)

---

## Common Issues & Solutions

| Issue | Cause | Solution |
|-------|-------|----------|
| Chart not showing | Canvas element not in DOM | Verify `<canvas id="cashFlowChart">` present |
| Icons blank | Lucide library not loaded | Check `lucide.createIcons()` called |
| Data not loading | API endpoint 404 | Check URL routes in urls.py |
| English text shows | Translation key missing | Add to `i18n` object or use Django `{% trans %}` |
| Layout breaks RTL | CSS not direction-aware | Add `html[dir="ar"]` selector rules |
| State not updating | API error silently fails | Check console logs & network tab |
| Chart crashes on reload | Old instance not destroyed | Verify `if (spendChartInst) spendChartInst.destroy()` |

---

## File References

| File | Purpose |
|------|---------|
| [templates/dashboard/index.html](templates/dashboard/index.html) | Main template (1100 lines) |
| [apps/frontend/frontend_views.py](apps/frontend/frontend_views.py) | View function |
| [apps/frontend/frontend_urls.py](apps/frontend/frontend_urls.py) | URL pattern |
| [apps/invoices/views.py](apps/invoices/views.py) | SpendAnalysisReportView, InvoiceListView |
| [apps/audit/views.py](apps/audit/views.py) | AuditDashboardOverviewView, BigFourComplianceView |
| [apps/analytics/views.py](apps/analytics/views.py) | IndustryBenchmarkView |
| [templates/base.html](templates/base.html) | Parent template (sidebar, nav, layout) |
| [static/vendor/lucide.min.js](static/vendor/lucide.min.js) | Icon library |
| core/context_processors.py | Injects product_name, company_byline |

---

## Useful Django Template Filters

```django
{% trans "..." %}                 <!-- Marked for translation -->
{% blocktrans with var=value %}   <!-- Block translation -->
{% url 'frontend:dashboard' %}    <!-- URL reverse lookup -->
{{ variable|default:"fallback" }} <!-- Default value -->
{{ value|escapejs }}              <!-- Escape for JS -->
```

---

## JavaScript Helpers

```javascript
// Fetch API wrapper (assumed available)
apiFetch(url)                    // GET /api/v1/... + JWT tokens

// Locale & locale-aware formatting
window.APP_LOCALE                // e.g., "en-US"
document.documentElement.lang    // e.g., "ar" or "en"
Intl.DateTimeFormat(locale, ...) // Native date formatting

// Alpine.js utilities
this.$nextTick(() => {...})      // After DOM update
this.$watch('property', callback) // Watch state changes
```

---

## Deployment Notes

1. **Static Files**: Ensure `python manage.py collectstatic` runs in production
2. **Lucide Icons**: Bundle is minified; no need to rebuild
3. **CSRF Tokens**: Required for any form submissions
4. **Database**: Dashboard queries are read-only (SELECT)
5. **Caching**: Safe to cache template (no user-specific data embedded)
6. **API Rate Limiting**: Consider adding rate limits to bulk endpoint calls

---

## Future Enhancement Ideas

- [ ] Real-time data updates via WebSocket
- [ ] Custom dashboard widget builder
- [ ] Export report as PDF
- [ ] Dark mode toggle
- [ ] Mobile app version
- [ ] Email digest of alerts
- [ ] Custom alert thresholds
- [ ] Multi-language support for Big Four/Benchmark labels
- [ ] Drill-down into charts (click chart → detail view)
- [ ] Data export (CSV/Excel)
