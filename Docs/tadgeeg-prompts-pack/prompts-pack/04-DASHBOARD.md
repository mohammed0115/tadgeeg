# 📊 04 — لوحة التحكم (Dashboard)

> Prompts لتطوير `templates/dashboard/index.html` و `templates/vendor_dashboard/*` وما يتعلق بالـ KPIs والـ Charts

---

## 🎯 Prompt 4.1 — تحويل Dashboard الرئيسية

```
في مشروع Tadgeeg AI، ملف `templates/dashboard/index.html` يستخدم gradients 
بنفسجية وزرقاء. أريد تحويله بالكامل لهوية تدقيق.

المطلوب: حدّث الصفحة بالكامل:

# 1. استبدل الـ Gradients:

```css
/* القديم */
.dashboard-gradient-blue   { background: linear-gradient(135deg,#3b82f6,#2563eb); }
.dashboard-gradient-violet { background: linear-gradient(135deg,#a855f7,#7c3aed); }
.dashboard-gradient-orange { background: linear-gradient(135deg,#fb923c,#f97316); }
.dashboard-gradient-green  { background: linear-gradient(135deg,#22c55e,#16a34a); }

/* الجديد */
.dashboard-gradient-primary { background: linear-gradient(135deg,#003366 0%,#002244 100%); }
.dashboard-gradient-accent  { background: linear-gradient(135deg,#10B981 0%,#059669 100%); }
.dashboard-gradient-warning { background: linear-gradient(135deg,#f59e0b 0%,#d97706 100%); }
.dashboard-gradient-danger  { background: linear-gradient(135deg,#ef4444 0%,#dc2626 100%); }
```

# 2. استبدل الزر Primary:
```css
/* القديم */
.dashboard-soft-button-primary {
  background: linear-gradient(135deg,#2563eb 0%,#9333ea 100%);
}

/* الجديد */
.dashboard-soft-button-primary {
  background: linear-gradient(135deg,#003366 0%,#10B981 100%);
  /* أو فقط: background: #10B981; */
}
```

# 3. الهيكل الجديد للـ Dashboard:

## Header Section:
- ترحيب: "مرحباً، [اسم المستخدم]"
- "إليك نظرة عامة على نشاط التدقيق اليوم"
- التاريخ بصيغة طويلة بالعربي
- زر "تصدير التقرير" (outline)
- زر "+ مستند جديد" (#10B981)

## 4 Stat Cards (Gradients):

كل بطاقة:
- خلفية gradient
- أيقونة كبيرة شفافة في الخلفية (top-right)
- Label أبيض
- Value كبير أبيض (Cairo 32px font-weight 900)
- Trend: ↑ أو ↓ مع نسبة + رسم بياني صغير (sparkline)
- زر "عرض التفاصيل" → بسهم

البطاقات الـ 4:
1. إجمالي الفواتير المحلّلة (gradient-primary)
   - 1,247 فاتورة هذا الشهر
   - ↑ +18.5% من الشهر السابق
   
2. دقة التحليل (gradient-accent)
   - 98.3%
   - ↑ +0.4% تحسّن
   
3. مخاطر مكتشفة (gradient-warning)
   - 24 حالة
   - ↓ -12% انخفاض
   
4. الامتثال ZATCA (gradient-primary لون مختلف)
   - 99.7%
   - متوافق

## شبكة 2 أعمدة (للـ Charts):

### عمود 1 (2/3 العرض): الرسم البياني الرئيسي
- Card بيضاء + box-shadow
- Title: "تطور التحليل"
- Tabs: يومي | أسبوعي | شهري | سنوي
- Chart.js: Line chart بـ 2 خطوط:
  • فواتير محلّلة (#003366)
  • فواتير ذات مخاطر (#ef4444)
- محور Y: العدد
- محور X: التواريخ
- Tooltip مخصص بهوية تدقيق

### عمود 2 (1/3 العرض): توزيع المخاطر
- Card بيضاء
- Title: "توزيع مستويات المخاطر"
- Doughnut chart:
  • منخفض: #10B981 (60%)
  • متوسط: #f59e0b (25%)
  • عالي: #f97316 (10%)
  • حرج: #ef4444 (5%)
- في الوسط: العدد الإجمالي
- Legend بنسب مئوية

## شبكة 2 أعمدة (للـ Tables):

### عمود 1 (2/3 العرض): آخر الفواتير
- Card بيضاء
- Title: "آخر الفواتير"
- زر "عرض الكل" → /invoices/
- جدول:
  • أيقونة الملف (PDF أحمر، XLSX أخضر، إلخ)
  • اسم الملف + المورد
  • التاريخ
  • المبلغ
  • Badge للحالة (مكتمل، معلّق، مرفوض)
  • Badge للمخاطر
- 5 صفوف فقط
- في الـ row hover: یعرض quick actions

### عمود 2 (1/3 العرض): التنبيهات
- Card بيضاء
- Title: "🔔 التنبيهات"
- Badge "3 جديد"
- قائمة التنبيهات:
  • لون left border حسب النوع
  • Icon
  • Title (bold)
  • Description (small, muted)
  • Time ago
- "عرض جميع التنبيهات"

## Quick Actions Section:
شبكة 4 بطاقات:
- 📤 رفع فاتورة
- 📊 إنشاء تقرير
- 🔍 بحث متقدم
- ⚙️ الإعدادات

كل بطاقة:
- خلفية بيضاء + border رفيع
- أيقونة كبيرة (بلون primary)
- Title
- Description قصير
- على hover: shadow + translateY

# 4. الـ Backend Context:

في `apps/frontend/views.py` أو `apps/vendor_dashboard/views.py`:
```python
class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'dashboard/index.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        org = self.request.user.organization
        now = timezone.now()
        month_start = now.replace(day=1)
        last_month = month_start - timedelta(days=1)
        last_month_start = last_month.replace(day=1)
        
        # الفواتير
        invoices = Invoice.objects.filter(organization=org)
        this_month = invoices.filter(created_at__gte=month_start)
        last_month_inv = invoices.filter(
            created_at__gte=last_month_start,
            created_at__lt=month_start
        )
        
        context.update({
            'total_invoices': this_month.count(),
            'invoices_change': calc_change(this_month.count(), last_month_inv.count()),
            'accuracy_rate': calc_accuracy(this_month),
            'high_risk_count': this_month.filter(risk_level='high').count(),
            'compliance_rate': calc_compliance(this_month),
            'recent_invoices': invoices.order_by('-created_at')[:5],
            'alerts': Alert.objects.filter(organization=org, is_read=False)[:5],
            'risk_distribution': calc_risk_distribution(this_month),
            'analysis_timeline': get_timeline_data(invoices, period='month'),
        })
        return context
```

# 5. الترجمات الجديدة (locale/ar/LC_MESSAGES/django.po):
```
msgid "Welcome back, %(name)s"
msgstr "مرحباً بعودتك، %(name)s"

msgid "Total Analyzed Invoices"
msgstr "إجمالي الفواتير المحلّلة"

msgid "Analysis Accuracy"
msgstr "دقة التحليل"

msgid "Detected Risks"
msgstr "مخاطر مكتشفة"

msgid "ZATCA Compliance"
msgstr "الامتثال لـ ZATCA"
```

أرفق الكود الحالي [ضع index.html]

أعطني الملف الكامل المعدّل.
```

---

## 🎯 Prompt 4.2 — Sidebar Navigation الموحدة

```
في مشروع Tadgeeg AI، الـ sidebar في `templates/base.html` يحتاج تحسين.

المطلوب: صمّم sidebar موحدة لكل صفحات الـ dashboard:

# الهيكل:
```html
<aside class="sidebar bg-primary-700 text-white" x-data="sidebarState()">
  <!-- Header مع Logo -->
  <div class="sidebar-header">
    <a href="{% url 'dashboard' %}" class="logo">
      <svg>[لوقو تدقيق]</svg>
      <span x-show="!collapsed">تدقيق</span>
    </a>
    <button @click="collapsed = !collapsed">
      <icon-menu />
    </button>
  </div>
  
  <!-- Navigation -->
  <nav class="sidebar-nav">
    <!-- Group 1: العمل اليومي -->
    <div class="nav-group">
      <div class="nav-group-title">العمل اليومي</div>
      <a href="..." class="nav-item {% block nav_dashboard %}{% endblock %}">
        <icon-dashboard />
        <span>لوحة التحكم</span>
      </a>
      <a href="..." class="nav-item {% block nav_invoices %}{% endblock %}">
        <icon-file-text />
        <span>الفواتير</span>
        <span class="badge">{{ pending_count }}</span>
      </a>
      <a href="..." class="nav-item {% block nav_documents %}{% endblock %}">
        <icon-folder />
        <span>المستندات</span>
      </a>
      <a href="..." class="nav-item {% block nav_upload %}{% endblock %}">
        <icon-upload />
        <span>رفع جديد</span>
      </a>
    </div>
    
    <!-- Group 2: التحليل -->
    <div class="nav-group">
      <div class="nav-group-title">التحليل والتدقيق</div>
      <a href="..." class="nav-item {% block nav_audit %}{% endblock %}">
        <icon-search />
        <span>جلسات التدقيق</span>
      </a>
      <a href="..." class="nav-item {% block nav_anomalies %}{% endblock %}">
        <icon-alert-triangle />
        <span>كشف الشذوذ</span>
      </a>
      <a href="..." class="nav-item {% block nav_reports %}{% endblock %}">
        <icon-bar-chart />
        <span>التقارير</span>
      </a>
      <a href="..." class="nav-item {% block nav_compliance %}{% endblock %}">
        <icon-shield-check />
        <span>الامتثال ZATCA</span>
      </a>
    </div>
    
    <!-- Group 3: الإدارة -->
    <div class="nav-group">
      <div class="nav-group-title">الإدارة</div>
      <a href="..." class="nav-item">
        <icon-users />
        <span>الفريق</span>
      </a>
      <a href="..." class="nav-item">
        <icon-database />
        <span>التخزين</span>
      </a>
      <a href="..." class="nav-item">
        <icon-activity />
        <span>سجل النشاط</span>
      </a>
    </div>
  </nav>
  
  <!-- Footer -->
  <div class="sidebar-footer">
    <button class="nav-item" @click="toggleDarkMode()">
      <icon-moon x-show="!dark" />
      <icon-sun x-show="dark" />
      <span x-text="dark ? 'الوضع النهاري' : 'الوضع الليلي'"></span>
    </button>
    <a href="{% url 'settings' %}" class="nav-item">
      <icon-settings />
      <span>الإعدادات</span>
    </a>
    <button @click="logout()" class="nav-item text-red-400">
      <icon-log-out />
      <span>تسجيل الخروج</span>
    </button>
    
    <!-- User Info Card -->
    <div class="user-card">
      <div class="avatar">{{ user.initials }}</div>
      <div class="info">
        <div class="name">{{ user.full_name }}</div>
        <div class="email">{{ user.email }}</div>
      </div>
    </div>
  </div>
</aside>
```

# الـ CSS:
```css
.sidebar {
  width: 260px;
  height: 100vh;
  position: sticky;
  top: 0;
  background: #003366;
  color: white;
  display: flex;
  flex-direction: column;
  transition: width 0.3s ease;
}

.sidebar.collapsed { width: 80px; }
.sidebar.collapsed .nav-item span { display: none; }

.nav-group { padding: 8px; }
.nav-group-title {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.5px;
  color: rgba(255,255,255,0.5);
  padding: 12px 16px;
  text-transform: uppercase;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 11px 16px;
  border-radius: 10px;
  color: rgba(255,255,255,0.7);
  font-size: 14px;
  transition: all 0.2s ease;
}

.nav-item:hover {
  background: rgba(255,255,255,0.08);
  color: white;
}

.nav-item.active {
  background: rgba(16, 185, 129, 0.15);
  color: #10B981;
  box-shadow: inset 3px 0 0 #10B981;
}

.nav-item .badge {
  margin-right: auto;
  background: #10B981;
  color: white;
  font-size: 10px;
  padding: 2px 8px;
  border-radius: 100px;
}

.user-card {
  margin-top: auto;
  padding: 16px;
  background: rgba(255,255,255,0.05);
  border-radius: 12px;
  display: flex;
  gap: 12px;
  align-items: center;
}

.avatar {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: #10B981;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
}
```

# الـ State Management (Alpine.js):
```javascript
function sidebarState() {
  return {
    collapsed: localStorage.getItem('sidebar_collapsed') === 'true',
    dark: localStorage.getItem('theme') === 'dark',
    
    init() {
      this.applyDarkMode();
    },
    
    toggleCollapse() {
      this.collapsed = !this.collapsed;
      localStorage.setItem('sidebar_collapsed', this.collapsed);
    },
    
    toggleDarkMode() {
      this.dark = !this.dark;
      localStorage.setItem('theme', this.dark ? 'dark' : 'light');
      this.applyDarkMode();
    },
    
    applyDarkMode() {
      document.documentElement.classList.toggle('dark', this.dark);
    },
    
    logout() {
      // Show confirmation modal
      window.dispatchEvent(new CustomEvent('show-logout-modal'));
    }
  }
}
```

# Mobile Responsive:
- Sidebar تختفي تحت 1024px
- زر hamburger في الـ topbar
- عند الضغط: drawer ينزلق من اليمين + overlay
- إغلاق بالـ swipe أو الضغط خارجها

أعطني:
1. الـ HTML للـ sidebar (من base.html)
2. الـ CSS الكامل
3. الـ Alpine.js state
4. الـ topbar للجوال (hamburger button)
5. التحديثات على كل صفحات dashboard لاستخدام نفس البلوكات
```

---

## 🎯 Prompt 4.3 — Charts ديناميكية مع Chart.js

```
في مشروع Tadgeeg AI، الصفحة `templates/dashboard/index.html` تحتوي على Charts.

المطلوب: حسّن الـ Charts بـ Chart.js بأسلوب احترافي:

# 1. Line Chart - تطور التحليل:

```javascript
const ctx = document.getElementById('analysisChart');
const data = {{ analysis_timeline|safe }};

new Chart(ctx, {
  type: 'line',
  data: {
    labels: data.labels, // مثلاً: ['Jan', 'Feb', 'Mar'...]
    datasets: [
      {
        label: 'فواتير محلّلة',
        data: data.analyzed,
        borderColor: '#003366',
        backgroundColor: createGradient('#003366', 0.2),
        tension: 0.4,
        fill: true,
        borderWidth: 3,
        pointBackgroundColor: '#003366',
        pointBorderColor: '#ffffff',
        pointBorderWidth: 2,
        pointRadius: 5,
        pointHoverRadius: 8,
      },
      {
        label: 'فواتير ذات مخاطر',
        data: data.risky,
        borderColor: '#ef4444',
        backgroundColor: createGradient('#ef4444', 0.1),
        tension: 0.4,
        fill: true,
        borderWidth: 3,
      }
    ]
  },
  options: {
    responsive: true,
    maintainAspectRatio: false,
    interaction: {
      mode: 'index',
      intersect: false,
    },
    plugins: {
      legend: {
        position: 'top',
        align: 'end',
        labels: {
          font: {
            family: 'Cairo, Tajawal',
            size: 13,
            weight: 600,
          },
          usePointStyle: true,
          padding: 20,
        }
      },
      tooltip: {
        backgroundColor: '#003366',
        titleColor: '#ffffff',
        bodyColor: '#ffffff',
        borderColor: '#10B981',
        borderWidth: 1,
        padding: 12,
        displayColors: true,
        cornerRadius: 8,
        titleFont: {
          family: 'Cairo, Tajawal',
          weight: 700,
        },
        bodyFont: {
          family: 'Tajawal',
        },
        rtl: true,
        textDirection: 'rtl',
      }
    },
    scales: {
      y: {
        beginAtZero: true,
        grid: { color: 'rgba(0,0,0,0.05)' },
        ticks: { font: { family: 'Tajawal' } }
      },
      x: {
        grid: { display: false },
        ticks: { font: { family: 'Tajawal' } }
      }
    }
  }
});

function createGradient(color, opacity) {
  const ctx = document.createElement('canvas').getContext('2d');
  const gradient = ctx.createLinearGradient(0, 0, 0, 300);
  gradient.addColorStop(0, color + Math.round(opacity * 255).toString(16));
  gradient.addColorStop(1, color + '00');
  return gradient;
}
```

# 2. Doughnut Chart - توزيع المخاطر:

```javascript
new Chart(document.getElementById('riskChart'), {
  type: 'doughnut',
  data: {
    labels: ['منخفض', 'متوسط', 'عالي', 'حرج'],
    datasets: [{
      data: [{{ low_risk }}, {{ medium_risk }}, {{ high_risk }}, {{ critical_risk }}],
      backgroundColor: ['#10B981', '#f59e0b', '#f97316', '#ef4444'],
      borderColor: '#ffffff',
      borderWidth: 4,
      hoverBorderWidth: 6,
      hoverOffset: 8,
    }]
  },
  options: {
    cutout: '70%',
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        position: 'bottom',
        labels: {
          font: { family: 'Cairo' },
          padding: 16,
          usePointStyle: true,
        }
      },
      tooltip: { /* same as line chart */ },
      // Plugin مخصص لعرض العدد في الوسط
      doughnutCenterText: {
        display: true,
        text: '{{ total_risk }}',
        subtext: 'إجمالي'
      }
    }
  },
  plugins: [centerTextPlugin] // custom plugin
});

const centerTextPlugin = {
  id: 'centerText',
  afterDraw(chart) {
    const { ctx, chartArea: { width, height, top, left } } = chart;
    ctx.save();
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    
    // الرقم الكبير
    ctx.font = 'bold 36px Cairo';
    ctx.fillStyle = '#003366';
    ctx.fillText(chart.options.plugins.doughnutCenterText.text, left + width/2, top + height/2 - 8);
    
    // النص الصغير
    ctx.font = '14px Tajawal';
    ctx.fillStyle = '#64748b';
    ctx.fillText(chart.options.plugins.doughnutCenterText.subtext, left + width/2, top + height/2 + 18);
    
    ctx.restore();
  }
};
```

# 3. Bar Chart - أداء الموردين:

```javascript
new Chart(document.getElementById('vendorsChart'), {
  type: 'bar',
  data: {
    labels: ['شركة الحلول', 'مؤسسة الأعمال', 'شركة التطوير', 'مؤسسة الخدمات'],
    datasets: [{
      label: 'فواتير صحيحة',
      data: [45, 38, 30, 25],
      backgroundColor: '#10B981',
      borderRadius: 8,
      borderSkipped: false,
    }, {
      label: 'فواتير ذات مخاطر',
      data: [3, 5, 8, 12],
      backgroundColor: '#ef4444',
      borderRadius: 8,
      borderSkipped: false,
    }]
  },
  options: {
    responsive: true,
    indexAxis: 'y', // أفقي للقراءة بالعربي
    scales: {
      x: { stacked: true, grid: { display: false } },
      y: { stacked: true, grid: { display: false } }
    }
  }
});
```

# 4. Sparklines (داخل الـ stat cards):
```javascript
// رسم بياني صغير 100x40 بدون labels
new Chart(document.getElementById('sparkline1'), {
  type: 'line',
  data: {
    labels: ['','','','','','',''],
    datasets: [{
      data: [12, 19, 15, 25, 22, 30, 28],
      borderColor: 'rgba(255,255,255,0.6)',
      backgroundColor: 'rgba(255,255,255,0.1)',
      tension: 0.4,
      fill: true,
      pointRadius: 0,
      borderWidth: 2,
    }]
  },
  options: {
    responsive: true,
    plugins: { legend: { display: false }, tooltip: { enabled: false }},
    scales: {
      x: { display: false },
      y: { display: false }
    }
  }
});
```

# 5. Real-time Updates (Optional):
استخدم WebSocket من `core/websocket.py`:
```javascript
const socket = new WebSocket('ws://' + window.location.host + '/ws/dashboard/');
socket.onmessage = (e) => {
  const data = JSON.parse(e.data);
  updateChart(analysisChart, data.timeline);
  updateStats(data.stats);
};
```

# الـ Backend Helpers في `apps/analytics/views.py`:
```python
class DashboardDataView(LoginRequiredMixin, View):
    def get(self, request):
        org = request.user.organization
        return JsonResponse({
            'timeline': self.get_timeline_data(org),
            'risk_distribution': self.get_risk_data(org),
            'vendors': self.get_vendors_data(org),
        })
    
    def get_timeline_data(self, org, days=30):
        # SQL query لحساب الإحصائيات لآخر 30 يوم
        from django.db.models import Count, Q
        from django.db.models.functions import TruncDay
        
        data = Invoice.objects.filter(organization=org)\
            .annotate(day=TruncDay('created_at'))\
            .values('day')\
            .annotate(
                analyzed=Count('id'),
                risky=Count('id', filter=Q(risk_level__in=['high', 'critical']))
            ).order_by('day')[:days]
        
        return {
            'labels': [d['day'].strftime('%d %b') for d in data],
            'analyzed': [d['analyzed'] for d in data],
            'risky': [d['risky'] for d in data],
        }
```

أعطني:
1. ملف `static/js/dashboard-charts.js` كامل
2. تحديث على `apps/analytics/views.py`
3. URL endpoint للـ data API
4. التحديثات على dashboard/index.html لاستيراد الـ JS
```

---

## 🎯 Prompt 4.4 — صفحة Vendor/Organization Dashboard

```
في مشروع Tadgeeg AI، مجلد `templates/vendor_dashboard/` يحتوي على صفحات 
خاصة بلوحة المنظمة.

المطلوب: تحسين وحدة dashboard المنظمة:

# 1. الـ Layout الموحد:
- استخدم نفس الـ Sidebar من Prompt 4.2
- TopBar مع breadcrumbs
- محتوى مركزي

# 2. الصفحات المطلوبة في `templates/vendor_dashboard/`:

## index.html (الرئيسية):
- نفس layout dashboard الرئيسية
- لكن الإحصائيات خاصة بالمنظمة فقط

## files.html (المستندات):
شبكة 4 أعمدة من البطاقات لأنواع المستندات:
- الفواتير (Invoices) → /dashboard/invoices/
- كشوفات البنوك (Bank Statements) → /dashboard/bank-statements/
- إقرارات ضريبية (VAT Returns) → /dashboard/vat-returns/
- أوامر الشراء (POs) → /dashboard/purchase-orders/
- إيصالات المبيعات (Sales Receipts)
- الرواتب (Payroll)
- التقارير المالية (Financial Reports)
- الأصول الثابتة (Fixed Assets)

كل بطاقة:
- أيقونة كبيرة (Lucide)
- اسم النوع
- العدد الإجمالي
- آخر تحديث (time ago)
- زر "عرض" + زر "+ إضافة"

## team.html (الفريق):
- جدول أعضاء المنظمة
- زر "+ دعوة عضو جديد"
- الأدوار: Admin, Auditor, Reviewer, Viewer
- أيقونة Avatar + الاسم + البريد + الدور + آخر نشاط
- Actions: تعديل دور، إيقاف، حذف

## organization.html (إعدادات المنظمة):
Tabs:
- المعلومات العامة (الاسم، الشعار، الرقم الضريبي)
- الفوترة والاشتراك
- التكاملات (Webhooks, API keys)
- المحاسبة (إعدادات ZATCA)
- الإعدادات المتقدمة

## activity.html (سجل النشاط):
- timeline بكل العمليات
- فلتر بالنوع، المستخدم، التاريخ
- export بـ CSV

# 3. الـ Permissions:
```python
class VendorDashboardMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.organization:
            return redirect('select-organization')
        if not request.user.has_perm('view_dashboard', request.user.organization):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)
```

# 4. الـ Multi-tenant Filtering:
كل query يجب أن يفلتر بالـ organization:
```python
# ❌ خطأ
Invoice.objects.all()

# ✅ صح
Invoice.objects.filter(organization=request.user.organization)
```

أعطني:
1. تحديث على templates/vendor_dashboard/index.html
2. ملف files.html جديد
3. ملف team.html جديد
4. ملف organization.html جديد
5. ملف activity.html جديد
6. التحديثات على apps/vendor_dashboard/views.py
7. التحديثات على apps/vendor_dashboard/urls.py
```

---

## 🎯 Prompt 4.5 — Real-time Notifications System

```
في مشروع Tadgeeg AI، المنصة تحتاج نظام إشعارات فوري.

المطلوب:

# 1. Notification Model:
```python
# apps/notifications/models.py
class Notification(models.Model):
    class Type(models.TextChoices):
        INFO = 'info', _('Info')
        SUCCESS = 'success', _('Success')
        WARNING = 'warning', _('Warning')
        ERROR = 'error', _('Error')
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    type = models.CharField(max_length=20, choices=Type.choices)
    title = models.CharField(max_length=200)
    message = models.TextField()
    icon = models.CharField(max_length=50, blank=True)  # Lucide icon name
    link = models.URLField(blank=True)  # رابط للتفاصيل
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'is_read', '-created_at']),
        ]
```

# 2. WebSocket Consumer:
```python
# apps/notifications/consumers.py
import json
from channels.generic.websocket import AsyncWebsocketConsumer

class NotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        if self.scope['user'].is_anonymous:
            await self.close()
            return
        
        self.user_id = self.scope['user'].id
        self.group_name = f'notifications_{self.user_id}'
        
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
    
    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)
    
    async def notification_message(self, event):
        await self.send(text_data=json.dumps(event['data']))
```

# 3. Helper لإرسال الإشعارات:
```python
# apps/notifications/services.py
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

def send_notification(user, type, title, message, **kwargs):
    notification = Notification.objects.create(
        user=user,
        organization=user.organization,
        type=type,
        title=title,
        message=message,
        **kwargs
    )
    
    # Push via WebSocket
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f'notifications_{user.id}',
        {
            'type': 'notification_message',
            'data': {
                'id': str(notification.id),
                'type': notification.type,
                'title': notification.title,
                'message': notification.message,
                'icon': notification.icon,
                'link': notification.link,
                'created_at': notification.created_at.isoformat(),
            }
        }
    )
    
    return notification
```

# 4. Frontend Component (في base.html):
```html
<div x-data="notificationsState()" x-init="init()" class="notifications-container">
  <!-- Bell button -->
  <button @click="open = !open" class="notification-btn">
    <icon-bell />
    <span x-show="unreadCount > 0" x-text="unreadCount" class="badge"></span>
  </button>
  
  <!-- Dropdown -->
  <div x-show="open" @click.away="open = false" 
       x-transition class="notifications-dropdown">
    <div class="header">
      <h3>الإشعارات</h3>
      <button @click="markAllRead()">تعليم الكل كمقروء</button>
    </div>
    
    <div class="list" x-show="notifications.length > 0">
      <template x-for="n in notifications" :key="n.id">
        <a :href="n.link || '#'" 
           @click="markRead(n.id)"
           :class="n.is_read ? 'read' : 'unread'"
           class="notification-item">
          <div class="icon" :class="'icon-' + n.type">
            <i :data-lucide="n.icon || 'bell'"></i>
          </div>
          <div class="content">
            <div class="title" x-text="n.title"></div>
            <div class="message" x-text="n.message"></div>
            <div class="time" x-text="formatTime(n.created_at)"></div>
          </div>
        </a>
      </template>
    </div>
    
    <div x-show="notifications.length === 0" class="empty">
      <icon-bell-off />
      <p>لا توجد إشعارات</p>
    </div>
    
    <div class="footer">
      <a href="/notifications/">عرض الكل</a>
    </div>
  </div>
</div>

<!-- Toast for new notifications -->
<div id="notification-toast" class="toast"></div>

<script>
function notificationsState() {
  return {
    open: false,
    notifications: [],
    unreadCount: 0,
    socket: null,
    
    async init() {
      await this.loadNotifications();
      this.connectWebSocket();
    },
    
    async loadNotifications() {
      const res = await fetch('/api/v1/notifications/');
      const data = await res.json();
      this.notifications = data.results;
      this.unreadCount = data.unread_count;
    },
    
    connectWebSocket() {
      this.socket = new WebSocket(
        'ws://' + window.location.host + '/ws/notifications/'
      );
      this.socket.onmessage = (e) => {
        const notification = JSON.parse(e.data);
        this.notifications.unshift(notification);
        this.unreadCount++;
        this.showToast(notification);
        this.playSound();
      };
    },
    
    showToast(notification) {
      // Create and show toast
      const toast = document.getElementById('notification-toast');
      toast.innerHTML = `
        <div class="toast-icon icon-${notification.type}">
          <i data-lucide="${notification.icon || 'bell'}"></i>
        </div>
        <div class="toast-content">
          <strong>${notification.title}</strong>
          <p>${notification.message}</p>
        </div>
      `;
      toast.classList.add('show');
      lucide.createIcons();
      
      setTimeout(() => toast.classList.remove('show'), 5000);
    },
    
    playSound() {
      const audio = new Audio('/static/sounds/notification.mp3');
      audio.volume = 0.3;
      audio.play().catch(() => {});
    },
    
    async markRead(id) {
      await fetch(`/api/v1/notifications/${id}/read/`, { method: 'POST' });
      const n = this.notifications.find(n => n.id === id);
      if (n && !n.is_read) {
        n.is_read = true;
        this.unreadCount--;
      }
    },
    
    async markAllRead() {
      await fetch('/api/v1/notifications/read-all/', { method: 'POST' });
      this.notifications.forEach(n => n.is_read = true);
      this.unreadCount = 0;
    },
    
    formatTime(date) {
      const d = new Date(date);
      const now = new Date();
      const diff = (now - d) / 1000;
      if (diff < 60) return 'الآن';
      if (diff < 3600) return Math.floor(diff/60) + ' د';
      if (diff < 86400) return Math.floor(diff/3600) + ' س';
      return Math.floor(diff/86400) + ' ي';
    }
  }
}
</script>
```

# 5. الـ API Endpoints:
```python
# apps/notifications/views.py
class NotificationListAPI(generics.ListAPIView):
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user)[:50]
    
    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()
        unread_count = qs.filter(is_read=False).count()
        return Response({
            'results': self.get_serializer(qs, many=True).data,
            'unread_count': unread_count,
        })
```

# 6. أمثلة على استخدام الإشعارات:
```python
# عند رفع فاتورة:
send_notification(
    user=invoice.uploaded_by,
    type='success',
    title='تم تحليل الفاتورة',
    message=f'تم تحليل {invoice.number} بنجاح',
    icon='check-circle',
    link=f'/invoices/{invoice.id}/'
)

# عند اكتشاف مخاطر:
send_notification(
    user=admin,
    type='warning',
    title='⚠️ مخاطر مكتشفة',
    message=f'فاتورة {invoice.number} تحتوي على {risk_count} مخاطر',
    icon='alert-triangle',
    link=f'/invoices/{invoice.id}/risks/'
)
```

أعطني:
1. الـ Model الكامل
2. الـ Consumer
3. الـ Service
4. الـ Frontend Component (HTML + JS + CSS)
5. الـ API Views + URLs
6. الـ Migrations
7. تحديث على routing.py لإضافة WebSocket
```

---

## ✅ Checklist بعد تطبيق هذا القسم

- [ ] `templates/dashboard/index.html` بهوية تدقيق
- [ ] الـ Sidebar الموحدة في كل صفحات الـ dashboard
- [ ] الـ Charts تعمل بـ Chart.js وألوان تدقيق
- [ ] الـ Stat cards مع gradients صحيحة
- [ ] صفحات `vendor_dashboard/` محدّثة
- [ ] Notification system يعمل (real-time)
- [ ] الـ Charts responsive
- [ ] الـ Backend يفلتر بالـ organization (multi-tenant)
- [ ] Tests في `tests/test_dashboard_and_reports.py` تنجح
- [ ] لا توجد ألوان بنفسجية أو وردية

---

**📌 بعد إكمال هذا القسم، انتقل لـ `05-INVOICES.md`**
