# حاجب `invoice_id` — تشخيص · 2026-08-13 · `claude @ 6d3d6f5`

> **قياس خالص.** صفر تعديل شيفرة. `dd46332f…` لم يتغيّر.
> والمخرَج مقارنة بدائل — **الاختيار قرار CTO، لا ترجيح مني.**

---

## §١ — لماذا يشترط `invoice_id`؟

`apps/rule_engine/services/compatibility/legacy_audit_adapter.py:73-99`،
اقتباسًا لا وصفًا:

```python
def evaluate(self, document: dict, invoice_id=None, context: Optional[dict] = None):
    if not invoice_id:
        raise ValueError("LegacyAuditEngineAdapter.evaluate() requires invoice_id")
    if not self.organization_id:
        raise ValueError("LegacyAuditEngineAdapter requires organization_id")

    from apps.rule_engine.pipeline.v2.compat import run_audit_compat
    audit_run = run_audit_compat(
        document_id=str(invoice_id),
        document_type="sales_invoice",
        organization_id=self.organization_id,
        triggered_by="legacy_adapter",
    )
    return AuditRunResult.from_audit_run(audit_run)
```

**ثلاث حقائق من السطور نفسها:**

1. 🔴 **`document` يُستقبَل ولا يُستعمل.** الحمولة التي يبني المسار كامل
   مرحلتيه الأولى والثانية لأجلها — تُهمَل. المعامل الوحيد الذي يعبر هو
   `invoice_id`.

2. **`invoice_id` ليس معرّف مستند — هو مفتاح بحث.** يُمرَّر
   `document_id=str(invoice_id)` إلى `run_audit_compat`، ومنه إلى
   `AuditPipelineV2.run` → `NormalizerFactory.get(document_type)` →
   والمُطبِّع يفعل حرفيًّا:

   ```python
   # apps/rule_engine/normalizers/invoice_normalizer.py:12-16
   inv = Invoice.objects.select_related("organization", "approved_by").get(
       id=document_id,
       organization_id=organization_id,
   )
   ```

   ⇒ **`document_id` مفتاح السجل المُطبوع، و`document_type` يختار أي
   جدول يُبحَث فيه.** الشرط ليس تعسّفًا: بلا مفتاح لا يوجد سجل، وبلا سجل
   لا يوجد ما يُدقَّق.

3. **`document_type="sales_invoice"` مثبَّت بلا تعليق يفسّره.** والجسر
   يحمل ثلاثة محوّلات أخرى تنادي `run_audit_compat` بأنواع أخرى — فالتثبيت
   خاصّ بهذا المحوّل لأنه كُتب لمستدعٍ واحد يتعامل مع فواتير.

**وهل يعمل بلا الاثنين لو مُرِّر معرّف مستند ونوعه؟** نعم — لا شيء آخر في
`evaluate` يحتاج `invoice_id`. الجسم كله ثلاثة أسطر تمرير.

---

## §٢ — من يعتمد على الشرط؟ (مسح `ast`)

| المستدعي | يمرّر `invoice_id`؟ | ما يمرّره |
|---|---|---|
| **`apps/audit/tasks.py:116-119`** | ✅ | `invoice_id=doc.pk` حيث `doc = ar.document` |
| `tests/test_documents_path_parity.py:75,406` | ❌ | يُثبّتان رفع `ValueError` |
| `tests/test_documents_path_parity.py:410` | ✅ | يُثبت أن الرفض يزول بتمريره |
| `core/services/pipeline.py:223` | ❌ | **الحاجب** — مسار المستندات |
| `apps/invoices/services/processor.py:417` | — | ينادي `run_audit` القديمة لا المحوّل |

**مستدعٍ إنتاجي واحد للمحوّل.** ⇒ توسيع التوقيع رخيص من حيث عدد المواقع.

### 🔴 والمستدعي الوحيد الذي يُرضي الشرط لا يُرضي معناه

`apps/audit/tasks.py:117` يمرّر `doc.pk` — و`doc` هو `DocumentAnalysisResult.document`،
أي **مفتاح `Document`**. والمُطبِّع يبحث به في جدول `Invoice`. قياسًا:

```
Document.pk عيّنة        : 003d215a-a481-4a08-a5bc-8bfabe050704
Invoice بهذا المفتاح      : False
تقاطع أول 500 مفتاح       : 0
```

⇒ `Invoice.DoesNotExist` ⇒ المُطبِّع **لا يرفع**، بل يسجّل تحذيرًا ويُعيد
`NormalizedDocument` فارغًا (سطور 18-24). فالمهمّة تُنتج `AuditRun` على
مستند **فارغ**، وتحسبها تدقيقًا.

**هذا عطل يعمل اليوم على مسار مستقلّ عن الخطوة ٤** — وهو نفس تعارض
فضاءات المعرّفات (الانحراف 51)، في موضع ثالث.

---

## §٣ — ما يملكه مسار المستندات

| | |
|---|---|
| المعرّف الذي يملكه | **مفتاح `Document`** — `run_full_pipeline(document_id)` ثم `Document.objects.get(pk=…)` |
| النوع | `analysis.to_dict()["document_type"]` من المُصنِّف — **من مفردات الثمانية** |
| المنظمة | ✅ `doc.organization_id`، ويُمرَّر إلى المحوّل أصلًا |
| ما يقرؤه من التقرير | الأحد عشر حقلًا (`docs/STEP_4_GATE_MEASUREMENT.md` §٥) |

### 🔴 وهل يملك مفتاح السجل المُطبوع؟ — **يملك طريقًا إليه**

`Document` يحمل **22 علاقة عكسية one-to-one** إلى النماذج المطبوعة:

```
purchaseorder · bankstatement · payrollsheet · expensereport · vatreturn
fixedasset · salesreceipt · goodsreceiptnote · paymentvoucher · salesorder
quotation · proformainvoice · receiptvoucher · cashvoucher · generalledger
ledger · contract · supplierstatement · customerstatement · journalentry
(+ extracted_data · analysis_result وهما ليسا نوعي مستند)
```

**399 من أول 400 مستند يملك واحدًا منها فعلًا:**
`FixedAsset` 313 · `SalesOrder` 12 · `Contract` 9 · `PurchaseOrder` 9 ·
`PaymentVoucher` 6 · `GoodsReceiptNote` 6 · `JournalEntry` 6 ·
`ReceiptVoucher` 6 · `SupplierStatement` 5 · `CustomerStatement` 4 ·
`Quotation` 4 · `PayrollSheet` 3 · `Ledger` 3 · `GeneralLedger` 3 ·
`CashVoucher` 3 · `ProformaInvoice` 3 · `BankStatement` 1 ·
`ExpenseReport` 1 · `VATReturn` 1 · `SalesReceipt` 1.

⇒ **الفجوة ليست معرّفًا مفقودًا. المعرّف موجود ولم يُوصَل.**

### ⚠️ لكن اشتقاق اسم النوع لا يكفي وحده

`MODEL_NAME → snake_case` يطابق **15 من 20** فقط:

| النموذج | `snake_case` | المُطبِّع المسجَّل |
|---|---|---|
| `ExpenseReport` | `expense_report` | **`expense`** |
| `GoodsReceiptNote` | `goods_receipt_note` | **`grn`** |
| `PaymentVoucher` | `payment_voucher` | **`payment`** |
| `PayrollSheet` | `payroll_sheet` | **`payroll`** |
| `VATReturn` | `v_a_t_return` 🔴 | **`tax_return`** |

و`sales_invoice` مُطبِّع **بلا نموذج مقابل في `documents`** — لأن
`Invoice` في تطبيق `invoices`، وهو الوحيد الذي لا يُبلَغ من `Document`.

⇒ أي بديل يحتاج **خريطة صريحة** لا اشتقاقًا. وخريطة يدوية هي الجذر الذي
نطارده — فيجب أن يحرسها اختبار يُقارنها بالسجل المسجَّل، لا أن تُكتب وتُنسى.

---

## §٤ — البدائل · بأربعة معايير

| | **أ. توسيع `evaluate`** | **ب. نقطة دخول جديدة** | **ج. نداء `run_audit_compat` مباشرةً** |
|---|---|---|---|
| **ما يتغيّر** | `legacy_audit_adapter.py:73-99`: يقبل `document_id` و`document_type`، و`invoice_id` يبقى اسمًا بديلًا | دالة جديدة في الجسر (`evaluate_document`) · `evaluate` لا تُمسّ | `pipeline.py:203,222-226` ينادي `run_audit_compat` · والمحوّل لا يُستعمل هنا |
| **من يتأثّر** | المستدعي الإنتاجي الواحد + 3 اختبارات تُثبّت `ValueError` | **لا أحد** — إضافة خالصة | `pipeline.py` وحده · والسطر 222+ **يتغيّر** |
| **مسار التراجع `AUDIT_ENGINE_VERSION`** | ✅ يبقى — الطريق نفسه عبر `run_audit_compat` | ✅ يبقى | ✅ يبقى |
| **🔴 يُبقي مسار الفواتير سليمًا بلا تغيير؟** | ⚠️ **لا تمامًا** — يمسّ الدالة التي يناديها | ✅ **نعم** — لا سطر مشترك | ✅ **نعم** — لا يمسّ الجسر |
| **ما يكسره** | 3 اختبارات تُثبّت الرفض تُعاد كتابتها. والأخطر: يُبقي `document_type` مثبَّتًا أو يُغيّره — وتغييره يمسّ سلوك `tasks.py` | لا شيء مقيس. والكلفة: طريقان في جسر غرضه توحيد الطرق | **العقد الذي بُني في الشحنة ١ لا يُستعمل** — و`AuditRunResult` بحقوله السبعة يصير بلا مستدعٍ على هذا المسار |
| **يحلّ فجوة السجل المُطبوع؟** | ❌ يحتاج الخريطة أيًّا كان | ❌ نفسه | ❌ نفسه |

**والثلاثة تشترك في شرط واحد لا مفرّ منه:** خريطة `Document` → (السجل
المُطبوع · اسم نوعه). بلاها يبقى الحاجب قائمًا مهما تغيّر التوقيع.

---

## §٥ — ما لم أستطع قياسه

* **أثر أي بديل على المُخرَج** — يحتاج تنفيذه، وهو خارج نطاق برمت قياس.
* **هل تُنتج `apps/audit/tasks.py` فعلًا `AuditRun` فارغًا اليوم؟** استدللتُ
  عليه من الشيفرة والمفاتيح (صفر تقاطع)، ولم أُشغّل المهمّة — تشغيلها يكتب
  صفوفًا ويستدعي Celery.
* **معدّل تغطية السجلات المُطبوعة على الإنتاج** — قِسته على أول 400 مستند
  في dev (399/400)، وكوربوس dev مثبَت أنه غير ممثِّل
  (`docs/CONFIDENCE_FORMULA_MEASUREMENT.md` §١).

---

## §٦ — بند يستحق شحنته الخاصة

`apps/audit/tasks.py:117` يمرّر مفتاح `Document` ليُبحَث به في `Invoice`،
فيُنتج تدقيقًا على مستند فارغ. **هذا عطل يعمل اليوم**، ومستقلّ تمامًا عن
الخطوة ٤، ويقع في مسار مهمّة مجدولة لا يراها أحد.
