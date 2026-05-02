# 📁 06 — إدارة المستندات (Documents)

> Prompts لتطوير `templates/documents/*` و `apps/documents/`

أنواع المستندات في النظام:
- Bank Statements (كشوفات البنوك)
- VAT Returns (إقرارات ضريبية)
- Payroll (الرواتب)
- Purchase Orders (أوامر الشراء)
- Sales Receipts (إيصالات المبيعات)
- Fixed Assets (الأصول الثابتة)
- Expense Reports (تقارير المصروفات)

---

## 🎯 Prompt 6.1 — صفحة المستندات الرئيسية

```
في مشروع Tadgeeg AI، ملف `templates/documents/index.html`:

المطلوب: صفحة hub للمستندات بهوية تدقيق.

# الهيكل:

## Header:
- "إدارة المستندات"
- breadcrumb + زر "+ مستند جديد"
- زر "تصدير الكل"

## Quick Stats (4 cards):
- إجمالي المستندات (مع +X هذا الشهر)
- معالجة جارية
- بحاجة مراجعة
- مكتملة

## Document Type Cards (شبكة 4×2):
كل بطاقة:
- أيقونة كبيرة بلون مميز
- اسم النوع (عربي + English)
- العدد الإجمالي
- "آخر تحديث: قبل X"
- زر "عرض" + "+ إضافة"

البطاقات:
1. 🏦 كشوفات البنوك → bank_statements.html
2. 📊 إقرارات ضريبية → vat_returns.html
3. 💰 الرواتب → payroll.html
4. 📋 أوامر الشراء → purchase_orders.html
5. 🧾 إيصالات المبيعات → sales_receipts.html
6. 🏢 الأصول الثابتة → fixed_assets.html
7. 💸 تقارير المصروفات → expense_reports.html
8. 📁 مستندات أخرى

## Recent Documents Table:
- آخر 10 مستندات من جميع الأنواع
- النوع، الاسم، التاريخ، الحالة، Actions

# Backend:
```python
class DocumentsHubView(LoginRequiredMixin, TemplateView):
    template_name = 'documents/index.html'
    
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        org = self.request.user.organization
        ctx['stats'] = {
            'bank_statements': BankStatement.objects.filter(organization=org).count(),
            'vat_returns': VATReturn.objects.filter(organization=org).count(),
            'payroll': PayrollDocument.objects.filter(organization=org).count(),
            'purchase_orders': PurchaseOrder.objects.filter(organization=org).count(),
            'sales_receipts': SalesReceipt.objects.filter(organization=org).count(),
            'fixed_assets': FixedAsset.objects.filter(organization=org).count(),
            'expense_reports': ExpenseReport.objects.filter(organization=org).count(),
        }
        ctx['recent'] = self.get_recent_documents(org)
        return ctx
```

أرفق الكود الحالي.
أعطني الـ template الكامل + view.
```

---

## 🎯 Prompt 6.2 — صفحة كشوفات البنوك

```
في `templates/documents/bank_statements.html`:

# المطلوب:
- جدول كشوفات البنوك
- أعمدة: # الرقم، البنك، رقم الحساب (مخفي جزئياً)، الفترة، الرصيد، عدد المعاملات، الحالة
- فلاتر: البنك، الفترة الزمنية، الحالة
- زر "+ كشف جديد"
- صفحة upload خاصة (PDF/Excel)
- تحليل تلقائي: كشف المعاملات المشبوهة، التحقق من الرصيد

# الـ Model:
```python
class BankStatement(SoftDeleteModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    bank_name = models.CharField(max_length=100)
    account_number = models.CharField(max_length=50)
    period_start = models.DateField()
    period_end = models.DateField()
    opening_balance = models.DecimalField(max_digits=15, decimal_places=2)
    closing_balance = models.DecimalField(max_digits=15, decimal_places=2)
    file = models.FileField(upload_to='bank_statements/%Y/%m/')
    transactions_count = models.IntegerField(default=0)
    status = models.CharField(max_length=20, default='pending')
    
    class Meta:
        ordering = ['-period_end']
```

# قواعد التدقيق:
1. الرصيد الافتتاحي يطابق الإغلاقي للفترة السابقة
2. عدم وجود معاملات مكررة
3. كشف المبالغ غير المعتادة (Z-score > 3)
4. التحقق من الجمع الحسابي
5. كشف معاملات شركاء مشبوهين

أعطني template + model + view + URL + audit rules.
```

---

## 🎯 Prompt 6.3 — صفحة الإقرارات الضريبية (VAT Returns)

```
في `templates/documents/vat_returns.html`:

# المطلوب:
- صفحة لإدارة إقرارات VAT الفصلية
- متوافقة مع ZATCA Phase 2
- حسابات تلقائية للضريبة المستحقة

# الحقول:
- الفترة (Q1, Q2, Q3, Q4)
- إجمالي المبيعات الخاضعة (Standard Rated)
- المبيعات الصفرية (Zero Rated)
- المبيعات المعفاة (Exempt)
- إجمالي المشتريات الخاضعة
- VAT على المبيعات (Output Tax)
- VAT على المشتريات (Input Tax)
- VAT المستحق (Net Tax)
- الحالة (Draft/Submitted/Accepted)

# قواعد التدقيق:
1. VAT = Sales × 0.15 (مع tolerance)
2. مجموع الفواتير في الفترة يطابق الإقرار
3. لا توجد فواتير ZATCA-flagged
4. التواريخ ضمن الفترة المحددة

# تصدير:
- XML لـ ZATCA submission
- PDF للأرشيف
- Excel للتحليل

أعطني template + model + tasks الـ Celery + ZATCA integration.
```

---

## 🎯 Prompt 6.4 — صفحة الرواتب (Payroll)

```
في `templates/documents/payroll.html`:

# المطلوب:
- جدول الموظفين والرواتب الشهرية
- استخراج تلقائي من PDF
- التحقق من GOSI (السعودية) أو مكافآت نهاية الخدمة
- كشف:
  • رواتب مكررة
  • زيادات غير مبررة
  • موظفين أشباح (لا يوجد سجل سابق)
  • تجاوز الحد الأعلى للراتب

# Sub-pages:
- /payroll/ - قائمة الفترات
- /payroll/<id>/ - تفاصيل الفترة (جدول الموظفين)
- /payroll/<id>/employee/<eid>/ - تفاصيل موظف

# Models:
```python
class PayrollPeriod(SoftDeleteModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    month = models.IntegerField()
    year = models.IntegerField()
    total_employees = models.IntegerField()
    total_gross = models.DecimalField(max_digits=15, decimal_places=2)
    total_deductions = models.DecimalField(max_digits=15, decimal_places=2)
    total_net = models.DecimalField(max_digits=15, decimal_places=2)
    file = models.FileField(upload_to='payroll/')

class PayrollEntry(models.Model):
    period = models.ForeignKey(PayrollPeriod, on_delete=models.CASCADE)
    employee_id = models.CharField(max_length=50)
    employee_name = models.CharField(max_length=200)
    basic_salary = models.DecimalField(max_digits=10, decimal_places=2)
    allowances = models.DecimalField(max_digits=10, decimal_places=2)
    deductions = models.DecimalField(max_digits=10, decimal_places=2)
    gosi = models.DecimalField(max_digits=10, decimal_places=2)
    net_salary = models.DecimalField(max_digits=10, decimal_places=2)
```

أعطني الـ models + templates + audit rules.
```

---

## 🎯 Prompt 6.5 — أوامر الشراء (Purchase Orders)

```
في `templates/documents/purchase_orders.html`:

# المطلوب:
صفحة PO management مع:
- ربط الـ PO بالفواتير المقابلة (3-way match)
- التحقق من الكميات والأسعار
- حالات: Draft, Sent, Confirmed, Received, Closed

# 3-Way Match Rule:
PO + GRN (Good Receipt Note) + Invoice يجب أن تتطابق في:
- الكمية
- السعر الإجمالي
- المورد
- المنتجات

# Sub-pages:
- /purchase-orders/ - قائمة
- /purchase-orders/<id>/ - تفاصيل
- /purchase-orders/<id>/match/ - 3-way match view

# Match View:
- 3 أعمدة: PO | GRN | Invoice
- تظليل الاختلافات بالأحمر
- summary: ✓ Match أو ⚠️ Mismatch
- حساب الـ variance

أعطني templates + models + matching algorithm.
```

---

## ✅ Checklist

- [ ] `documents/index.html` hub محدّث
- [ ] صفحات لكل نوع مستند
- [ ] Models مع SoftDeleteModel
- [ ] Audit rules لكل نوع
- [ ] 3-way match يعمل
- [ ] ZATCA XML export يعمل
- [ ] Tests في `test_document_models_and_rules.py` تنجح

---

**📌 انتقل لـ `07-REPORTS.md`**
