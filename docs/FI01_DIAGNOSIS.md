# تشخيص FI-01 — «رفع واحد ينشئ فاتورتين»

> **النطاق:** جهاز تطوير محلي · قياس فقط · **صفر تعديل شيفرة أو قالب أو إعداد**.
> التغيير الوحيد في هذه الشحنة هو ملفات `docs/`.
> **لا يحتوي هذا التقرير أي إصلاح، ولا يقترح واحدًا.**

| البند | القيمة |
|---|---|
| الفرع المقاس | `claude` عند `9f76ebe` (`docs: record frontend backend integration check`) |
| رأس الشجرة عند بدء الجلسة | `5bacadb` — **متأخّر 9 commits**؛ قُدِّم بـ`git merge --ff-only` بتصريح صريح (§9) |
| تجميع الاختبارات | 4,035 عند `9f76ebe` · 4,044 عند `5bacadb` — كلاهما فوق حدّ 3,932 |
| قاعدة القياس | قاعدة اختبار SQLite في الذاكرة عبر pytest — **لم تُكتب أي صفوف في `db_runtime.sqlite3`** |
| المصدر المقارَن | `docs/FRONTEND_BACKEND_INTEGRATION_CHECK.md` §7 وأدلته، وقد رُصد FI-01 عند `12a5e96` (أب `9f76ebe`) |

---

## ١. حدود الإثبات

يثبت هذا التقرير **ما يفعله الخادم لكل طلب HTTP**. ولا يثبت ما يفعله المتصفح
قبل أن يُرسل الطلب.

هذا التمييز هو محور التشخيص كلّه: العيب المرصود يقع في المسافة بين
«ضغطة واحدة» و«طلبان»، والقياس أدناه يغطّي الشقّ الثاني فقط. الشقّ الأول —
لماذا أرسل المتصفح طلبين من ضغطة واحدة — **لم يُثبَت في هذه الجلسة**، وهو
مذكور في §10 كقرار مفتوح.

---

## ٢. تتبّع الاستدعاء الكامل

### ٢-أ · نقطتا رفع منفصلتان، لا واحدة

المهمة افترضت مسارًا واحدًا. الواقع نقطتان، والواجهة **لا تستخدم** نقطة الـAPI:

| النقطة | من يستدعيها | العرض |
|---|---|---|
| `POST /api/v1/invoices/upload/` | عملاء API واختبارات المستودع | `apps/invoices/views.py:312` |
| `POST /auditor/upload/` | **متصفح المستخدم** من `/invoices/upload/` | `apps/auditing/views/upload.py:45` |

الدليل على أن الواجهة تستخدم الثانية:
`templates/invoices/upload.html:308` — `fetch('/auditor/upload/', {method:'POST'})`،
وقبله `:301` — `for (const f of this.files) fd.append('file', f)` (إلحاق **مرّة واحدة** لكل ملف).

### ٢-ب · مسار الـAPI — من الطلب إلى `Invoice.objects.create`

```
POST /api/v1/invoices/upload/
└─ apps/invoices/urls.py:8            → InvoiceUploadView
   └─ apps/invoices/views.py:312      post()
      :317   uploaded_files = request.FILES.getlist("files")
      :329   InvoiceBatch.objects.create          ← دفعة واحدة للطلب
      :335   AuditSessionService.create_session   ← جلسة واحدة للطلب
      :352   for uploaded_file in uploaded_files:
      :356     ext not in ALLOWED_EXT           → continue
      :365     validate_uploaded_file(check_content=True)
      :373     ext == ".zip"                    → _process_zip → continue
      :381     ext in STRUCTURED_BULK_EXTENSIONS {.csv,.tsv,.json,.xlsx,.xls}
      :382       structured = _process_structured_upload(...)
      :383       if structured and structured.get("handled"):
      :395           continue                   ← ‼ داخل الشرط، لا خارجه
      :398     r = _process_single_file(...)    ← يُبلَغ فقط إذا كان الشرط كاذبًا
```

### ٢-ج · الفرع المُهيكَل

```
apps/invoices/services/processor.py:700  process_structured_upload
   :715   row_iter = iter_structured_records(uploaded_file, filename)
   :717   if row_iter is None:  return None      ← امتداد غير مُهيكَل فقط
   :730   for row_number, payload in row_iter:   → تقطيع إلى دفعات
   :737   process_structured_rows_chunk(...)     (أو :749 للبقية)
   :757   if total_rows == 0:   return None      ← ‼ مخرج السقوط
   :805   return {"handled": True, "mode": "async_chunked", ...}
   :817   return {"handled": True, "mode": "sync_chunked",  ...}

apps/invoices/services/processor.py:596  process_structured_rows_chunk
   :626   row_name = f"{base_name}_row{row_number}.json"
   :634   process_single_file(..., structured_payload=payload)
```

### ٢-د · المنشئ الفعلي للصف

```
apps/invoices/services/processor.py:181  process_single_file
   :224   file_hash = compute_file_hash(...)
   :227   if AuditSessionService.has_file_hash(audit_session, file_hash): raise
   :231   with transaction.atomic():
   :233     Invoice.objects.create(...)          ★ صف الفاتورة
   :250     Document.objects.create(...)         ★ جسر الفوترة
   :278     if structured_payload is not None:   → الحمولة الرسمية
   :296     else: DocumentEngine(use_ai=True).ingest(file_path)
```

### ٢-هـ · مسار الواجهة — وهو الذي رُصد عليه FI-01

```
templates/invoices/upload.html:196   <button @click="upload" type="button">
   :308   fetch('/auditor/upload/', {method:'POST', body: fd})
└─ finai_backend/urls.py:71 → apps/auditing/urls.py:23 → AuditDocumentUploadView
   └─ apps/auditing/views/upload.py:45   post()
      :70    uploaded_files = form.cleaned_data["file"]
      :82    for f in uploaded_files:
      :101     router.route(uploaded_file=f, ...)
      └─ core/services/upload_router.py:177  route → :339 _route_invoice
         :364    InvoiceBatch.objects.create        ‼ دفعة جديدة **لكل طلب**
         :370    AuditSessionService.create_session ‼ جلسة جديدة **لكل طلب**
         :380    _process_structured_upload(...)
         :389    if structured and structured.get("handled"):  → return
         :421    _process_single_file(...)          ← وإلا
         └─ processor.py:233  Invoice.objects.create
```

### ٢-و · 🔴 الفرضية مدحوضة على مستوى البنية

سؤال المهمة: «هل يوجد مسار يُنفّذ الاثنين لملف واحد؟» — **لا.**

لدالة `process_structured_upload` نوعان من العائد فقط:

- `None` — عند السطرين `717` و`757`، ولا يكون قد أُنشئ أي صف.
- `{"handled": True, ...}` — عند السطرين `805` و`817`.

**لا تُعيد الدالة أبدًا قاموسًا بـ`handled` كاذبة.** ولذلك فإن الشرط في
`views.py:383` و`upload_router.py:389` يقسم التنفيذ قسمة حادّة: إمّا الصفوف
المُهيكَلة، وإمّا الملف الكامل. `_process_single_file` في `views.py:398`
و`upload_router.py:421` **لا يُبلَغ إلا حين لم يُنشئ المسار المُهيكَل شيئًا.**

المسار الوحيد إلى `views.py:398` بعد امتداد مُهيكَل هو `total_rows == 0` — أي
صفر صفوف مُنشأة. فلا ازدواج، بل بديل.

---

## ٣. القياس

### ٣-أ · كيف يُعاد

القياس أُجري بملف pytest مؤقّت (`tests/test_zz_fi01_measure_tmp.py`)، **حُذف بعد
القياس ولم يُلتزَم**، ويستعمل تجهيزات `tests/conftest.py` القائمة
(`organization`, `admin_user`, `admin_client`, `web_client`). جوهره:

```python
def _counts(org):
    return {
        "Invoice":      Invoice.objects.filter(organization=org).count(),
        "Document":     Document.objects.filter(organization=org).count(),
        "AuditSession": AuditSession.objects.filter(organization=org).count(),
        "InvoiceBatch": InvoiceBatch.objects.filter(organization=org).count(),
    }

# مسار الـAPI
admin_client.post("/api/v1/invoices/upload/", {"files": [f]}, format="multipart")

# مسار الواجهة
web_client.force_login(admin_user)
web_client.post("/auditor/upload/",
                {"file": [f], "selected_doc_type": "invoice", "doc_language": "auto"},
                HTTP_X_REQUESTED_WITH="XMLHttpRequest")
```

كل حالة تبدأ من `BEFORE {'Invoice': 0, 'Document': 0, 'AuditSession': 0, 'InvoiceBatch': 0}`
— وهذا هو إثبات النظافة: لا بقايا بين الحالات، ولا كتابة في قاعدة التشغيل.
و`refresh_from_db()` يسبق قراءة كل حقل.

### ٣-ب · مسار الـAPI — `POST /api/v1/invoices/upload/`

| # | المُدخَل | Invoice | Document | AuditSession | InvoiceBatch | `original_filename` | `structured_payload` | `ocr_confidence` |
|---|---|---:|---:|---:|---:|---|---|---:|
| أ | CSV بصفّ واحد | **1** | 1 | 1 | 1 | `fi01_a_row2.json` | ✅ مُرِّر | 100.0 |
| ب | CSV بثلاثة صفوف | **3** | 3 | 1 | 1 | `_row2/_row3/_row4.json` | ✅ مُرِّر | 100.0 |
| ج | PDF | **1** | 1 | 1 | 1 | `fi01_c.pdf` | ❌ لم يُمرَّر | 0.0 |
| د | JSON كائن مفرد | **1** | 1 | 1 | 1 | `fi01_d.json` | ❌ لم يُمرَّر | 0.0 |

### ٣-ج · مسار الواجهة — `POST /auditor/upload/`

| # | المُدخَل | Invoice | Document | AuditSession | InvoiceBatch | `original_filename` | `structured_payload` |
|---|---|---:|---:|---:|---:|---|---|
| و-أ | CSV بصفّ واحد | **1** | 1 | 1 | 1 | `ui_a_row2.json` | ✅ مُرِّر |
| و-د | JSON كائن مفرد | **1** | 1 | 1 | 1 | `ui_d.json` | ❌ لم يُمرَّر |
| و-ج | PDF | **1** | 1 | 1 | 1 | `ui_c.pdf` | ❌ لم يُمرَّر |

**رفعٌ واحد ⇒ فاتورة واحدة لكل ملف، على المسارين معًا.**

### ٣-د · القيم المستخرَجة

| الحالة | `invoice_number` | `vendor_name` | `total` | `vat` | `subtotal` |
|---|---|---|---:|---:|---:|
| أ · و-أ (بحمولة مُهيكَلة) | `INV-001` | `Acme Supplier` | 1150.00 | 150.00 | 1000.00 |
| ب صف 1 | `INV-101` | `Alpha Supplier` | 1150.00 | 150.00 | 1000.00 |
| ب صف 2 | `INV-102` | `Beta Supplier` | 2300.00 | 300.00 | 2000.00 |
| ب صف 3 | `INV-103` | `Gamma Supplier` | 3450.00 | 450.00 | 3000.00 |
| ج · و-ج (PDF) | `INV-PDF-1` | `''` | 0.00 | 0.00 | 0.00 |
| د · و-د (JSON) | **`oice`** | **`_name": "Frontend Integration Supplier",`** | 0.00 | 0.00 | 0.00 |

### ٣-هـ · حالتا الازدواج

**(هـ) الملف نفسه مرّتين داخل طلب واحد** — `POST /api/v1/invoices/upload/`:

```
processed=1 failed=1
errors=[{"filename": "fi01_dup_row2.json",
         "error": "Duplicate file already processed in this audit session."}]
DELTA {'Invoice': 1, 'Document': 1, 'AuditSession': 1, 'InvoiceBatch': 1}
```

الحارس يعمل. صفٌّ واحد فقط.

**(و) الملف نفسه في طلبين متتاليين** — `POST /auditor/upload/` مرّتين:

```
request 1: HTTP 302 -> /invoices/2efce681-1ced-4ee8-b218-829b08e8b58e/
request 2: HTTP 302 -> /invoices/6c45cc7b-3f22-4185-a525-1653fdb8bdd0/

DELTA {'Invoice': 2, 'Document': 2, 'AuditSession': 2, 'InvoiceBatch': 2}

audit_session ids: ['680655ae-...', 'a71d85f5-...']     ← جلستان
batch ids        : ['37ec461f-...', 'ffdf8e24-...']     ← دفعتان
is_duplicate     : [False, True]
file_hash equal  : True
```

🔴 **هنا يُعاد إنتاج FI-01** — بطلبين، لا بطلب واحد.

---

## ٤. الحكم: أيّ مسار صحيح وأيّهما زائد

> **لا يوجد مسار زائد. ولا شيء يُحذف.**

المسار المُهيكَل (`processor.py:634` بـ`structured_payload`) والمسار غير المُهيكَل
(`views.py:398` · `upload_router.py:421`) **ليسا نسختين من عمل واحد**، بل فرعان
متكاملان يقسمهما شرطٌ واحد ولا يلتقيان. حذف أيّهما يُسقط صنفًا كاملًا من
المُدخَلات: حذف الأول يُلغي معالجة صفوف CSV/Excel، وحذف الثاني يُلغي معالجة
PDF والصور.

**FI-01 ليس ازدواج مسار. هو ازدواج طلب.**

والصورة المقاسة:

1. كل طلب إلى `/auditor/upload/` يُنشئ `InvoiceBatch` جديدة (`upload_router.py:364`)
   و`AuditSession` جديدة (`:370`).
2. حارس التكرار الوحيد على هذا المسار هو `has_file_hash`، **ونطاقه الجلسة**.
3. ⇒ طلبان = جلستان = الحارس أعمى بينهما بحكم البناء، لا بحكم عطل.

### أدلّة من أثر CTO نفسه تُرجّح الطلبين على الطلب الواحد

من `docs/frontend_integration_evidence/frontend_ui_invoice_multiplicity.json`:

| الصف | `created_at` | حدث `uploaded` | الفارق |
|---|---|---|---|
| 1 | `08:13:57.061305` | `08:13:58.530441` | 1.469 ث |
| 2 | `08:13:57.062105` | `08:14:00.055186` | 2.993 ث |

`record_invoice_event` مؤجَّل إلى `transaction.on_commit` (`processor.py:269`)، فحدث
`uploaded` يقع لحظة الإيداع. والصفّان أُنشئا بفارق 0.0008 ثانية بينما أُودعا بفارق
1.52 ثانية — أي أن **خطّي المعالجة تداخلا زمنيًا**.

حلقة `for` واحدة لا تُنتج هذا: فيها يُنشأ الصف الثاني **بعد** اكتمال خط الأول
وإيداعه. والقياس المباشر يؤكّده — طلبان متتاليان في (و) أعطيا فارق `created_at`
قدره **4.990030 ثانية**، لا 0.0008.

⇒ الطلبان في الأثر **متزامنان**، لا متتاليان داخل حلقة.

وشاهد ثانٍ: `file_hash` واحد للصفّين (`f8ac91a2…` في لقطة القاعدة) — أي أن كليهما
هو **الملف الكامل**، لا صفًّا مُهيكَلًا. ولو كان أحدهما صفًّا لاختلف الهاش،
لأن `processor.py:627` يُسلسل الحمولة من جديد.

### ما لم يُثبَت

**لم أُعِد إنتاج الضغطة الواحدة التي تُصدر طلبين.** أعدتُ إنتاج أثرها في الخادم
فقط. وفحص القالب لم يُظهر سببًا قاطعًا: الزر `type="button"` بربط `@click="upload"`
واحد (`templates/invoices/upload.html:196`)، وإلحاق الملف يجري مرّة واحدة (`:301`).
لكن `upload()` في `:276` يفتقر إلى حارس تزامن في مستهلّه — يفحص
`if (!this.files.length) return` ولا يفحص `this.uploading`. إخفاء الزر يتم بـ
`x-show` (`:172`)، وهو إخفاء عرضٍ لا يمنع ضغطة ثانية تسبق إعادة الرسم.
**هذا ترجيح غير مقاس، وأصنّفه فرضية مفتوحة لا نتيجة.**

---

## ٥. علاقة FI-05 بـFI-01

> 🔴 **عيبان منفصلان. FI-05 ليس عَرَضًا لـFI-01.**

فرضية المهمة كانت: «الاستخلاص المشوّه من النسخة التي لم تمرّ بـ`structured_payload`».
الشقّ الثاني من الفرضية **صحيح**، والشقّ الأول — أن ذلك عَرَض للازدواج — **خاطئ**.

### الآلية المقاسة

```
core/services/parsers/structured.py:160  _iter_json_records
   :168   if not isinstance(data, list):
   :169       return                     ← كائن JSON مفرد ⇒ صفر صفوف
        ↓
processor.py:757   if total_rows == 0: return None
        ↓
views.py:398 / upload_router.py:421      ← السقوط إلى الملف الكامل
        ↓
processor.py:296   DocumentEngine(use_ai=True).ingest(file_path)
        ↓
        استخلاص بالتعابير النمطية فوق نصّ JSON الخام
        ⇒ invoice_number = 'oice'   (شظية من مفتاح "invoice_number")
        ⇒ vendor_name    = '_name": "Frontend Integration Supplier",'
```

### الإثبات أنهما مستقلّان

- **تشوّه بلا ازدواج:** الحالتان (د) و(و-د) أنتجتا **فاتورة واحدة** لكلٍّ، وفيها
  `oice` و`0.00`. لو كان FI-05 عَرَضًا للازدواج لما ظهر مع صفٍّ واحد.
- **ازدواج بلا فارق:** الحالة (و) أنتجت صفّين **كلاهما مشوّه**، من المصدر نفسه.
  فالازدواج لا يُنتج التشوّه ولا يشفيه.
- **شاهد من أثر CTO:** لقطة القاعدة تسجّل `_extraction_method: 'json'` مع
  `_extraction_error: "'NoneType' object is not subscriptable"` — مستخلص JSON
  ارتفع باستثناء وسقط إلى الاحتياطي، والقيمة الصحيحة `UI-FRONTEND-2026-001`
  كانت حاضرة في `raw_text` طوال الوقت.

### تصحيح لتعليق قائم في الشيفرة

`processor.py:278-283` يصف فرع `structured_payload` بأنه علاج مشكلة `oice`.
وهو علاج صحيح **لصفوف CSV/Excel وقوائم JSON**. لكنه لا يُبلَغ أصلًا حين يكون
المُدخَل كائن JSON مفردًا، لأن `_iter_json_records` يرفضه قبل ذلك.
فالتعليق صادق في نطاقه، ويُقرأ أوسع ممّا يُغطّي.

---

## ٦. الأرقام التسعة

| # | السؤال | الفرضية | **المقاس** |
|---:|---|---|---|
| ١ | (أ) CSV بصفّ واحد ينشئ أكثر من فاتورة؟ | نعم | 🔴 **لا — واحدة** |
| ٢ | (ب) CSV بثلاثة صفوف ينشئ أكثر من ثلاث؟ | ربما 6 | 🔴 **لا — ثلاث** |
| ٣ | (ج) PDF ينشئ أكثر من واحدة؟ | — | **لا — واحدة** |
| ٤ | أيّ الصفّين يحمل الحقول الصحيحة؟ | — | **الذي مرّ بـ`structured_payload`** (`ocr_confidence=100.0`) |
| ٥ | صفّ `oice` و`0.00` — أيّ مسار أنشأه؟ | — | السقوط بلا حمولة: `views.py:398` · `upload_router.py:421` |
| ٦ | صفّ القيم الصحيحة — أيّ مسار؟ | — | `processor.py:634` بـ`structured_payload=payload` |
| ٧ | هل يُعدّ الصفّان تكرارًا لبعضهما؟ | — | **نعم** — الثاني `is_duplicate=True`، وتفشل `DUP-001`/`DUP-002`/`DUP-004` |
| ٨ | كم فاتورة تُحسب مقابل رفع واحد؟ | — | **1 لكل طلب.** ومع ازدواج الطلب: `Invoice 2 · Document 2 · AuditSession 2 · InvoiceBatch 2` |
| ٩ | كم تُخصم من الحصّة؟ | — | ⚠️ **لم يُقَس** — انظر أدناه |

### عن الرقم التاسع — وهو أثر تجاري، فلا أُجمّله

**لم أقس خصم حصّة، ولا أدّعي رقمًا.** المقاس أن كل طلب ينشئ صفّ `Document`
واحدًا (`processor.py:250`)، وأن التعليق في `processor.py:245-248` ينصّ صراحةً على
أن الفوترة مربوطة بـ`Document` لا بـ`Invoice`. وفي بيئة القياس ردّت بوابة الحصّة
بـ`Please choose a subscription plan before auditing invoices`، فلم يقع خصم
أُراقبه.

⇒ الأثر التجاري **مُرجَّح ببنية الربط، وغير مُثبَت بقياس**. وإثباته يحتاج
منظمة باشتراك فعّال تُقاس عدّاداتها قبل الرفع وبعده — وهو قياس لم تطلبه المهمة
ولم أُجره.

---

## ٧. أخطاء التشخيص السابق — ومنها أخطائي

### ٧-أ · ما أخطأ فيه توجيه المهمة

1. **«ملف CSV بصفّ واحد يُعالَج مرّتين — مرة كملف ومرة كصفّ.»**
   مدحوض. القياس: فاتورة واحدة (٣-ب). والبناء يمنعه (٢-و): `continue` في
   `views.py:395` داخل الشرط، و`process_structured_upload` لا تُعيد `handled`
   كاذبة أبدًا.

2. **«والفارق 0.0008 ثانية يُثبت أنهما من ضغطة واحدة.»**
   الفارق يُثبت **التزامن**، لا الضغطة الواحدة. وهو في الواقع دليل ضدّ فرضية
   الحلقة الواحدة، لأن الحلقة تُنتج فارقًا بحجم خط المعالجة — 4.99 ثانية في
   القياس المباشر.

3. **«§7: قبلتُ فرق الحمولة بندًا مُعدَّدًا بناءً على قياس على مسار واحد، وفحصك
   أثبت أن الإصلاح لا يعمل في مسار الواجهة.»**
   هذا التصحيح الذاتي **دقيق في نتيجته وغير دقيق في سببه**. إصلاح
   `structured_payload` يعمل في مسار الواجهة — قياس (و-أ) يُثبته: CSV مرفوع من
   `/auditor/upload/` أعطى `INV-001` و`1150.00` و`ocr_confidence=100.0`.
   ما لا يعمل ليس المسار، بل **صنف المُدخَل**: كائن JSON مفرد لا يبلغ الإصلاح
   أصلًا (§5). العينة التي فُحصت كانت `frontend_ui_invoice.json` — كائنًا مفردًا —
   فبدا قصور الصنف قصورًا في المسار.

4. **رقما السطرين في التوجيه (`views.py:398` و`processor.py:634`) صحيحان عند
   `9f76ebe`** — وهما اللذان أكّدا أن التوجيه كُتب على الرأس البعيد بينما كانت
   الشجرة المحلية متأخّرة تسعة commits (§9).

### ٧-ب · ما أخطأتُ فيه أنا

1. **توقّعت أن مسار الواجهة هو نفسه مسار الـAPI.** بنيتُ أول جولة قياس على
   `POST /api/v1/invoices/upload/` وحده، وكدت أختم بأن FI-01 غير موجود. وهو
   موجود — على `/auditor/upload/`. الفرق لم يظهر إلا بعد تتبّع القالب إلى
   `templates/invoices/upload.html:308`.

2. **قرأت أثر `frontend_ui_invoice_multiplicity.json` مبكّرًا كدليل على أن كلا
   الصفّين مشوّه، فرجّحت أن السؤال ٤ جوابه «لا أحدهما».** الجواب الصحيح أدقّ:
   في تلك العينة لا أحدهما، لأن كليهما من مسار السقوط — لكن السؤال عن الصفّين
   الناتجين عن مسارين مختلفين لا يقع أصلًا، إذ لا يجتمع مساران على ملف واحد.

---

## ٨. الحرّاس — لماذا لم يمنع أحدها

**بند مسجَّل. لا حارس يُكتب هنا؛ يُكتب مع الإصلاح.**

| الحارس | لماذا لم يكشف |
|---|---|
| `AuditSessionService.has_file_hash` — `apps/audit/services/audit_sessions.py:104-107` | يرشّح `session.invoices` — **نطاقه الجلسة**. و`upload_router.py:370` يُنشئ جلسة لكل طلب. فالحارس أعمى عبر الطلبات بحكم البناء. المقاس في (و): جلستان لطلبين. |
| `test_duplicate_file_inside_same_upload_is_blocked` — `tests/test_audit_sessions.py:225` | يرفع الملفين في **طلب واحد** (`:248-252`) ⇒ جلسة واحدة ⇒ الحارس يعمل والاختبار يمرّ **بحقّ**. لا يغطّي طلبين، ولا يدّعي ذلك. |
| `test_structured_row_is_forwarded_as_authoritative_payload` — `tests/test_structured_invoice_rows.py` | يستبدل `process_single_file` بـ`monkeypatch`. لا يُنشأ صف `Invoice` قط، ولا يُفحص أي عدّاد. |
| `apps/auditing/tests/test_upload.py` | يرقّع `DocumentUploadRouter` (`:95`) و`AuditProcessingService` (`:118`, `:168`). لا يبلغ الموجّه الحقيقي. |
| `tests/test_upload_pipeline.py` | يرسل فعلًا إلى `/auditor/upload/` (`:141`)، لكنه يرقّع `AuditProcessingService.process` ويتحقّق من `status_code in [200,201,302]` فقط. |

### الإجابة المباشرة على أسئلة §5 في المهمة

- **هل يوجد اختبار يرفع ملفًا من نقطة الرفع ويعدّ الفواتير؟**
  على مسار الواجهة: **لا. ولا واحد.** لا اختبار في المستودع يقرأ
  `Invoice.objects.count()` بعد `POST /auditor/upload/`.
- **لماذا مرّ `test_duplicate_file_inside_same_upload_is_blocked`؟**
  لأنه صحيح. يختبر الازدواج داخل الجلسة، وهو ممنوع فعلًا (قياس هـ).
- **هل كشف التكرار يعمل عبر مسارين متزامنين أصلًا؟**
  **لا.** ولا عبر طلبين متزامنين. الحارس داخل الجلسة، والجلسة داخل الطلب.
  وقواعد `DUP-001/002/004` تكشف الازدواج **بعد** وقوعه — تصفه ولا تمنعه.

⇒ الخلاصة: لم يفشل حارس. **لم يوجد حارس في هذا الموضع** — وهو فراغ تغطية لا عطل.

---

## ٩. الانحرافات

1. **الشجرة عند البدء كانت متأخّرة تسعة commits** — `5bacadb` مقابل `9f76ebe`،
   وأربعة منها تمسّ الملفين قيد التشخيص. و`structured_payload` كان **معدومًا**
   في `processor.py` المحلي (صفر تطابق). القياس هناك كان سيُنتج نفيًا كاذبًا.
   توقّفت وأبلغت، وتقدّمت بـ`git merge --ff-only origin/claude` **بتصريح صريح**.

2. **`docs/PLAN.md` غير متتبَّع** منذ 12 أغسطس. لم يُمسّ ولم يُدرَج في أي commit،
   بقرار صريح.

3. **قِست على قاعدة اختبار، لا على `db_runtime.sqlite3`.** المهمة طلبت التنظيف
   وإثبات عودة العدّادات؛ عزل pytest يحقّقهما بالبناء (كل حالة تبدأ من أصفار).
   **الأثر:** لم أقس على بيانات التشغيل، ولذلك لا أدّعي شيئًا عن صفوف قائمة فيها.

4. **الفرضية المركزية للمهمة مدحوضة** (§2-و، §6). أبلغت ولم أُصلح.

5. **فرضية §3 في المهمة مدحوضة جزئيًا** — الاستخلاص المشوّه سببه فعلًا غياب
   `structured_payload`، لكن FI-05 عيب مستقلّ لا عَرَض (§5).

6. **مفاتيح OpenAI في بيئة القياس غير صالحة** (`401 invalid_api_key`). فسقط
   الاستخلاص إلى الطبقة الثالثة في كل حالة غير مُهيكَلة. **الأثر:** أرقام
   الاستخلاص للحالتين (ج) و(د) مقيسة على مسار احتياطي لا على GPT-4o. وهذا لا
   يمسّ نتيجة FI-01 — العدّ لا يعتمد على جودة الاستخلاص — لكنه يمسّ FI-05:
   لا أستطيع أن أنفي أن مفتاحًا صالحًا كان سيستخرج القيم الصحيحة من الكائن
   المفرد. **آلية السقوط تبقى قائمة في الحالتين**، لأنها تقع قبل أي نداء AI.

7. **لم أُعِد إنتاج الضغطة الواحدة ⇒ طلبين.** أعدت إنتاج أثرها فقط (§4).

8. **`pytest -q --collect-only` يخالف حدّ التغطية** (28.58% مقابل 45%) — وهذا
   متوقّع عند التجميع وحده، وقد سجّله تقرير CTO السابق كذلك.

---

## ١٠. ما يحتاج قرارًا

1. **🔴 FI-01 ليس عيب ازدواج مسار، فلا يصحّ إصلاحه بحذف مسار.** القرار المطلوب:
   أين يوضع الحارس — منع الطلب المكرّر في المتصفح، أم حارس تكرار عبر الطلبات
   على مستوى المنظمة/النافذة الزمنية بدل الجلسة، أم كلاهما؟ (الحارس بالجلسة
   قائم ويعمل، ولا يكفي.)

2. **الشقّ غير المُثبَت:** ما الذي يجعل المتصفح يُصدر طلبين من ضغطة واحدة؟
   إثباته يحتاج جلسة متصفح حقيقية مع تسجيل الشبكة. أطلبه كمهمة قياس منفصلة —
   وبدونه يبقى أي إصلاح في الواجهة تخمينًا.

3. **FI-05 يحتاج شحنة مستقلّة** عن FI-01. وموضع القرار: هل يُقبل كائن JSON
   المفرد كصفّ واحد في `_iter_json_records`، أم يُمنع رفعه، أم يُترك للسقوط؟
   الثلاثة تغيّر سلوكًا قائمًا، فالقرار ليس لي.

4. **الرقم التاسع (الحصّة) لم يُقَس.** إن كان الأثر التجاري حاسمًا في الأولوية،
   فالمطلوب تصريح بقياسه على منظمة باشتراك فعّال.

5. **فراغ التغطية في §8** — لا اختبار يعدّ الفواتير من مسار الواجهة. الحارس
   يُكتب مع الإصلاح، وبزرع مخالف يُثبت أنه يفشل قبل أن يُقبل.
