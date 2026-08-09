# 📈 07 — التقارير (Reports)

> Prompts لتطوير `templates/reports/*` و `apps/reports/`

---

## 🎯 Prompt 7.1 — صفحة التقارير الرئيسية

```
في مشروع Tadgeeg AI، ملف `templates/reports/index.html`:

المطلوب: صفحة hub للتقارير بهوية تدقيق.

# الهيكل:

## Header:
- "التقارير والتحليلات"
- زر "+ تقرير جديد"

## Quick Reports Grid (شبكة 3×3):
بطاقات للتقارير السريعة:
1. تقرير تنفيذي (Executive Report)
2. تقرير الفواتير (Invoice Audit)
3. تقرير الامتثال (Compliance)
4. تقرير المخاطر (Risk Assessment)
5. تقرير الاحتيال (Fraud Detection)
6. ISA 700 Opinion
7. تدفقات نقدية (IAS 7)
8. تحليل البائعين (Vendor Analysis)
9. تقرير مخصص (Custom)

كل بطاقة:
- أيقونة + اسم
- وصف قصير
- زر "إنشاء"

## Recent Reports Table:
- آخر التقارير المنشأة
- النوع، التاريخ، الحجم، الحالة، Actions (View/Download/Share)

# Backend:
```python
class ReportsHubView(LoginRequiredMixin, TemplateView):
    template_name = 'reports/index.html'
    
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['recent_reports'] = Report.objects.filter(
            organization=self.request.user.organization
        ).order_by('-created_at')[:10]
        return ctx
```

أعطني template + view.
```

---

## 🎯 Prompt 7.2 — التقرير التنفيذي (Executive Report)

```
في `templates/reports/executive_report.html`:

# المطلوب:
تقرير تنفيذي شامل بصفحات متعددة:

## الصفحة 1: غلاف
- لوقو تدقيق كبير
- "التقرير التنفيذي للتدقيق المالي"
- اسم المنظمة + الفترة
- التاريخ
- الإصدار

## الصفحة 2: Executive Summary
- 4 KPI cards كبيرة
- Risk Score
- Compliance Score
- توصيات مختصرة

## الصفحة 3: تحليل الفواتير
- إجمالي الفواتير المحلّلة
- توزيع المخاطر (chart)
- top 10 high-risk invoices
- top 10 vendors

## الصفحة 4: الامتثال
- ZATCA compliance rate
- VAT accuracy
- duplicate detection results

## الصفحة 5: كشف الاحتيال
- Fraud indicators detected
- Benford's Law analysis
- pattern anomalies

## الصفحة 6: التوصيات
- قائمة التوصيات بأولوياتها
- خطة العمل المقترحة
- الموارد المطلوبة

## الصفحة 7: الملاحق
- Methodology
- Audit trail
- Definitions

# طباعة PDF:
```python
# apps/reports/services/pdf.py
from weasyprint import HTML, CSS

class ExecutiveReportPDF:
    def __init__(self, organization, period):
        self.org = organization
        self.period = period
    
    def generate(self):
        context = self.get_context()
        html_content = render_to_string('reports/executive_report_pdf.html', context)
        css = CSS(string=self.get_print_css())
        
        pdf = HTML(string=html_content).write_pdf(stylesheets=[css])
        return pdf
    
    def get_print_css(self):
        return """
        @page {
            size: A4;
            margin: 2cm;
            @top-center { content: "تدقيق - التقرير التنفيذي"; }
            @bottom-right { content: counter(page) " / " counter(pages); }
        }
        body { font-family: 'Tajawal', sans-serif; direction: rtl; }
        h1, h2, h3 { font-family: 'Cairo', sans-serif; color: #003366; }
        .accent { color: #10B981; }
        """
```

# Print-friendly CSS:
- A4 size
- print margins
- page breaks بين الأقسام
- rtl support

أعطني الـ template + PDF service + view.
```

---

## 🎯 Prompt 7.3 — تقرير تدقيق الفواتير

```
في `templates/reports/invoice_audit_report.html`:

# المطلوب:
تقرير شامل لتدقيق الفواتير:

## المحتوى:
1. **Header**:
   - معلومات المنظمة
   - الفترة
   - التاريخ والتوقيع

2. **Executive Summary**:
   - إحصائيات: 1,247 فاتورة محلّلة
   - 98.3% دقة
   - 24 مخاطر

3. **التحليل التفصيلي**:
   - توزيع المخاطر (chart)
   - top vendors
   - top high-risk invoices
   - patterns detected

4. **30 Audit Rules Summary**:
   - جدول لكل قاعدة:
     • نسبة النجاح
     • عدد الفواتير الفاشلة
     • مستوى الخطورة
   - color-coded

5. **Anomalies Section**:
   - فواتير مكررة محتملة
   - مبالغ شاذة (Z-score)
   - فواتير بدون VAT
   - patterns مشبوهة

6. **Recommendations**:
   - أولوية عالية
   - أولوية متوسطة
   - أولوية منخفضة

7. **Appendix**:
   - Methodology
   - Sample size
   - Tools used

# Render to PDF:
استخدم weasyprint مع CSS مخصص للطباعة.

# الـ View:
```python
class InvoiceAuditReportView(LoginRequiredMixin, View):
    def get(self, request):
        format = request.GET.get('format', 'html')
        date_from = request.GET.get('date_from')
        date_to = request.GET.get('date_to')
        
        context = self.get_context(date_from, date_to)
        
        if format == 'pdf':
            pdf = render_to_pdf('reports/invoice_audit_report_pdf.html', context)
            response = HttpResponse(pdf, content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="invoice_audit_{date_from}_{date_to}.pdf"'
            return response
        elif format == 'excel':
            return generate_excel(context)
        else:
            return render(request, 'reports/invoice_audit_report.html', context)
```

أعطني الـ templates (HTML + PDF) + view + الـ data calculations.
```

---

## 🎯 Prompt 7.4 — ISA 700 Opinion Report

```
في `apps/reports/`، أحتاج تقرير ISA 700:

# المطلوب:
ISA 700 = المعيار الدولي للتدقيق رقم 700 (تكوين رأي وإصداره عن البيانات المالية)

# الأنواع:
1. **Unqualified Opinion** (رأي غير متحفظ): البيانات صحيحة بالكامل
2. **Qualified Opinion** (رأي متحفظ): توجد مخالفات محدودة
3. **Adverse Opinion** (رأي معاكس): البيانات لا تعكس الواقع
4. **Disclaimer** (إخلاء مسؤولية): لم نستطع الحكم

# المنطق:
```python
def determine_opinion(audit_session):
    failed_critical_rules = audit_session.get_failed_critical_rules()
    failed_high_rules = audit_session.get_failed_high_rules()
    accuracy_rate = audit_session.accuracy_rate
    
    if failed_critical_rules > 0:
        return 'adverse'
    elif failed_high_rules > 5 or accuracy_rate < 70:
        return 'disclaimer'
    elif failed_high_rules > 0 or accuracy_rate < 95:
        return 'qualified'
    else:
        return 'unqualified'
```

# الـ Template:
- Heading رسمي
- "نحن، فريق تدقيق، قمنا بتدقيق..."
- المعايير المتبعة (ISA, IFRS, Local GAAP)
- النطاق
- المسؤوليات
- الرأي (Bold + Highlighted)
- التوقيع الرقمي
- التاريخ

# Digital Signature:
استخدم cryptography library:
```python
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

def sign_report(content_bytes, private_key):
    signature = private_key.sign(
        content_bytes,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256()
    )
    return signature
```

أعطني template + opinion logic + signature service.
انظر `tests/test_isa700_opinion.py` للتوقعات الموجودة.
```

---

## 🎯 Prompt 7.5 — تخصيص التقارير وSchedule

```
في مشروع Tadgeeg AI، أحتاج:

# 1. Custom Report Builder:
صفحة `templates/reports/builder.html`:
- اختيار نوع البيانات
- اختيار الحقول (drag & drop)
- الفلاتر
- التجميع (Group by)
- نوع العرض (Table/Chart)
- معاينة فورية
- حفظ/تصدير

# 2. Scheduled Reports:
- إنشاء جدول لإرسال تقرير دوري
- تكرار: يومي/أسبوعي/شهري
- المستلمين (emails)
- الصيغة (PDF/Excel)
- تفعيل/إيقاف

# Model:
```python
class ScheduledReport(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    name = models.CharField(max_length=200)
    report_type = models.CharField(max_length=50)
    frequency = models.CharField(max_length=20)  # daily/weekly/monthly
    day_of_week = models.IntegerField(null=True)  # 0=Sunday
    day_of_month = models.IntegerField(null=True)
    time = models.TimeField()
    recipients = models.JSONField(default=list)  # list of emails
    format = models.CharField(max_length=10)  # pdf/excel
    is_active = models.BooleanField(default=True)
    last_run = models.DateTimeField(null=True)
    next_run = models.DateTimeField(null=True)
    config = models.JSONField(default=dict)  # filters, params
```

# Celery Beat Task:
```python
# apps/reports/tasks.py
@shared_task
def run_scheduled_reports():
    now = timezone.now()
    due = ScheduledReport.objects.filter(
        is_active=True,
        next_run__lte=now
    )
    
    for schedule in due:
        try:
            generate_and_send_report.delay(schedule.id)
            schedule.last_run = now
            schedule.next_run = calculate_next_run(schedule)
            schedule.save()
        except Exception as e:
            logger.error(f"Schedule {schedule.id} failed: {e}")

@shared_task
def generate_and_send_report(schedule_id):
    schedule = ScheduledReport.objects.get(id=schedule_id)
    # generate report
    # send email with attachment
    pass
```

# Celery Beat Schedule:
```python
# settings.py
CELERY_BEAT_SCHEDULE = {
    'run-scheduled-reports': {
        'task': 'apps.reports.tasks.run_scheduled_reports',
        'schedule': crontab(minute='*/15'),  # every 15 min
    },
}
```

أعطني template builder + scheduling system + tasks.
```

---

## ✅ Checklist

- [ ] صفحة hub للتقارير تعمل
- [ ] Executive Report PDF يطبع بـ weasyprint
- [ ] Invoice Audit Report يعمل
- [ ] ISA 700 Opinion logic مطبّق
- [ ] Custom report builder يعمل
- [ ] Scheduled reports تشتغل تلقائياً
- [ ] PDF بهوية تدقيق
- [ ] RTL في الـ PDFs

---

**📌 انتقل لـ `08-AUDIT-ENGINE.md`**
