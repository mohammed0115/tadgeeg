# 🌐 02 — الصفحة الرئيسية (Landing Page)

> Prompts لتحويل صفحة `templates/landing/index.html` لصفحة تسويقية احترافية بهوية تدقيق

---

## 🎯 Prompt 2.1 — التحويل الكامل للصفحة الرئيسية

```
أعمل على مشروع Django اسمه Tadgeeg AI. ملف `templates/landing/index.html` 
حالياً يحتوي على ألوان بنفسجية وغير متماشي مع هوية تدقيق.

المطلوب: حوّل الصفحة بالكامل لتصميم احترافي بهوية تدقيق:

# الهوية:
- الأساسي: #003366 (أزرق كحلي)
- التمييز: #10B981 (أخضر)
- الخطوط: Tajawal (نصوص) + Cairo (عناوين)
- اللوقو: دائرة زرقاء + علامة صح خضراء

# البنية المطلوبة:

## 1. Navigation (sticky)
- Logo + كلمة "تدقيق Tadgeeg"
- Links: الرئيسية، المميزات، الأسعار، عن الشركة، اتصل بنا
- Buttons: تسجيل الدخول (outline)، ابدأ تجربتك المجانية (#10B981)
- زر hamburger للجوال
- خلفية شفافة مع backdrop-blur

## 2. Hero Section
- خلفية: gradient ناعم من f8fafc إلى ffffff مع orbs ملونة blurred
- العنوان: "مستقبل المراجعة المالية السحابية، هنا"
  - بخط Cairo 60px font-weight 900
  - "السحابية" بلون #10B981
- الوصف: "أتمتة ذكية، دقة متناهية، وتقارير فورية"
- زرين: ابدأ تجربتك المجانية (#10B981) + طلب ديمو (outline)
- يمين: laptop mockup فيه dashboard preview (HTML/CSS بدون صور)
- إحصائيات تحت الأزرار: +2.5M فاتورة، 95% أتمتة، 98% دقة

## 3. Features Grid (3 أعمدة)
لكل ميزة: أيقونة في كادر ملون 64x64 + عنوان + وصف
- "أتمتة العمليات" (أيقونة Zap)
- "كشف الاحتيال" (أيقونة Shield)
- "تقارير ذكية" (أيقونة BarChart)
- hover effects: translateY + shadow + شريط tail متدرج

## 4. Compliance Section (خلفية #003366)
- العنوان: "نغطي دول مجلس التعاون الخليجي"
- وصف بنص أبيض/شفاف
- 4 شارات: ZATCA السعودية، FTA الإمارات، GAZT الكويت، NBR البحرين
- بطاقة جانبية: "شهادات الامتثال" مع ISO 27001, SOC 2, ZATCA Phase 2

## 5. How It Works (4 خطوات)
1. ارفع المستند
2. تحليل بالذكاء الاصطناعي
3. كشف الاحتيال والامتثال
4. تقرير شامل

كل خطوة: رقم كبير + أيقونة + عنوان + وصف.
خط متقطع رابط بين الخطوات.

## 6. Pricing Section (3 خطط)
- Starter: مجاني (50 فاتورة/شهر)
- Professional: 499 ر.س/شهر [الأكثر شعبية]
- Enterprise: حسب الطلب
الوسطى: حدود خضراء + Badge + scale-105

## 7. Testimonials (3 شهادات عملاء)
بطاقات بيضاء + اقتباس + اسم + وظيفة + شركة + أيقونة

## 8. FAQ (Accordion)
6 أسئلة شائعة باستخدام Alpine.js للـ toggle:
- ما هو نظام تدقيق؟
- هل متوافق مع ZATCA؟
- كم يستغرق التحليل؟
- هل بياناتي آمنة؟
- ما الـ APIs المتاحة؟
- كيف يمكنني التواصل مع الدعم؟

## 9. CTA Banner (خلفية متدرجة)
"ابدأ رحلة التدقيق الذكي اليوم"
+ زر كبير "ابدأ تجربتك المجانية"

## 10. Footer
- عمود 1: اللوقو + وصف قصير + social icons
- عمود 2: المنتج (الفواتير، التقارير، الامتثال، API)
- عمود 3: الشركة (عن، اتصل، وظائف، مدونة)
- عمود 4: الدعم (الوثائق، النظام، الحالة، الأسئلة)
- شريط سفلي: © 2026 Tadgeeg by Get Solution Company

# الشروط التقنية:
1. استخدم Tailwind CSS (موجود في base.html)
2. استخدم Alpine.js للـ interactivity
3. احتفظ بكل `{% load static i18n %}` و `{% trans %}`
4. احتفظ بـ `{{ product_name }}`, `{{ product_tagline }}` etc. من branding.py
5. RTL support كامل
6. Responsive: mobile (< 640px), tablet (768px), desktop (1024px+)
7. Animations:
   - fadeInUp للعناصر عند التحميل
   - float للـ orbs في الـ hero
   - reveal-on-scroll باستخدام IntersectionObserver
8. Performance:
   - استخدم font-display: swap
   - lazy loading للصور إن وجدت

أرفق الكود الحالي [ضع الملف هنا]

أعطني الملف الكامل المعدّل، جاهز للاستبدال المباشر.
```

---

## 🎯 Prompt 2.2 — تحديث Laptop Mockup في Hero

```
في `templates/landing/index.html`، الـ Hero section يحتوي على mockup للوحة 
التحكم. أريد تحسينه ليعرض dashboard تدقيق الفعلي.

المطلوب: بناء laptop mockup كامل بـ HTML/CSS فقط (بدون صور):

# هيكل الـ Laptop:
<div class="laptop">
  <div class="laptop-screen">
    <div class="laptop-display"> ← 16:10 aspect ratio
      [محتوى الـ dashboard هنا]
    </div>
  </div>
  <div class="laptop-base"></div>
</div>

# محتوى الـ Display (mockup داخلي):

## Sidebar اليمنى (22% عرض):
- لوقو تدقيق صغير
- 7 nav items مع dots:
  • Dashboard (active)
  • Features
  • Departments  
  • Company
  • About
  • Email
  • Settings

## Main Area:
### Header:
- Search bar + 🔍
- Avatar دائري

### Title row:
- "Dashboard" بخط Cairo
- زر "+ Free Trial" أخضر

### 4 Stat Cards:
- Financial Accuracy: $2.5M (+14.8%) [أخضر متدرج]
- Audit Result: $52.0M (+10.5%)
- Reporting: $200K (+18.6%)
- Data Security: $36K (-21.3%) [نص أحمر]

### Charts Row (شبكة 2/1):
- Audit Dashboard (يسار): bar chart 7 أعمدة مزدوجة (أزرق + أخضر)
- Financial Summary (يمين): pie chart بـ conic-gradient
  • 60% Audit (أزرق)
  • 25% Reports (أخضر)
  • 15% Security (رمادي)

### Table:
3 صفوف:
- Quarterly Reports | $1,050,000 | 8/2025 | $18.0K | +5% lift
- Quarterly Reports | $1,150,100 | 8/2025 | $15.0K | +1% lift
- Reports Reviewed | $1,300,500 | 8/2025 | $15.0K | +5% lift

# المتطلبات:
- استخدم font-size صغير (5-9px) لأن الـ mockup داخل laptop
- الألوان: #003366 (primary)، #10B981 (accent)، #f8fafc (bg)
- درجات اللون من tailwind: bg-slate-50, border-slate-200
- shadow على laptop: filter: drop-shadow(0 30px 50px rgba(0,51,102,0.25))
- animation: float 6s ease-in-out infinite للـ laptop

أعطني الـ HTML + CSS كاملاً (يمكن استخدام style block داخل الصفحة).
```

---

## 🎯 Prompt 2.3 — إضافة قسم Pricing تفاعلي

```
في `templates/landing/index.html`، أضف قسم Pricing احترافي بميزة 
التبديل بين شهري/سنوي (مع خصم 20% للسنوي).

المطلوب:

# Toggle Switch:
- 2 buttons: "شهري" | "سنوي (وفر 20%)"
- استخدم Alpine.js: x-data="{ billing: 'monthly' }"
- Badge "وفر 20%" بجانب "سنوي"

# 3 خطط:

## Starter (مجاني)
- 0 ر.س / شهر
- ✓ 50 فاتورة شهرياً
- ✓ مستخدم واحد
- ✓ تحليل أساسي للفواتير
- ✓ تقارير PDF بسيطة
- ✓ دعم بريد إلكتروني
- ✗ كشف احتيال متقدم
- ✗ تكامل ZATCA
- ✗ API access
- زر: "ابدأ مجاناً" (outline)

## Professional ⭐ [الأكثر شعبية]
- 499 ر.س / شهر (شهري) أو 4,790 ر.س / سنة (سنوي)
- ✓ 500 فاتورة شهرياً
- ✓ 5 مستخدمين
- ✓ كشف احتيال متقدم
- ✓ تكامل ZATCA Phase 2
- ✓ تقارير مخصصة
- ✓ API access (1000 req/day)
- ✓ دعم أولوية 24/7
- ✓ تكامل ERP
- زر: "ابدأ التجربة المجانية" (#10B981)
- Badge: "الأكثر شعبية" في الأعلى
- البطاقة scale-105 + حدود خضراء

## Enterprise
- "حسب الطلب"
- ✓ فواتير غير محدودة
- ✓ مستخدمين غير محدودين  
- ✓ SLA مخصص (99.99%)
- ✓ مدير حساب مخصص
- ✓ تكاملات مخصصة
- ✓ تدريب فريقك
- ✓ White-label option
- زر: "تواصل مع المبيعات" (outline)

# التصميم:
- شبكة 3 أعمدة (1 عمود في الجوال)
- بطاقات بيضاء + border-radius 20px + shadow على hover
- استخدم Lucide Icons: check (أخضر) و x (رمادي)
- Hover: translateY(-4px) + shadow أعمق
- أسعار بخط Cairo 48px font-weight 900
- ر.س بحجم أصغر بجانب السعر

# Pricing display logic مع Alpine.js:
<span x-text="billing === 'monthly' ? '499 ر.س' : '4,790 ر.س'"></span>
<span x-text="billing === 'monthly' ? '/ شهر' : '/ سنة'"></span>

# جدول مقارنة شامل تحت البطاقات:
- 30+ ميزة في عمود يسار
- 3 أعمدة لكل خطة بـ ✓ أو ✗ أو نص
- categorized: التحليل، الأمان، التكاملات، الدعم
- accordion لكل category مع Alpine.js

# قسم FAQ خاص بالأسعار:
- هل يمكنني تغيير الخطة؟
- ما هي خيارات الدفع؟
- هل في رسوم خفية؟
- كيف يتم احتساب الفواتير؟

استخدم Tailwind فقط بدون CSS مخصص.
احتفظ بكل `{% trans %}` للترجمة لاحقاً.

أعطني كامل قسم Pricing جاهز للإلصاق في landing/index.html.
```

---

## 🎯 Prompt 2.4 — إضافة قسم Customer Logos / Trust Badges

```
في `templates/landing/index.html`، أضف قسم "موثوق من قبل" يعرض شعارات 
العملاء أو شركاء وشهادات الموثوقية.

المطلوب:

# قسم 1: Trust Badges
خط أعلى الـ Hero أو بعده مباشرة:
"موثوق من قبل أكثر من 1,200+ منظمة في الخليج"

شبكة 6 أعمدة (شعارات وهمية SVG):
- استخدم اختصارات الشركات (نص + خلفية رمادية فاتحة)
- رمادي بـ grayscale
- على hover: ملوّن بـ animation
- مسافات متساوية

# قسم 2: شهادات الامتثال
شبكة 4 بطاقات صغيرة:

البطاقة 1: ZATCA
- شعار ZATCA SVG
- "متوافق مع المرحلة الثانية"
- ✓ E-Invoicing
- ✓ QR Code
- ✓ Digital Signature

البطاقة 2: ISO 27001
- شعار ISO
- "أمن المعلومات"
- شارة "Certified"

البطاقة 3: SOC 2 Type II
- شعار SOC 2
- "أمن البيانات والخصوصية"
- شارة "Audited"

البطاقة 4: GDPR Ready
- شعار GDPR
- "حماية البيانات الشخصية"
- شارة "Compliant"

# قسم 3: إحصائيات الثقة
شريط واسع بخلفية #003366:
- "+2.5 مليون" فاتورة معالجة
- "+1,200" منظمة
- "98%" نسبة الدقة
- "99.9%" نسبة الـ Uptime

كل رقم بـ Cairo 48px أبيض + label تحته.

# Animations:
- counter animation للأرقام (تعد من 0 لقيمتها)
- استخدم IntersectionObserver للتفعيل عند التمرير
- delay 100ms بين كل رقم

أعطني كود HTML + Tailwind كامل + الـ JavaScript للـ counters.
```

---

## 🎯 Prompt 2.5 — تحسين أداء Landing Page

```
في `templates/landing/index.html` لمشروع Tadgeeg AI:

المطلوب: تحسين أداء الصفحة لتسريع التحميل:

# 1. تحسين الخطوط:
- استخدم font-display: swap في @font-face
- استخدم preload للخطوط الأساسية:
```html
<link rel="preload" href="..." as="font" type="font/woff2" crossorigin>
```
- حمّل الخطوط من نفس domain إن أمكن (دجاد كـ static)

# 2. تحسين الصور:
- كل الصور تستخدم loading="lazy" (ما عدا above-the-fold)
- استخدم srcset للـ responsive images
- استخدم WebP format مع fallback لـ JPG/PNG
- أضف width و height attributes صراحة

# 3. تحسين الـ JavaScript:
- استخدم defer لكل الـ scripts غير الحرجة
- ادمج Alpine.js فقط للأقسام التي تحتاجه
- الـ animations: استخدم CSS transforms بدل JS animations
- استخدم will-change بحذر (مع الـ animations فقط)

# 4. تحسين الـ CSS:
- استخدم critical CSS inline في <head>
- أجّل non-critical CSS بـ media="print" trick
- احذف unused Tailwind classes (في production)

# 5. Cache:
- أضف Cache-Control headers في nginx config
- استخدم versioning للـ static files
- ETag على الموارد

# 6. CDN (اختياري):
- اقترح setup لـ Cloudflare/CloudFront
- DNS prefetch للموارد الخارجية:
```html
<link rel="dns-prefetch" href="//fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
```

# 7. Lighthouse Score المستهدف:
- Performance: 90+
- Accessibility: 95+
- Best Practices: 95+
- SEO: 100

# 8. SEO Tags في <head>:
```html
<meta name="description" content="...">
<meta name="keywords" content="تدقيق, ZATCA, AI, financial auditing...">

<!-- Open Graph -->
<meta property="og:type" content="website">
<meta property="og:title" content="...">
<meta property="og:description" content="...">
<meta property="og:image" content="...">
<meta property="og:url" content="https://tadgeeg.com">
<meta property="og:site_name" content="Tadgeeg">
<meta property="og:locale" content="ar_SA">

<!-- Twitter -->
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="...">
<meta name="twitter:description" content="...">
<meta name="twitter:image" content="...">

<!-- Schema.org JSON-LD -->
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  "name": "Tadgeeg AI",
  ...
}
</script>
```

أعطني التحديثات اللازمة لـ:
1. الـ <head> الكامل
2. أمثلة على lazy loading
3. nginx config لـ caching
4. سكريبت لتنظيف unused CSS

احتفظ بكل `{% load static i18n %}` و `{% trans %}`.
```

---

## 🎯 Prompt 2.6 — إضافة Animations احترافية

```
في `templates/landing/index.html`:

المطلوب: أضف animations احترافية لكل قسم في الصفحة الرئيسية.

# 1. Hero Section:
- العنوان: typewriter effect أو split-text reveal
- الوصف: fade-in delayed by 0.3s
- الأزرار: scale-in من 0.9 إلى 1
- اللابتوب: float continuously
- الـ stats: counter من 0 لرقمها (1.5s duration, easeOutQuart)

# 2. Features:
- بطاقات تدخل واحدة تلو الأخرى (stagger 100ms)
- على hover: 
  - الكرت يرتفع 8px
  - الأيقونة تنبض
  - شريط متدرج يظهر في الأعلى

# 3. Compliance Section:
- العنوان: slide-in from right
- الشارات: pop-in بـ scale animation
- الخلفية: subtle gradient animation

# 4. How It Works:
- الخطوات تظهر متتالية مع line drawing animation
- الخط بين الخطوات يُرسم بالتسلسل

# 5. Pricing:
- 3 بطاقات: stagger entrance من اليمين
- البطاقة الوسطى: pulse glow effect
- على hover: highlight + shadow

# 6. Testimonials:
- carousel بـ Alpine.js (auto-play 5s)
- swipe support للجوال
- dots navigation
- pause on hover

# 7. FAQ:
- accordion smooth transitions (max-height)
- الأيقونة تدور 90deg عند الفتح
- الإجابة تظهر بـ fade-slide

# 8. CTA Banner:
- خلفية متدرجة متحركة (gradient shift)
- الزر: shimmer effect

# 9. Footer:
- روابط: hover underline من المنتصف للخارج
- social icons: rotate + scale

# الأدوات:
- IntersectionObserver للـ reveal-on-scroll
- CSS animations + keyframes
- transform & opacity فقط (للأداء)
- prefers-reduced-motion للمستخدمين الحساسين:
```css
@media (prefers-reduced-motion: reduce) {
  * { animation: none !important; }
}
```

# الـ Performance:
- استخدم will-change بحذر
- لا تستخدم top/left للحركة (استخدم transform)
- debounce لـ scroll events
- requestAnimationFrame للـ counters

أعطني كل الـ CSS و JavaScript المطلوب، منظم في style block + script block 
يمكن إضافتها مباشرة في landing/index.html.
```

---

## 🎯 Prompt 2.7 — صفحة "عن الشركة" (About Us)

```
في مشروع Tadgeeg AI، أحتاج صفحة "عن الشركة" منفصلة.

المطلوب:

# 1. أنشئ template جديد: `templates/landing/about.html`
- يرث من `templates/base.html`
- يستخدم نفس navigation الـ landing page
- نفس footer

# 2. أضف URL في `apps/frontend/urls.py`:
path('about/', AboutPageView.as_view(), name='about')

# 3. أضف View في `apps/frontend/views.py`:
class AboutPageView(TemplateView):
    template_name = 'landing/about.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(get_branding_context())
        return context

# 4. محتوى الصفحة:

## Hero:
- "تدقيق - ذكاء مالي بلا حدود"
- وصف قصير عن المهمة

## قسم القصة (Story):
- "كيف بدأت تدقيق؟"
- نصوص + صورة (placeholder)
- الـ timeline من 2024 إلى الآن

## قسم القيم (Values):
4 بطاقات مع أيقونات:
- 🛡️ الأمان (Security)
- ⚡ الابتكار (Innovation)
- 🎯 الدقة (Precision)
- 🤝 الثقة (Trust)

## قسم الفريق (Team):
شبكة بطاقات لـ 4-6 أشخاص:
- صورة دائرية (placeholder)
- الاسم
- المنصب
- LinkedIn icon

## قسم الإحصائيات:
- +50 مهندس وخبير
- +5 سنوات خبرة
- +1,200 عميل سعيد
- +24/7 دعم متواصل

## قسم الـ Get Solution Company:
- شعار الشركة الأم
- وصف قصير
- روابط للمنتجات الأخرى

## قسم الشركاء (Partners):
شعارات شركاء (وهمية):
- AWS, Microsoft, OpenAI, ZATCA, etc.

## CTA: "انضم لرحلتنا"
- زر التقديم على وظيفة
- زر تواصل معنا

# الشروط:
- استخدم نفس هوية تدقيق (#003366 + #10B981)
- RTL + responsive
- استخدم Lucide icons
- Animations عند التمرير

أعطني:
1. الـ template الكامل (about.html)
2. التحديث على urls.py
3. التحديث على views.py
4. أي migrations لازمة
```

---

## ✅ Checklist بعد تطبيق هذا القسم

- [ ] `templates/landing/index.html` بالهوية الجديدة بالكامل
- [ ] لا توجد ألوان بنفسجية في الصفحة
- [ ] Laptop mockup يعرض dashboard وهمي بألوان تدقيق
- [ ] قسم Pricing موجود ويعمل (toggle شهري/سنوي)
- [ ] Trust badges + شهادات الامتثال موجودة
- [ ] Animations سلسة وعند التمرير
- [ ] Performance: Lighthouse score 85+
- [ ] SEO tags في الـ <head>
- [ ] Open Graph + Twitter cards
- [ ] صفحة About موجودة
- [ ] الموقع responsive على جميع الأحجام (مع الجوال)
- [ ] الترجمات `{% trans %}` تعمل في العربي والإنجليزي

---

**📌 بعد إكمال هذا القسم، انتقل لـ `03-AUTH-PAGES.md`**
