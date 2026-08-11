# الخطوة ٤ — قياس البوابة · **النتيجة: توقّف**

> جهاز تطوير · 2026-08-11 · `claude @ e9012cc` · Django 5.2.17
> الأداة: `scratchpad/parity.py` — قراءة-فقط، عدّادات `AuditRun` و`Document`
> و`DocumentAnalysisResult` متساوية قبل وبعد.

---

## ١. ما قيس

34 مستندًا حقيقيًا: أول اثنين من كل نوع من الأنواع الـ22 المخزَّنة، مرتّبة
بـ`order_by("id")`. لكل مستند أُعيد إنتاج المرحلتين ١ و٢ من
`core/services/pipeline.py` بـ`use_ai=False` (حتمي · بلا شبكة · بلا كلفة —
والمرحلتان لا تتغيّران بهذه الشحنة، فهما مُدخَل مشترك للمحرّكين)، ثم نودي
المحرّكان بشكل الاستدعاء نفسه الذي يستعمله `pipeline.py:223` حرفيًا.

وأُضيف قياس لم تطلبه المهمة: استدعاء `_serialise_audit_report` الحقيقي على
ما يُعيده كل محرّك. هي السطر التالي مباشرةً في المرحلة ٣، وتقرير لا
يُسلسَل لا يصل إلى التخزين — فقياس المحرّك وحده يقيس نصف المسار.

---

## ٢. الأرقام الستة

| # | المطلوب | المقيس |
|---|---|---|
| ١ | `blocks_approval` False → True | **غير مقيس** — المسار الجديد لا يُنتج `AuditRun` واحدًا |
| ٢ | `blocks_approval` True → False | غير مقيس — نفس السبب |
| ٣ | فارق `risk_score` متوسط · أقصى | غير مقيس — نفس السبب |
| ٤ | مستندات تغيّر `risk_level` | غير مقيس — نفس السبب |
| ٥ | نتائج القواعد لكل مستند | **18 → غير مقيس** (كان المتوقّع 131) |
| ٦ | أخطأ في أحدهما دون الآخر | 🔴 **34 من 34** |

```
sample size                                  34
OLD engine evaluate() succeeded              34/34
OLD report survived _serialise_audit_report   0/34
NEW adapter evaluate() succeeded              0/34

  34 x  ValueError: LegacyAuditEngineAdapter.evaluate() requires invoice_id
  34 x  AttributeError: 'AuditReport' object has no attribute 'passed_count'

read-only proof:
  audit_runs         before=3     after=3     SAME
  documents          before=1853  after=1853  SAME
  analysis_results   before=0     after=0     SAME
```

**الرقم ٦ أكبر من صفر ⇒ توقّف.** `pipeline.py` لم يُمسّ.

---

## ٣. الشرط الحاجب الأول — الجسر يرفض شكل الاستدعاء

`pipeline.py:223` ينادي:

```python
report = audit_engine.evaluate(document=doc_dict, context=context)
```

و`LegacyAuditEngineAdapter.evaluate` أوّل ما تفعله:

```python
if not invoice_id:
    raise ValueError("LegacyAuditEngineAdapter.evaluate() requires invoice_id")
```

الرفض غير مشروط بالبيانات — يقع قبل أي منطق خاص بالمستند. فـ«34 من 34»
ليست خاصيّة عيّنة، والعيّنة الأكبر لن تغيّرها.

**وحتى مع تمرير معرّف،** الجسر يثبّت `document_type="sales_invoice"` ويمرّر
المعرّف إلى `run_audit_compat` الذي يفهمه **مفتاح السجل المُصنَّف**. ومسار
المستندات لا يملك إلا مفتاح `Document`، ولا واحدًا من أنواعه الـ22 هو
`sales_invoice`. هذا تعارض فضاءات المعرّفات نفسه (الانحراف 51).

⇒ **التبديل يحتاج تعديلًا في `apps/rule_engine/**` — وهو خارج نطاق هذه
الشحنة صراحةً.**

---

## ٤. الشرط الحاجب الثاني — المسار مكسور قبل الشحنة

المحرّك القديم يعمل: 18 قاعدة · `risk=75/critical` على العيّنة الأولى.
ثم يُرمى الناتج كله:

```
_serialise_audit_report(report)
  → AttributeError: 'AuditReport' object has no attribute 'passed_count'
```

`AuditReport` يسمّي العدّادات `passed_rules`/`failed_rules`/`skipped_rules`/
`error_rules`؛ والمُسلسِل يقرأ `passed_count`/`failed_count`/`skipped_count`/
`error_count`. الأربعة كلها.

والمرحلة ٣ تلتقط كل استثناء، فيُضاف السطر إلى `errors` ويبقى
`summary["audit"]` فارغًا — **بلا أثر مرئي واحد.** والدليل المستقلّ:
`DocumentAnalysisResult` صفر صفّ في dev، و`AuditRun` ثلاثة صفوف كلها
`sales_invoice` من مسار الفواتير.

⇒ **الفرضية «18 → 131» غير دقيقة.** ما يصل التخزين اليوم **صفر**. والانتقال
الحقيقي هو صفر → 131، وهو أثر أكبر لا أصغر.

المفارقة: `AuditRunResult` **يحمل** الحقول الأربعة — أُضيفت في الشحنة ١
لهذا المستدعي بالذات. فالتبديل، لو أمكن، **يُصلح** هذا العطل بلا سطر إضافي.

---

## ٥. ما يمرّ بالمسار فعلًا

22 نوعًا مخزَّنًا في `Document`، والمرحلة ٢ تُعيد تصنيفها إلى خمسة فقط:

| ما تُعيده المرحلة ٢ | مستندات العيّنة |
|---|---|
| `invoice` | 17 |
| `other` | 13 |
| `bank_statement` · `payroll` · `receipt` | 1 لكلٍّ |

**لا `sales_invoice` بينها.** والتصنيف المخزَّن والمُستنتَج يختلفان كثيرًا
(`bank_statement` → `invoice` · `purchase_order` → `other`) — بند مستقل عن
هذه الشحنة، وقياسه هنا لأنه يحدّد ما ستراه قواعد الـ131.

المستدعيان: `apps/documents/views.py:264` (متزامن · ملفات < 1MB) و
`apps/documents/tasks.py:48` (Celery). كلاهما حيّ.

الحقول التي يقرأها المسار بعد الاستدعاء — من `_serialise_audit_report` لا
من ذاكرتي: `risk_score` · `risk_level` · `total_rules` · `passed_count` ·
`failed_count` · `skipped_count` · `error_count` · `escalate` ·
`processing_time_ms` · `summary` · `rule_results`؛ ومن كل نتيجة قاعدة:
`rule_id` · `rule_name` · `severity` · `result` · `explanation` · `details`.

---

## ٦. أثر اللوحة — البند ٤ من الأربعة

`apps/frontend/page_views.py:4341-4360` و`apps/reports/views.py:237-256`
كلاهما يجمع من `AuditRun`. الحالة على dev:

| منظمة | `total_runs` | `total_rules_applied` | `re_compliance` | `risk_dist` |
|---|---|---|---|---|
| سعدية سامي محمد حسب الله | 1 | 20 | 15.0% | high: 1 |
| Mohammed Kamal | 2 | 40 | 20.0% | high: 2 |

`AuditRun` بنوع غير `sales_invoice`: **صفر**.

⇒ اللوحة اليوم لا تعرض مسار المستندات إطلاقًا. وأول `AuditRun` يكتبه هذا
المسار **يُدخل مقامًا جديدًا بالكامل**، لا يضاعف مقامًا قائمًا ×7. الخطّ
الفاصل الذي يطلبه MASTER §١.٢ البند ٤ ما زال شرطًا، وأثره أوضح مما وُصف.

**لم أُصلح اللوحة** — الغرض هنا القياس.

---

## ٧. ما يحتاج قرارًا

١. **أين يُصلَح الشرط الأول؟** الجسر خارج نطاق هذه الشحنة. الخياران:
   توسيع `evaluate` لتقبل النوع والمعرّف الصحيحين (تعديل في
   `apps/rule_engine/**`)، أو نقطة دخول جديدة لمسار المستندات. كلاهما شحنة
   مستقلة وقرار معماري.

٢. **الشرط الثاني — أسماء بديلة في `AuditReport`.** أربعة أسطر
   `@property` تُصلح مسار المستندات **بلا** تبديل المحرّك ولا انتقال إلى
   131 قاعدة. تعديل في `apps/audit/audit_engine.py` وهو خارج النطاق.
   وهذا القرار مستقل عن الخطوة ٤ ويستحق أن يُشحن قبلها.

٣. **الترتيب.** ما دام المسار لا يوصل شيئًا إلى التخزين، فالخطوة ٤ ليست
   «18 → 131» بل «تشغيل مسار متوقّف». هل تبقى الخطوة ٤ كما هي، أم تسبقها
   شحنة تُعيد المسار إلى العمل على محرّكه الحالي أولًا فيصير للمقارنة
   خطّ أساس حقيقي؟

٤. **بيئة عرض.** لا نشر قبل فحص متصفّح (`FRONTEND_CONTRACT` §5) وبيان
   whitenoise المبنيّ فعليًا (بند مفتوح من المرحلة ٢) ويومين مراقبة على dev.
