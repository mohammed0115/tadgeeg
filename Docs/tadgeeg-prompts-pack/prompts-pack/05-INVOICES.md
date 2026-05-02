# 📄 05 — إدارة الفواتير (Invoices)

> Prompts لتطوير `templates/invoices/*` و `apps/invoices/`

---

## 🎯 Prompt 5.1 — قائمة الفواتير (Invoices List)

```
في مشروع Tadgeeg AI، ملف `templates/invoices/list.html`:

المطلوب: حدّث الصفحة بهوية تدقيق + ميزات متقدمة.

# الهيكل:

## Header:
- "الفواتير"
- breadcrumb: لوحة التحكم > الفواتير
- زر "+ رفع فاتورة جديدة" (#10B981)
- زر "تصدير CSV"

## Filters Bar (شريط فلاتر):
- Search input عريض (يبحث في رقم الفاتورة، اسم المورد)
- Date range picker (من - إلى)
- Status: dropdown (الكل، معلّق، محلّل، مرفوض، موافق عليه)
- Risk Level: dropdown (الكل، منخفض، متوسط، عالي، حرج)
- Vendor: searchable dropdown
- Amount Range: slider (مبلغ من - إلى)
- زر "إعادة تعيين الفلاتر"

## Status Tabs:
شريط tabs مع counters:
- الكل (1,247)
- معلّق (45)
- محلّل (1,180)
- موافق عليه (980)
- مرفوض (22)

## View Toggle:
أزرار تبديل: Table | Grid

## Table View:
أعمدة:
- ☐ Checkbox (للـ bulk actions)
- # الرقم
- المستند (أيقونة الملف + الاسم + المورد)
- التاريخ
- المبلغ
- ضريبة VAT
- الإجمالي
- الحالة (badge)
- المخاطر (badge)
- Actions (عرض، تعديل، حذف)

## Bulk Actions Bar:
يظهر عند تحديد صفوف:
- "تم تحديد X فاتورة"
- أزرار: تصدير، تصنيف، حذف، إرسال للمراجعة

## Pagination:
- 25 / 50 / 100 لكل صفحة
- "عرض 1-25 من 1,247"
- أرقام الصفحات
- previous/next

# Backend في `apps/invoices/views.py`:
```python
class InvoiceListView(LoginRequiredMixin, ListView):
    model = Invoice
    template_name = 'invoices/list.html'
    paginate_by = 25
    context_object_name = 'invoices'
    
    def get_queryset(self):
        qs = Invoice.objects.filter(organization=self.request.user.organization)
        
        # Filters
        status = self.request.GET.get('status')
        if status: qs = qs.filter(status=status)
        
        risk = self.request.GET.get('risk_level')
        if risk: qs = qs.filter(risk_level=risk)
        
        search = self.request.GET.get('q')
        if search:
            qs = qs.filter(
                Q(invoice_number__icontains=search) |
                Q(vendor_name__icontains=search)
            )
        
        date_from = self.request.GET.get('date_from')
        date_to = self.request.GET.get('date_to')
        if date_from: qs = qs.filter(invoice_date__gte=date_from)
        if date_to: qs = qs.filter(invoice_date__lte=date_to)
        
        return qs.select_related('vendor', 'uploaded_by').order_by('-created_at')
```

أرفق `templates/invoices/list.html` الحالي.
أعطني الكود الكامل + التحديثات على views.py.
```

---

## 🎯 Prompt 5.2 — تفاصيل الفاتورة (Invoice Detail)

```
في مشروع Tadgeeg AI، ملف `templates/invoices/detail.html`:

المطلوب: صفحة تفاصيل احترافية للفاتورة:

# الهيكل:

## Top Banner:
- breadcrumb: الفواتير > رقم الفاتورة
- اسم الملف + أيقونة
- شارة الحالة الكبيرة (Approved/Pending/Rejected)
- شارة المخاطر
- أزرار: مشاركة، طباعة، تحميل PDF، اعتماد، رفض

## شبكة 4 Summary Cards:
- حالة الامتثال (متوافق/غير متوافق)
- دقة التحليل (98.5%)
- مستوى المخاطر (منخفض)
- إجمالي المبلغ (gradient #003366)

## Layout 2/3 + 1/3:

### العمود الرئيسي:
1. **البيانات المستخرجة**:
   - اسم المورد، VAT ID، التاريخ، رقم الفاتورة
   - المبلغ الصافي، الضريبة، الإجمالي
   - تنسيق grid مع labels واضحة

2. **30 قاعدة تدقيق**:
   - شبكة من البطاقات الصغيرة
   - كل قاعدة: ✓ نجحت / ⚠️ تحذير / ✗ فشلت
   - عند الضغط: modal بالتفاصيل
   - فلتر: الكل، نجحت، فشلت

3. **Audit Trail (سجل العمليات)**:
   - timeline عمودي
   - كل حدث: timestamp + المستخدم + الإجراء
   - ألوان مختلفة حسب نوع الإجراء

### العمود الجانبي:
1. **Fraud Detection**:
   - meter للـ score
   - قائمة الـ flags
   - زر "تشغيل تحليل إضافي"

2. **Total Card** (gradient):
   - المبلغ الكبير
   - تفاصيل: صافي + VAT

3. **التوصيات**:
   - قائمة مرقمة
   - أيقونات + نصوص

4. **Document Viewer**:
   - عرض PDF/صورة الفاتورة
   - zoom in/out
   - download

## Comments Section:
- إضافة تعليق
- thread of comments
- mentions (@username)

# Backend Context:
```python
class InvoiceDetailView(LoginRequiredMixin, DetailView):
    model = Invoice
    template_name = 'invoices/detail.html'
    context_object_name = 'invoice'
    
    def get_queryset(self):
        return Invoice.objects.filter(organization=self.request.user.organization)
    
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        invoice = self.object
        ctx.update({
            'audit_results': invoice.audit_results.all(),
            'audit_trail': invoice.audit_logs.order_by('-created_at'),
            'comments': invoice.comments.order_by('created_at'),
            'fraud_score': invoice.fraud_score,
            'compliance_checks': invoice.compliance_checks.all(),
        })
        return ctx
```

# JavaScript للـ document viewer:
استخدم PDF.js للـ PDFs أو img tag للصور.
أضف zoom/rotate controls.

أرفق `detail.html` و `detail_premium.html` الحاليين (لو موجودين).
أعطني الكود الكامل المحدّث.
```

---

## 🎯 Prompt 5.3 — صفحة رفع الفواتير (Upload)

```
في مشروع Tadgeeg AI، ملف `templates/invoices/upload.html`:

المطلوب: صفحة رفع احترافية مع:

# الميزات:
1. **Drag & Drop** zone كبيرة
2. **Multi-file** upload (حتى 50 ملف)
3. **Bulk progress** bar
4. **Per-file preview** (thumbnail + اسم + حجم + حالة)
5. **OCR Status** لكل ملف (pending → processing → done)
6. **AI Analysis Status** بعد OCR
7. **Real-time updates** بـ WebSocket
8. **Batch creation**: كل المرفوع يدخل في batch واحد

# الواجهة:

## Drop Zone:
- 200px ارتفاع
- خلفية متدرجة عند hover
- أيقونة Upload كبيرة
- "اسحب الملفات هنا أو اضغط للاختيار"
- "PDF, JPG, PNG, ZIP - حد أقصى 50 ميجا"

## File List:
لكل ملف بطاقة:
- thumbnail/icon
- اسم الملف + حجم
- progress bar
- status badge
- زر إلغاء/حذف

## Settings قبل الرفع:
- Audit Session: dropdown أو "إنشاء جلسة جديدة"
- Vendor: optional dropdown
- Notes: textarea
- Auto-approve إذا low risk: checkbox

## Statistics:
بعد الرفع:
- عدد الملفات الكلي
- نسبة النجاح
- متوسط دقة OCR
- الفواتير عالية المخاطر

# Backend في `apps/invoices/views.py`:
```python
class InvoiceUploadView(LoginRequiredMixin, View):
    template_name = 'invoices/upload.html'
    
    def post(self, request):
        files = request.FILES.getlist('files')
        batch = InvoiceBatch.objects.create(
            organization=request.user.organization,
            uploaded_by=request.user,
            total_files=len(files)
        )
        
        for file in files:
            invoice = Invoice.objects.create(
                batch=batch,
                organization=request.user.organization,
                uploaded_by=request.user,
                original_file=file,
                status='pending'
            )
            # Trigger Celery task
            process_invoice.delay(invoice.id)
        
        return JsonResponse({'batch_id': str(batch.id)})
```

# Celery Task:
```python
# apps/invoices/tasks.py
@shared_task(bind=True, max_retries=3)
def process_invoice(self, invoice_id):
    invoice = Invoice.objects.get(id=invoice_id)
    try:
        invoice.status = 'processing'
        invoice.save()
        
        # 1. OCR
        ocr_result = run_ocr(invoice.original_file.path)
        
        # 2. AI Extraction (GPT-4o)
        extracted = extract_with_gpt4o(ocr_result, invoice.original_file.path)
        
        # 3. Save extracted data
        invoice.vendor_name = extracted['vendor']
        invoice.invoice_number = extracted['number']
        invoice.amount = extracted['amount']
        # ...
        
        # 4. Run 30 audit rules
        run_audit_rules(invoice)
        
        # 5. Calculate fraud score
        invoice.fraud_score = calculate_fraud_score(invoice)
        
        # 6. Determine status
        invoice.status = 'validated'
        invoice.save()
        
        # 7. Send notification
        send_notification(
            invoice.uploaded_by,
            'success',
            'تم تحليل الفاتورة',
            f'تم تحليل {invoice.invoice_number}'
        )
    except Exception as e:
        invoice.status = 'error'
        invoice.error_message = str(e)
        invoice.save()
        raise self.retry(exc=e, countdown=60)
```

أرفق `templates/invoices/upload.html` الحالي.
أعطني الكود الكامل + Celery task + WebSocket updates.
```

---

## 🎯 Prompt 5.4 — صفحة Invoice Batches

```
في `templates/invoices/batches.html` و `batch_detail.html`:

# Batches List:
- جدول الـ batches
- # الرقم، التاريخ، الملفات (5/10)، المنشئ، الحالة
- progress bar للـ batch processing
- زر "عرض"

# Batch Detail:
- معلومات الـ batch
- progress overall
- جدول كل الـ invoices في الـ batch
- حالة كل invoice
- "إعادة معالجة الفاشلة"
- "تصدير نتائج Batch"

أعطني الـ templates الكاملة + views + الـ URLs.
```

---

## 🎯 Prompt 5.5 — Manual Review Workflow

```
في مشروع Tadgeeg AI، عندما الـ AI لا يستطيع الجزم بالفاتورة (confidence < 80%)، 
يجب إرسالها للمراجعة اليدوية.

المطلوب:

# 1. Manual Review Queue:
صفحة `templates/invoices/manual_review.html`:
- قائمة الفواتير التي تحتاج مراجعة
- إخفاء الـ low-confidence fields بـ ⚠️
- "X فواتير تحتاج مراجعتك"

# 2. Review Page:
- side-by-side: الصورة | البيانات المستخرجة
- المستخدم يصحح الحقول
- يحفظ → يعيد تشغيل audit rules
- زر "موافقة" أو "رفض" مع سبب

# 3. الـ API:
```python
class InvoiceManualReviewView(LoginRequiredMixin, UpdateView):
    model = Invoice
    fields = ['vendor_name', 'invoice_number', 'amount', 'vat_amount', ...]
    template_name = 'invoices/manual_review.html'
    
    def form_valid(self, form):
        invoice = form.save(commit=False)
        invoice.manually_reviewed = True
        invoice.reviewed_by = self.request.user
        invoice.reviewed_at = timezone.now()
        invoice.save()
        
        # Re-run audit
        from apps.invoices.tasks import re_audit_invoice
        re_audit_invoice.delay(invoice.id)
        
        messages.success(self.request, 'تم حفظ المراجعة')
        return redirect('invoice-detail', pk=invoice.pk)
```

أعطني الـ template + view + URL.
```

---

## ✅ Checklist بعد تطبيق هذا القسم

- [ ] `invoices/list.html` بفلاتر متقدمة
- [ ] `invoices/detail.html` يعرض 30 قاعدة و audit trail
- [ ] `invoices/upload.html` يدعم drag & drop وbatch
- [ ] Celery tasks لـ OCR وanalysis تعمل
- [ ] Manual review queue يعمل
- [ ] Tests في `tests/test_invoice_*.py` تنجح
- [ ] الـ multi-tenant filtering مطبّق
- [ ] لا توجد ألوان بنفسجية

---

**📌 بعد إكمال هذا القسم، انتقل لـ `06-DOCUMENTS.md`**
