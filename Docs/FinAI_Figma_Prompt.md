# FinAI — Figma Design Prompt
## نظام التدقيق المالي الذكي · AI-Powered Financial Auditing Platform

---

## 🎯 Project Brief

Design a **complete Figma design system + 12 production screens** for FinAI — an Arabic-first (RTL), AI-powered financial auditing SaaS platform targeting Saudi Arabia and GCC enterprises. The product audits invoices against 30 validation rules, detects fraud, and ensures ZATCA VAT compliance.

**Target users:** Financial managers, auditors, accountants in Saudi/GCC companies  
**Direction:** Enterprise SaaS · shadcn/ui exact token system · RTL Arabic-first · bilingual (AR/EN)

---

## 🎨 Design Tokens — Exact Values

Implement these as Figma Variables (in a `Tokens` collection):

### Color Primitives

```
Slate-950   #020617    ← login page background
Slate-900   #0f172a    ← sidebar background
Slate-800   #1e293b
Slate-700   #334155
Slate-600   #475569
Slate-500   #64748b    ← muted foreground / subtext
Slate-400   #94a3b8    ← placeholder, secondary icon
Slate-300   #cbd5e1    ← field label (on dark)
Slate-200   #e2e8f0    ← border / divider
Slate-100   #f1f5f9    ← muted background / tabs container
Slate-50    #f8fafc    ← page background

Blue-700    #1d4ed8
Blue-600    #2563eb    ← PRIMARY — buttons, active states, focus rings
Blue-500    #3b82f6    ← hover primary / sidebar active icon
Blue-400    #60a5fa    ← sidebar active text / links
Blue-200    #bfdbfe    ← blue badge border
Blue-100    #dbeafe
Blue-50     #eff6ff    ← blue badge background

Cyan-500    #06b6d4    ← logo gradient endpoint
Cyan-400    #22d3ee

Red-700     #b91c1c
Red-600     #dc2626    ← destructive / flagged
Red-500     #ef4444    ← live pulse dot
Red-200     #fecaca    ← critical badge border
Red-50      #fef2f2    ← critical badge background

Amber-700   #b45309
Amber-600   #d97706    ← duplicate / medium
Amber-200   #fde68a
Amber-50    #fffbeb

Green-700   #15803d
Green-600   #16a34a    ← approve button / success
Green-200   #bbf7d0
Green-50    #f0fdf4    ← approved badge background

Violet-700  #5b21b6
Violet-600  #7c3aed    ← audit score / AI features
Violet-200  #ddd6fe
Violet-50   #f5f3ff

White       #ffffff
```

### Semantic Color Variables (Light Mode)

```
background           #f8fafc   (Slate-50)
foreground           #0f172a   (Slate-900)
foreground-sub       #334155   (Slate-700)

card                 #ffffff
card-foreground      #0f172a
card-border          #e2e8f0   (Slate-200)

muted                #f1f5f9   (Slate-100)
muted-foreground     #64748b   (Slate-500)

primary              #2563eb   (Blue-600)
primary-foreground   #ffffff
primary-hover        #1d4ed8   (Blue-700)

ring                 rgba(147,197,253,0.45)   ← focus ring (blue-300 at 45%)

border               #e2e8f0
input-background     #f8fafc
input-border         #e2e8f0

accent               #f1f5f9   (same as muted)
accent-foreground    #0f172a
```

### Semantic Color Variables (Sidebar)

```
sidebar-bg              #0f172a   (Slate-900)
sidebar-border          rgba(255,255,255,0.06)
sidebar-foreground      #94a3b8   (Slate-400)
sidebar-foreground-dim  #475569   (Slate-600)
sidebar-label           #334155   (Slate-700)
sidebar-accent          rgba(255,255,255,0.07)
sidebar-accent-fg       rgba(255,255,255,0.90)
sidebar-active          rgba(37,99,235,0.18)   ← blue at 18% opacity
sidebar-active-fg       #60a5fa   (Blue-400)
sidebar-separator       rgba(255,255,255,0.06)
```

### Semantic Color Variables (Dark Login Page)

```
login-bg               #020617   (Slate-950)
login-card-bg          rgba(15,23,42,0.85)     ← glass effect
login-card-border      rgba(255,255,255,0.09)
login-blob-blue        rgba(37,99,235,0.14)
login-blob-violet      rgba(124,58,237,0.10)
login-input-bg         rgba(255,255,255,0.05)
login-input-border     rgba(255,255,255,0.10)
login-separator        rgba(255,255,255,0.08)
```

### Typography

```
Font Family — Arabic:  IBM Plex Sans Arabic
Font Family — Numbers: JetBrains Mono (for amounts, codes, IDs, percentages)

Scale:
  display-xl    32px / weight 800 / tracking -0.03em   ← FinAI wordmark on login
  display-lg    28px / weight 700 / tracking -0.025em
  heading-1     20px / weight 700                       ← card titles
  heading-2     16px / weight 700
  heading-3     14px / weight 600
  body-lg       14px / weight 400
  body          13px / weight 400                       ← default UI text
  body-sm       12px / weight 400
  caption       11px / weight 500
  label-upper   10.5px / weight 700 / uppercase / tracking +0.08em  ← field labels
  badge-text    11px / weight 500
  nav-item      13px / weight 400 (default) / 600 (active)
  mono-lg       20px monospace / weight 700             ← KPI numbers
  mono-md       13px monospace / weight 400             ← invoice IDs, codes
  mono-sm       11px monospace / weight 600             ← score percentages
```

---

## 📐 Spacing & Radius System

Exact from shadcn/ui source:

```
Radius:
  r-none    0px
  r-sm      4px
  r-md      6px      ← buttons, inputs, badges, nav items
  r-lg      8px      ← icon boxes
  r-xl      10px     ← tabs trigger (inner)
  r-2xl     12px     ← cards (rounded-xl)
  r-3xl     16px     ← login glass card (rounded-2xl)
  r-4xl     18px     ← logo icon box
  r-full    9999px   ← avatars, progress bars, badge pills, pulse dots

Spacing scale (multiples of 4px):
  2px, 4px, 6px, 8px, 10px, 12px, 14px, 16px, 20px, 24px, 28px, 32px, 40px, 48px

Component heights (exact):
  h-7     28px    ← small button (btn-sm)
  h-8     32px    ← sidebar menu button, topbar buttons
  h-9     36px    ← default button, default input
  h-10    40px    ← large button (btn-lg), login button
  h-12    48px    ← large sidebar item (with avatar)
  sidebar 52px    ← topbar height
  topbar  52px

Component widths:
  sidebar-expanded   224px  (14rem)
  sidebar-collapsed   48px  (3rem)
  login-form         400px  max-width
```

---

## 🔲 Component Library (Build These in Figma)

### 1. Button — 4 variants × 2 sizes

```
Variant  / Style
─────────────────────────────────────────────────────────────────
Primary  → bg: Blue-600  · text: white · hover: Blue-700
Ghost    → bg: Slate-100 · text: Slate-700 · hover: Slate-200
Outline  → bg: white · border: Slate-200 · text: Slate-700
Green    → bg: Green-600 · text: white    ← approve action
Red      → bg: Red-600   · text: white    ← reject action

Sizes:
  sm → h-7 · px-3 · r-md · font 11px 600
  md → h-8 · px-12px · r-md · font 12px 600   (topbar)
  lg → h-9/h-10 · px-16px · r-md · font 13px 600

Icon button: h-8 w-8 · r-md (square icon-only)

States: Default · Hover · Focus (ring 3px rgba(147,197,253,0.45)) · Disabled (opacity 50%)
```

### 2. Input Field

```
Height: 36px (h-9)
Radius: 6px (r-md)
Border: 1px Slate-200 (--border)
Background: Slate-50 (--input-background) for light
            rgba(255,255,255,0.05) for dark/login

Padding: 0 12px
Font: 13px / Slate-900

States:
  Default → border Slate-200
  Focus   → border Blue-600 + ring 3px rgba(147,197,253,0.45)
  Error   → border Red-500 + ring 3px rgba(239,68,68,0.25)
  Disabled → opacity 50%

Field anatomy (always include label above):
  Label: 10.5px / 700 / uppercase / tracking +0.08em / Slate-300 (dark) or Slate-500 (light)
  Gap between label and input: 6px
```

### 3. Badge — 7 semantic variants

```
Anatomy: inline-flex · r-md (6px) · border 1px · px-8px py-2px · 11px / 500

Critical  → bg Red-50    / text Red-700    / border Red-200
High      → bg Amber-50  / text Amber-700  / border Amber-200
Medium    → bg Amber-50  / text Amber-700  / border Amber-200 (lighter tint)
Low       → bg Green-50  / text Green-700  / border Green-200
Flagged   → bg Red-50    / text Red-800    / border Red-200
Approved  → bg Green-50  / text Green-800  / border Green-200
Pending   → bg Amber-50  / text Amber-900  / border Amber-200
Duplicate → bg Violet-50 / text Violet-700 / border Violet-200
Info/Blue → bg Blue-50   / text Blue-700   / border Blue-200
Secondary → bg Slate-100 / text Slate-500  / border Slate-200

Sidebar badge (notification count):
  bg: Red-500 · text: white · r-full · 10px 700 · px-6px py-1px
```

### 4. Card

```
bg: white (#ffffff)
border: 1px Slate-200
radius: 12px (rounded-xl)
shadow: none (flat design — border provides separation)

Accent variants (left border strip for KPI cards in RTL: border-right):
  Blue   → border-right: 3px solid Blue-500
  Red    → border-right: 3px solid Red-500
  Amber  → border-right: 3px solid Amber-500
  Green  → border-right: 3px solid Green-500
  Violet → border-right: 3px solid Violet-600

Card Header: padding 12px 16px · border-bottom 1px Slate-200
Card Body:   padding 16px
Card Footer: padding 10px 16px · border-top 1px Slate-200
```

### 5. Tabs — Pill Container

```
Container (tabs-list):
  bg: Slate-100
  radius: 10px (rounded-xl)
  padding: 3px (p-[3px])
  gap between triggers: 2px
  display: inline-flex

Trigger (tab):
  height: 28px (calc(100%-1px) inside container)
  padding: 0 10px
  radius: 8px (rounded-xl inner)
  font: 12px / 500
  border: 1px transparent (default) → 1px Slate-200 (active)

  Default  → bg transparent · text Slate-500
  Active   → bg white · text Slate-900 · border Slate-200 · shadow: 0 1px 3px rgba(0,0,0,0.07)
  Hover    → bg rgba(0,0,0,0.04) · text Slate-700

Allow count chips inside trigger:
  bg: Slate-200 · text Slate-500 · r-sm (4px) · 10px / 600 · px-5px
  (active with red: bg Red-200 · text Red-700)
```

### 6. Progress Bar

```
Track: h-6px (h-1.5) · r-full · bg rgba(37,99,235,0.12) (primary/20)
Fill:  r-full · transition: width 0.6s ease
       Blue-600  → score ≥ 85 (low risk)
       Green-600 → score ≥ 70 (medium risk — vendor spend bars)
       Amber-500 → score ≥ 50
       Red-500   → score <  50 (critical)

Compact version for table rows: track width 50px
```

### 7. Avatar

```
Shape: circle (r-full)
Size-sm: 28×28px · font 11px 700
Size-md: 32×32px · font 12px 700
Size-lg: 40×40px · font 14px 700

Background: gradient per letter initial (Arabic):
  أ,ب,ت: Blue-50  · text Blue-700
  ج,ح,خ: Amber-50 · text Amber-700
  د,ذ,ر: Green-50 · text Green-700
  ...etc — or assign randomly per vendor

Logo icon-box (square):
  36×36px · r-lg (10px)
  bg: linear-gradient(135deg, Blue-500, Cyan-500)
  box-shadow: 0 4px 14px rgba(59,130,246,0.40)
```

### 8. Sidebar Nav Button

```
Matches shadcn SidebarMenuButton exactly:
  display: flex · align-items: center · gap: 8px
  width: 100% · height: 32px (h-8)
  padding: 0 8px (p-2)
  radius: 6px (rounded-md)
  font: 13px / 400 (default), 600 (active)
  transition: background 120ms · color 120ms
  icon: 15×15px SVG (Lucide)

States:
  Default → bg transparent · text Slate-400
  Hover   → bg rgba(255,255,255,0.07) · text rgba(255,255,255,0.90)
  Active  → bg rgba(37,99,235,0.18) · text Blue-400 · font-weight 600

Notification badge (inside button, margin-right: auto):
  r-full · bg Red-500 · text white · 10px 700 · px-6 py-1

Section label (SidebarGroupLabel):
  10.5px / 700 / uppercase / tracking +0.08em
  color: Slate-700 / padding: 8px 8px 3px
```

### 9. Table Row

```
Header: border-bottom 1px Slate-200
  th: 11px / 600 / uppercase / tracking +0.06em / Slate-500
  padding: 9px 14px · text-align: right (RTL)

Row:
  td: 12.5px / Slate-700 · padding: 11px 14px
  border-bottom: 1px Slate-100
  hover: bg rgba(241,245,249,0.5)
  last-child: no border

Skeleton loading row:
  Replace content with bg-Slate-100 animated pulse shapes
  → rectangle r-md for text · circle for avatar · rounded-full for badge
```

### 10. KPI Stat Card

```
Anatomy (top-to-bottom, RTL layout):
  Row 1: [Icon Box 32px] ............. [Trend Pill]
  Row 2: [Value — JetBrains Mono 24px bold]
  Row 3: [Label — 11.5px Slate-500]
  Row 4 (optional): [Progress Bar 6px]

Icon Box:
  32×32px · r-lg (8px)
  bg: semantic (Blue-50, Red-50, Amber-50, Green-50, Violet-50)
  icon: 15px stroke-2 matching accent color

Trend Pill:
  r-full · 10px 700 · px-7px py-2px
  Up:   bg Green-50  · text Green-700  "↑ 18%"
  Down: bg Red-50    · text Red-700    "↓ 4%"
  Live: [pulse dot 6px Red-500] + "مراجعة" in Red-500

Value: JetBrains Mono · 24px / 700
  Blue-600 (invoices) · Red-600 (flagged) · Amber-600 (duplicates) · Green-700 (spend) · Violet-600 (score)

Amount format: "4.2م ر.س" (Arabic abbreviated millions)
```

### 11. Skeleton

```
Matches shadcn Skeleton: bg-accent animate-pulse rounded-md
  bg: Slate-100
  radius: 6px (rounded-md) except circles
  animation: opacity pulse 2s ease-in-out infinite (50% → 100%)

Common sizes:
  Text line: h-13px various widths (60px, 80px, 100px, 120px)
  Avatar:    28px circle
  Badge:     h-20px w-55px r-md
  Progress:  h-8px w-80px r-full
```

### 12. Separator

```
Matches shadcn Separator: bg-border h-px w-full
  Horizontal: 1px height · 100% width · Slate-200
  Sidebar:    rgba(255,255,255,0.06) · mx-8px
```

---

## 🖥️ Screens to Design (12 Total)

---

### Screen 1 — Login Page (Dark)

**URL:** `/login/`  
**Background:** Slate-950 (#020617) full bleed  
**Layout:** Centered single column, max-width 400px

**Elements:**
1. **Dot grid overlay** — radial-gradient dots rgba(255,255,255,0.055) / 28px repeat, covers full viewport
2. **Glow blobs** (position: absolute, pointer-events none):
   - Top-right: 500×500px · Blue-600 at 14% opacity · blur 80px
   - Bottom-left: 380×380px · Violet-600 at 10% opacity · blur 80px
   - Center: 200×200px · Cyan-500 at 7% opacity · blur 60px
3. **Logo block** (floating animation: translateY 0→-8px→0 / 5s ease-in-out infinite):
   - Icon box: 64×64px · r-4xl (18px) · gradient Blue-500 → Cyan-500 · box-shadow 0 16px 48px Blue-600/45%
   - SVG: bar chart icon (Lucide `BarChart3`) 32px white
   - Wordmark: "FinAI" · 28px / 800 / tracking -0.03em · white
   - Subtitle: "نظام التدقيق المالي الذكي" · 13px / 400 · Slate-500
   - Gap: 18px between icon and text
4. **Glass card** (login-card styles):
   - bg rgba(15,23,42,0.85) · backdrop-blur 24px
   - border 1px rgba(255,255,255,0.09)
   - radius 16px · padding 28px
   - box-shadow: 0 24px 64px rgba(0,0,0,0.5)
   - **Greeting:** "أهلاً بعودتك 👋" · 17px / 700 · white
   - **Subtitle:** "سجّل الدخول للوصول إلى لوحة التحكم" · 13px · Slate-500
   - **Email field** (dark variant input):
     - Label: "البريد الإلكتروني" · label-upper style · Slate-300
     - Input: h-36px · r-md · bg rgba(255,255,255,0.05) · border rgba(255,255,255,0.10) · text white
     - Placeholder: "admin@company.sa" · Slate-500
     - Focus: border Blue-500 · ring 3px rgba(147,197,253,0.40)
   - **Password field** (same style):
     - Label row: label right + "نسيت كلمة المرور؟" link (Blue-400) left
   - **Submit button** (h-40px btn-primary full-width):
     - gradient: linear-gradient(135deg, Blue-600, Blue-500)
     - box-shadow: 0 4px 16px Blue-600/35%
     - text: "تسجيل الدخول" + left-pointing arrow icon
   - **Footer** (border-top rgba(255,255,255,0.08) · margin-top 22px):
     - Right: green pulse dot (6px r-full bg Green-500 + glow) + "JWT + AES-256" Slate-500 11px
     - Left: badge-success "ZATCA متوافق ✓"

**API connected to:** `POST /api/v1/auth/token/`

---

### Screen 2 — Dashboard (Light + Sidebar)

**URL:** `/dashboard/`

**Sidebar (224px dark):**
- Brand header (52px) with logo icon + "FinAI" + "التدقيق المالي" in Cyan-400
- Nav sections: الرئيسية / الفواتير / التحليل
- Active: لوحة التحكم (sidebar-active state)
- Badge on "الفواتير": Red-500 pill "12"
- User footer: avatar gradient + "محمد العمري" / "مدير مالي" + chevron

**Topbar (52px):**
- Right: breadcrumb "لوحة التحكم / مارس 2026"
- Left: Search input (w-180px) + Bell icon (notification dot Red-500) + "فاتورة جديدة" primary button

**Content (Slate-50 bg, padding 16px, gap 14px):**

Row 1 — 5 KPI Cards (grid 5-col, gap 10px):
- إجمالي الفواتير · 1,847 · Blue · ↑18%
- مُبلَّغ عنها · 142 · Red · live pulse dot
- فواتير مكررة · 38 · Amber · ↑4
- إجمالي الإنفاق · 4.2م ر.س · Green
- متوسط التدقيق · 76% · Violet · progress bar below

Row 2 — Flagged Invoices Table Card (flex: 1):
- Card header: title + badge-flagged + tabs pill (الكل/حرج/عالي/متوسط) + "عرض الكل ←"
- Table: 8 columns (رقم الفاتورة / المورد / التاريخ / المبلغ / مستوى الخطر / نقاط التدقيق / الحالة / إجراء)
- 4 data rows + 1 skeleton row
- Pagination: "عرض 1–5 من 142 نتيجة" + prev/1/2/3/next buttons

**APIs connected:**
- `GET /api/v1/invoices/reports/spend/` → KPI totals
- `GET /api/v1/invoices/?status=flagged&page_size=8` → table rows
- `GET /api/v1/invoices/stats/` → KPI aggregates

---

### Screen 3 — Invoice Upload

**URL:** `/invoices/upload/`

**Layout:** Sidebar + topbar same pattern, content single-column centered max-width 720px

**Content:**
1. **Page title:** "رفع الفواتير" · heading-1 + subtext "يمكنك رفع ملفات PDF أو صور أو ملفات ZIP"
2. **Batch name field** (full-width): label "اسم الدفعة" + input placeholder "دفعة مارس 2026"
3. **Drag-drop zone** (h-200px):
   - border: 2px dashed Slate-200 → Blue-500 on hover/drag
   - radius: 12px (r-2xl)
   - bg: Slate-50 → Blue-50 on hover
   - center: upload icon (Lucide `UploadCloud` 40px Slate-400) + "اسحب الملفات هنا" 14px Slate-600 + "أو" + "تصفح الملفات" Blue-600 underline
   - small text: "PDF · PNG · JPG · ZIP — حتى 50 MB لكل ملف" Slate-400 11px
4. **File queue** (list, after files added):
   - Each item: [file type icon 32px] [file name 13px bold] [file size 11px Slate-400] [remove × button] — right aligned
   - PDF icon: Red-50 bg + Red-600 icon
   - Image icon: Blue-50 bg + Blue-600 icon
   - ZIP icon: Amber-50 bg + Amber-600 icon
5. **Upload button** (full-width h-40px primary): "رفع وتحليل الفواتير" + processing animation
6. **Results card** (appears after upload):
   - Summary strip: total / success / flagged / duplicate counts
   - Per-file result rows with badge per rule group failure

**API connected to:** `POST /api/v1/invoices/upload/`

---

### Screen 4 — Invoice List

**URL:** `/invoices/`

**Content:**
1. **Stats strip** (5 chips, horizontal scroll): إجمالي · مُعتمدة · مُبلَّغة · مكررة · قيد المراجعة
2. **Filter bar**: Search input + Status select + Risk level select + Date range picker + "إعادة تعيين"
3. **Table** (same design language as Dashboard table + columns):
   - All 8 columns from dashboard
   - Add: duplicate indicator (violet dot before invoice number)
   - Row hover: subtle Slate-50 tint
   - Inline approve button: Ghost sm
4. **Pagination** footer

**API connected to:** `GET /api/v1/invoices/` with params `search · status · risk_level · is_duplicate · date_from · date_to · page`

---

### Screen 5 — Invoice Detail

**URL:** `/invoices/<uuid>/`

**Layout:** Sidebar + topbar + 2-column content (main 65% + sidebar 35%)

**Left column (main):**
1. **Invoice header card**: vendor name · invoice # · date · amounts (subtotal/VAT/total) in a grid
2. **AI Summary card**: "ملخص الذكاء الاصطناعي" · blue-left-border · AI text paragraph + recommendations list
3. **30-Rules Breakdown card**:
   - Tabs: الكل / INV / DUP / VAT / ANO / CTL / DOC
   - Each rule row: [color dot pass/fail] [rule code mono] [rule name] [message] [severity badge] [passed badge]
   - Group pass rates (6 circular mini-progress rings across top)

**Right column (sidebar):**
1. **Score Ring card**: animated SVG circle 120px · score % in center (JetBrains Mono 28px) · risk level badge below
2. **Status card**: current status badge + approve/reject buttons
3. **Approve/Reject Modal** (overlay):
   - Reason textarea + confirm button
4. **Audit Trail card**: timeline list with events (uploaded/validated/flagged/approved)

**APIs connected:**
- `GET /api/v1/invoices/{id}/`
- `POST /api/v1/invoices/{id}/approve/` → body `{action: "approve"|"reject", reason: string}`
- `POST /api/v1/invoices/{id}/revalidate/`

---

### Screen 6 — Invoice Batches

**URL:** `/invoices/batches/`

**Content:** Table of upload batches
- Columns: اسم الدفعة / تاريخ الرفع / عدد الملفات / مُعتمد / مُبلَّغ / الحالة
- Status badges: processing (yellow pulse) / completed (green) / failed (red)
- Row click → batch detail drawer (right panel slides in)

**API connected to:** `GET /api/v1/invoices/batches/`

---

### Screen 7 — Reports

**URL:** `/reports/`

**Content:**
1. **Generate section** (4 quick-generate cards in 2×2 grid):
   - تقرير تدقيق الفواتير · ملخص تنفيذي · تقييم المخاطر · تحليل الموردين
   - Each card: icon + title + description + "توليد" button
   - Language toggle: AR / EN
2. **Saved reports list** (below): type filter tabs + table with report name / date / language / preview button
3. **Report Viewer Modal**: full-screen overlay with 8-section narrative + stats grid

**APIs connected:**
- `POST /api/v1/reports/generate/` → `{report_type, language}`
- `GET /api/v1/reports/`
- `GET /api/v1/reports/{id}/`

---

### Screen 8 — Vendors

**URL:** `/vendors/`

**Content:**
1. **Stats row** (4 inline chips): إجمالي الموردين / عالي الخطر / موردون جدد / موردون بتكرار
2. **Filter bar**: Search + Risk tier select
3. **Table**:
   - Columns: المورد / رقم الضريبي / مستوى الخطر / فواتير مكررة / فواتير مُبلَّغة / إجمالي الإنفاق / آخر فاتورة
   - Risk tier: Low (badge-low) / Medium (badge-medium) / High (badge-high) / Blocked (badge-critical + lock icon)
   - Spend bar (inline progress, Green gradient, % of max vendor spend)

**API connected to:** `GET /api/v1/invoices/reports/vendors/`

---

### Screen 9 — Anomaly Detection / Analytics

**URL:** `/analytics/`

**Content:**
1. **Benford's Law chart card**:
   - Bar chart (9 bars, digits 1–9) with expected curve overlay
   - Suspicious digits highlighted in Red-200
   - Legend: actual (Blue-500) / expected (Slate-300 dashed)
2. **AI Scan card**: "فحص الشذوذ بالذكاء الاصطناعي" + "بدء الفحص" button (primary)
   - Results: list of anomalies with severity badge + description
3. **High-risk invoices table**: Risk score progress bars + vendor + amount

**APIs connected:**
- `POST /api/v1/analytics/benford-analysis/`
- `POST /api/v1/analytics/detect-anomalies/`

---

### Screen 10 — Audit Cases

**URL:** `/audit/`

**Content:** Table of audit cases
- Columns: رقم القضية (CASE-YYYY-NNNN mono) / النوع / الحالة / المُعيَّن / الأولوية / تاريخ الإنشاء
- Case types: fraud / compliance / anomaly / duplicate / tax / internal
- Status pipeline: open → investigating → pending → resolved → closed
- "فتح قضية جديدة" button in topbar

**API connected to:** `GET /api/v1/audit/cases/`

---

### Screen 11 — Compliance (ZATCA)

**URL:** `/compliance/`

**Content:**
1. **Compliance overview** (3 big stat cards): Rules Active / Violations Open / Resolved This Month
2. **Rule categories** (tabs): ZATCA / VAT / IFRS / GAAP / SAMA / INTERNAL
3. **Violations table**: rule name / invoice / severity / status / resolve button

**APIs connected:**
- `GET /api/v1/compliance/rules/`
- `GET /api/v1/compliance/violations/`
- `POST /api/v1/compliance/violations/{id}/resolve/`

---

### Screen 12 — Documents

**URL:** `/documents/`

**Content:** File registry table
- Columns: اسم الملف / النوع / ثقة OCR (progress bar) / الحالة / تاريخ الرفع
- OCR confidence color: ≥80% Green · 60–80% Amber · <60% Red
- File type icons matching Upload screen

**API connected to:** `GET /api/v1/documents/`

---

## 🌐 Figma File Structure

```
📁 FinAI Design System
│
├── 📄 Cover
│
├── 📁 Foundations
│   ├── 🎨 Color Tokens (Variables)
│   ├── 📝 Typography Scale
│   ├── 📐 Spacing & Radius
│   └── 🌑 Shadows & Effects
│
├── 📁 Components
│   ├── Button (4 variants × 2 sizes × 4 states)
│   ├── Input Field (2 themes × 4 states)
│   ├── Badge (11 variants)
│   ├── Card (base + 5 accent variants)
│   ├── Tabs (container + trigger states)
│   ├── Progress Bar (4 color variants)
│   ├── Avatar (3 sizes + color variants)
│   ├── Sidebar Nav Item (3 states)
│   ├── KPI Stat Card (5 variants)
│   ├── Table (header + rows + skeleton + hover)
│   ├── Skeleton (text / avatar / badge / progress)
│   ├── Separator (horizontal + sidebar variant)
│   ├── Toast notification (success/error/info/warning)
│   └── Modal / Dialog (approve + report viewer)
│
├── 📁 Patterns
│   ├── Sidebar (expanded 224px + collapsed 48px)
│   ├── Topbar (52px)
│   ├── Page Layout (sidebar + topbar + content)
│   ├── Filter Bar
│   ├── Pagination
│   └── Empty States
│
└── 📁 Screens (1280×800px, RTL)
    ├── 01 Login
    ├── 02 Dashboard
    ├── 03 Invoice Upload
    ├── 04 Invoice List
    ├── 05 Invoice Detail
    ├── 06 Invoice Batches
    ├── 07 Reports
    ├── 08 Vendors
    ├── 09 Analytics
    ├── 10 Audit Cases
    ├── 11 Compliance
    └── 12 Documents
```

---

## ⚙️ Figma Setup Instructions

1. **Canvas:** Set frame size to 1280×800px for all screens
2. **Direction:** Enable RTL in text layers (Figma: Right-to-Left setting in Text properties)
3. **Variables:** Create all Color Tokens as Figma Variables with Light/Dark modes
4. **Auto Layout:** Use Auto Layout on all components for responsive behavior
5. **Components:** Create as Figma Components with variants for all states
6. **Prototype:** Link all screens in a flow starting from Login → Dashboard

### Fonts to install:
- IBM Plex Sans Arabic (Google Fonts)
- JetBrains Mono (Google Fonts)

---

## 📌 Key Design Rules

1. **RTL is primary** — all layouts flow right-to-left. English text (codes, IDs) stays LTR within RTL context
2. **JetBrains Mono for all numbers** — amounts, invoice IDs, scores, dates, VAT numbers
3. **Flat design** — no elevation/box-shadows on cards; borders provide separation
4. **Sidebar always dark** — even in light mode, sidebar stays `#0f172a`
5. **Risk color semantic** — Critical=Red · High=Amber · Medium=Amber-light · Low=Green — NEVER mixed
6. **No decorative gradients on content** — gradients only on: logo icon, primary button, login blobs
7. **Progress fill color = risk level** — Red<50% · Amber 50–70% · Green 70–85% · Blue>85%
8. **Skeleton on load** — every table shows 3 skeleton rows before data arrives
9. **Status always rightmost column** in tables (closest to the user's reading start in RTL)
10. **ZATCA badge** appears on every screen that shows VAT-related data (green badge-success)
