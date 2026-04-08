# FinAI Settings - CSS Class Quick Reference

## 🎨 Premium Components Library

### Card Components

#### Hero Header Card
```html
<section class="group relative overflow-hidden rounded-3xl 
  border border-slate-200/60 
  bg-gradient-to-br from-white via-slate-50/30 to-white 
  shadow-sm transition-all hover:shadow-md 
  dark:border-slate-800/60 dark:from-slate-950/80 
  dark:via-slate-900/40 dark:to-slate-950/80">
  <div class="absolute -top-32 -right-32 h-64 w-64 
    rounded-full bg-primary-500/10 blur-3xl 
    opacity-0 transition-opacity group-hover:opacity-100"></div>
  <div class="relative px-8 py-10 lg:px-10 lg:py-12">
    <!-- Content -->
  </div>
</section>
```

#### Standard Section Card
```html
<section class="group relative overflow-hidden rounded-3xl 
  border border-slate-200/60 
  bg-gradient-to-br from-white via-slate-50/30 to-white 
  p-8 shadow-sm transition-all hover:shadow-md 
  dark:border-slate-800/60 dark:from-slate-950/80 
  dark:via-slate-900/40 dark:to-slate-950/80">
  <div class="absolute -top-24 -left-24 h-48 w-48 
    rounded-full bg-primary-500/10 blur-3xl 
    opacity-0 transition-opacity 
    group-hover:opacity-100"></div>
  <div class="relative">
    <!-- Content -->
  </div>
</section>
```

#### Stat/Metric Card
```html
<div class="group overflow-hidden rounded-2xl 
  border border-slate-200/60 
  bg-gradient-to-br from-white to-slate-50/80 
  p-6 shadow-sm transition-all hover:shadow-md 
  dark:border-slate-800/60 dark:from-slate-950/80 
  dark:to-slate-900/50 dark:hover:border-slate-700/80">
  <div class="absolute -top-12 -right-12 h-24 w-24 
    rounded-full bg-primary-500/20 blur-2xl 
    opacity-0 transition-opacity 
    group-hover:opacity-100"></div>
  <div class="relative space-y-3">
    <!-- Content -->
  </div>
</div>
```

---

### Form Elements

#### Premium Input
```html
<input class="w-full rounded-2xl border border-slate-200/60 
  bg-white/80 px-4 py-3 text-sm shadow-sm 
  transition duration-200 
  placeholder:text-slate-400 
  focus:border-primary-500/80 focus:bg-white 
  focus:outline-none focus:ring-4 focus:ring-primary-500/10 
  dark:border-slate-700/60 dark:bg-slate-950/40 
  dark:text-white dark:placeholder:text-slate-500 
  dark:focus:border-primary-400 dark:focus:bg-slate-950" />
```

#### Premium Select
```html
<select class="w-full rounded-2xl border border-slate-200/60 
  bg-white/80 px-4 py-3 text-sm 
  transition duration-200 
  focus:border-primary-500/80 focus:bg-white 
  focus:outline-none focus:ring-4 focus:ring-primary-500/10 
  dark:border-slate-700/60 dark:bg-slate-950/40 
  dark:text-white dark:focus:border-primary-400 
  dark:focus:bg-slate-950">
  <!-- options -->
</select>
```

#### Premium Textarea
```html
<textarea class="w-full rounded-2xl border border-slate-200/60 
  bg-white/80 px-4 py-3 text-sm leading-7 
  transition duration-200 
  placeholder:text-slate-400 
  focus:border-primary-500/80 focus:bg-white 
  focus:outline-none focus:ring-4 focus:ring-primary-500/10 
  dark:border-slate-700/60 dark:bg-slate-950/40 
  dark:text-white dark:placeholder:text-slate-500 
  dark:focus:border-primary-400 dark:focus:bg-slate-950">
</textarea>
```

#### Input with Icon
```html
<div class="relative">
  <input type="number" class="w-full ... pl-10" />
  <span class="pointer-events-none absolute inset-y-0 left-4 
    flex items-center text-xs font-semibold text-slate-500">
    %
  </span>
</div>
```

---

### Buttons

#### Primary Button (CTA)
```html
<button type="submit" class="inline-flex h-11 
  min-w-[14rem] items-center justify-center gap-2.5 
  rounded-2xl 
  bg-gradient-to-r from-slate-950 to-slate-800 
  px-6 text-sm font-bold text-white 
  shadow-lg 
  transition-all duration-200 
  hover:shadow-xl hover:-translate-y-0.5 
  disabled:opacity-50 disabled:cursor-not-allowed 
  disabled:shadow-none 
  dark:from-primary-600 dark:to-primary-700 
  dark:shadow-[0_10px_30px_-10px_rgba(37,99,235,0.7)] 
  dark:hover:shadow-[0_15px_40px_-10px_rgba(37,99,235,0.9)]">
</button>
```

#### Secondary Button
```html
<button type="button" class="inline-flex h-11 
  items-center justify-center gap-2 
  rounded-2xl border border-slate-200/60 
  bg-white px-5 text-sm font-semibold 
  text-slate-700 shadow-sm 
  transition-all duration-200 
  hover:border-slate-300/80 hover:bg-slate-50 
  hover:shadow-md active:scale-95 
  dark:border-slate-700/60 dark:bg-slate-950/50 
  dark:text-slate-300 dark:hover:border-slate-600/80 
  dark:hover:bg-slate-900">
</button>
```

---

### Status Badges

#### Success Badge
```html
<span class="inline-flex items-center gap-2.5 rounded-full 
  border border-emerald-200 bg-emerald-50 px-3.5 py-1.5 
  text-xs font-semibold text-emerald-700 
  dark:border-emerald-500/20 dark:bg-emerald-500/10 
  dark:text-emerald-200">
  <span class="h-2 w-2 rounded-full bg-emerald-500"></span>
  Saved
</span>
```

#### Warning Badge
```html
<span class="inline-flex items-center gap-2.5 rounded-full 
  border border-amber-200 bg-amber-50 px-3.5 py-1.5 
  text-xs font-semibold text-amber-800 
  dark:border-amber-500/20 dark:bg-amber-500/10 
  dark:text-amber-200">
  <span class="h-2 w-2 rounded-full bg-amber-500"></span>
  Needs Review
</span>
```

#### Info Badge
```html
<span class="inline-flex items-center gap-2.5 rounded-full 
  border border-primary-200/60 bg-primary-50/80 px-3.5 py-1.5 
  text-xs font-semibold text-primary-700 
  dark:border-primary-500/20 dark:bg-primary-500/10 
  dark:text-primary-200">
  <span class="h-2 w-2 rounded-full bg-primary-600 
    animate-pulse"></span>
  FinAI Control Center
</span>
```

---

### Icons & Icon Containers

#### Icon with Colored Background (Header)
```html
<div class="flex h-10 w-10 items-center justify-center 
  rounded-xl 
  bg-primary-100 text-primary-700 
  dark:bg-primary-500/20 dark:text-primary-300">
  <i data-lucide="building-2" class="h-5 w-5"></i>
</div>
```

#### Icon Container Variants
```html
<!-- Primary -->
<div class="bg-primary-100 text-primary-700 
  dark:bg-primary-500/20 dark:text-primary-300"></div>

<!-- Success/Emerald -->
<div class="bg-emerald-100 text-emerald-700 
  dark:bg-emerald-500/20 dark:text-emerald-300"></div>

<!-- Warning/Amber -->
<div class="bg-amber-100 text-amber-700 
  dark:bg-amber-500/20 dark:text-amber-300"></div>

<!-- Info/Violet -->
<div class="bg-violet-100 text-violet-700 
  dark:bg-violet-500/20 dark:text-violet-300"></div>

<!-- Secondary/Blue -->
<div class="bg-blue-100 text-blue-700 
  dark:bg-blue-500/20 dark:text-blue-300"></div>
```

---

### Text & Typography

#### Eyebrow/Label
```html
<p class="text-xs font-semibold uppercase 
  tracking-wider text-slate-500 dark:text-slate-500">
  Label
</p>
```

#### Section Title
```html
<h2 class="text-lg font-bold 
  text-slate-950 dark:text-white">
  Section Title
</h2>
```

#### Description
```html
<p class="max-w-sm text-sm 
  text-slate-600 dark:text-slate-400">
  Lorem ipsum description...
</p>
```

#### Helper Text
```html
<p class="text-xs leading-relaxed 
  text-slate-500 dark:text-slate-400">
  Helper text or hint...
</p>
```

---

### Alert/Info Boxes

#### Success Info Box
```html
<div class="flex gap-3 rounded-2xl border border-emerald-200/60 
  bg-emerald-50/80 p-4 
  dark:border-emerald-500/20 dark:bg-emerald-500/10">
  <span class="flex h-5 w-5 shrink-0 items-center 
    justify-center rounded-lg 
    bg-emerald-100 text-emerald-700 
    dark:bg-emerald-500/20 dark:text-emerald-300">
    <i data-lucide="check" class="h-3 w-3"></i>
  </span>
  <div>
    <p class="text-xs font-semibold 
      text-slate-900 dark:text-white">Title</p>
    <p class="mt-0.5 text-xs 
      text-slate-600 dark:text-slate-400">Description</p>
  </div>
</div>
```

#### Warning Info Box
```html
<div class="flex gap-3 rounded-2xl border border-amber-200/60 
  bg-amber-50/80 p-4 
  dark:border-amber-500/20 dark:bg-amber-500/10">
  <span class="flex h-5 w-5 shrink-0 items-center 
    justify-center rounded-lg 
    bg-amber-100 text-amber-700 
    dark:bg-amber-500/20 dark:text-amber-300">
    <i data-lucide="alert-circle" class="h-3 w-3"></i>
  </span>
  <div>
    <p class="text-xs font-semibold 
      text-slate-900 dark:text-white">Needs Attention</p>
    <p class="mt-0.5 text-xs 
      text-slate-600 dark:text-slate-400">Description</p>
  </div>
</div>
```

---

### Toggle Switch

#### Premium Toggle
```html
<div @click="settings.toggle = !settings.toggle" 
  class="flex cursor-pointer items-center 
  justify-between gap-4 rounded-lg 
  border border-slate-100/60 bg-slate-50/50 
  px-3 py-3 transition-all duration-200 
  hover:bg-slate-100 
  dark:border-slate-800/60 dark:bg-slate-950/20 
  dark:hover:bg-slate-950/40">
  
  <div class="space-y-1">
    <p class="text-xs font-semibold 
      text-slate-900 dark:text-white">Label</p>
    <p class="text-xs leading-relaxed 
      text-slate-500 dark:text-slate-400">Description</p>
  </div>
  
  <button @click.stop="settings.toggle = !settings.toggle" 
    role="switch" 
    :aria-checked="settings.toggle ? 'true' : 'false'"
    class="relative mt-0.5 inline-flex h-5 w-9 
    shrink-0 rounded-full transition-all duration-200 
    focus:outline-none focus:ring-2 focus:ring-primary-500/50"
    :class="settings.toggle ? 'bg-primary-600 
      shadow-md shadow-primary-500/30' : 'bg-slate-300 
      dark:bg-slate-700'">
    <span class="absolute inset-y-0.5 right-0.5 
      h-4 w-4 rounded-full bg-white shadow 
      transition-transform duration-200"
      :class="settings.toggle ? '-translate-x-4' : 'translate-x-0'">
    </span>
  </button>
</div>
```

---

### Grid Layouts

#### 2-Column Section Grid
```html
<div class="grid gap-3 sm:grid-cols-2">
  <!-- Item 1 -->
  <!-- Item 2 -->
</div>
```

#### Statistics Grid (4 Columns)
```html
<div class="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
  <!-- Stat 1 -->
  <!-- Stat 2 -->
  <!-- Stat 3 -->
  <!-- Stat 4 -->
</div>
```

#### Full-Width 2-Column
```html
<div class="grid gap-8 lg:grid-cols-2">
  <!-- Section 1 -->
  <!-- Section 2 -->
</div>
```

#### Nested Grid (2+3 columns)
```html
<div class="grid gap-8 lg:grid-cols-[minmax(0,0.92fr)_minmax(0,1.08fr)]">
  <div class="grid gap-5 md:grid-cols-2">
    <!-- Item 1 -->
    <!-- Item 2 -->
  </div>
  <div>
    <!-- Side content -->
  </div>
</div>
```

---

### Spacing Reference

| Function | Classes |
|----------|---------|
| **Section Gap** | `gap-6`, `gap-8` |
| **Card Padding** | `p-6`, `p-8` |
| **Internal Spacing** | `space-y-3`, `space-y-4`, `space-y-5` |
| **Grid Gap** | `gap-3`, `gap-4` |
| **Top Margin** | `mt-1`, `mt-3`, `mt-6` |
| **Border Spacing** | `px-3`, `px-4`, `px-5`, `px-8` |

---

### Dark Mode Quick Switch

Prepend `dark:` to any Tailwind class:
```html
<!-- Light -->
<div class="bg-white text-slate-900">

<!-- Dark -->
<div class="bg-white dark:bg-slate-950 
  text-slate-900 dark:text-white">
```

---

## 🎯 Copy-Paste Patterns

### New Section Template
```html
<section class="group relative overflow-hidden rounded-3xl 
  border border-slate-200/60 
  bg-gradient-to-br from-white via-slate-50/30 to-white 
  p-8 shadow-sm transition-all hover:shadow-md 
  dark:border-slate-800/60 dark:from-slate-950/80 
  dark:via-slate-900/40 dark:to-slate-950/80">
  
  <div class="absolute -top-24 -left-24 h-48 w-48 
    rounded-full bg-[COLOR]-500/10 blur-3xl 
    opacity-0 transition-opacity 
    group-hover:opacity-100"></div>
  
  <div class="relative space-y-6 border-b 
    border-slate-100/80 pb-6 dark:border-slate-800/80">
    <div class="flex items-start gap-3">
      <div class="flex h-10 w-10 items-center justify-center 
        rounded-xl bg-[COLOR]-100 text-[COLOR]-700 
        dark:bg-[COLOR]-500/20 dark:text-[COLOR]-300">
        <i data-lucide="[ICON]"></i>
      </div>
      <div>
        <p class="text-xs font-semibold uppercase 
          tracking-wider text-slate-500">Category</p>
        <h2 class="text-lg font-bold 
          text-slate-950 dark:text-white">Title</h2>
        <p class="mt-1 max-w-sm text-sm 
          text-slate-600 dark:text-slate-400">Description</p>
      </div>
    </div>
  </div>
  
  <div class="relative mt-6 space-y-4">
    <!-- Form fields here -->
  </div>
</section>
```

Replace:
- `[COLOR]` with: `primary`, `emerald`, `amber`, `violet`, `blue`
- `[ICON]` with: Lucide icon name

---

**Color Palette:**
- Primary: `primary` (indigo/blue)
- Success: `emerald`
- Warning: `amber`
- Info: `primary`
- Error: `red`
- Secondary: `violet`, `blue`

Last Updated: March 2026
Version: 1.0
