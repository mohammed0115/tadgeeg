# الخطوات ٤–٩ — تغييرات مُجهَّزة، لا مُصرَّح بشحنها

> **الموضع المقترح:** `docs/UNIFICATION_STEPS_4_9.md`
> **الحالة:** جاهزة للتطبيق · **محجوبة** على بوابات مكتوبة أدناه
> **المرجع:** `docs/UNIFICATION_PLAN.md`

> ⚠️ **هذا الملف عمل مُجهَّز لا تصريح.** كل خطوة تحمل بوابتها، ولا تُشحن قبل
> اجتيازها. تجهيز التغيير قبل قراءة الأرقام مقبول؛ شحنه ليس كذلك.

---

## الخطوة ٤ — تبديل مسار المستندات

### البوابة 🔴

**لا تُشحن قبل تنفيذ الخطوة ٠ وقراءة ناتجها.**

| فرق متوسط الدرجة بين `"2.0"` و`"3.0"` | القرار |
|---|---|
| < 5 نقاط | ✅ امضِ |
| 5–15 | ⚠️ الخطوة ٦أ (الظلّ) **قبل** هذه الخطوة |
| > 15 | 🔴 توقّف — قرار مهني |

### التغيير

`core/services/pipeline.py` — السطر 203:

```diff
-        from apps.audit.audit_engine import AuditEngine
+        # مسار المستندات كان المستدعي الوحيد الذي أفلت من ترحيل المحرّكات
+        # القديمة، لأنه لم يكن في قائمة `Callers:` المكتوبة بيد في رأس
+        # legacy_audit_adapter.py. القائمة حملت واحدًا من أربعة.
+        # الجسر يوجّه إلى run_audit_compat، فهذا السطر ينقل المسار من
+        # AuditEngine (18 قاعدة) إلى الأنبوب الذي يختاره AUDIT_ENGINE_VERSION.
+        from apps.rule_engine.services.compatibility.legacy_audit_adapter import (
+            LegacyAuditEngineAdapter as AuditEngine,
+        )
```

**السطر 222 وما بعده لا يُلمس.** بقاؤه حرفيًا هو الإثبات العملي لصحة العقد.

### ما يتغيّر فعلًا

```
مسار المستندات:  18 قاعدة  →  131 قاعدة        (×7)
أوزان الخطورة:   40/25/10/5  →  مركّب بخمسة مكوّنات
عدم التكرار:     لا يوجد  →  نافذة idempotency  (تحسين أمان)
```

### المراقبة — يومان على `dev` قبل `live`

**عدد الملاحظات لكل مستند — العتبة ×5:**

```sql
SELECT r.document_type,
       AVG(c.n) AS avg_results_per_run,
       MAX(c.n) AS max_results
FROM re_audit_run r
JOIN (SELECT audit_run_id, COUNT(*) n FROM re_audit_result GROUP BY audit_run_id) c
  ON c.audit_run_id = r.id
WHERE r.started_at >= NOW() - INTERVAL 2 DAY
GROUP BY r.document_type;
```

**الحجب الجديد — العتبة صفر غير مُفسَّر:**

```sql
SELECT DATE(started_at) d, engine_version,
       SUM(blocks_approval) blocked, COUNT(*) total
FROM re_audit_run
WHERE started_at >= NOW() - INTERVAL 7 DAY
GROUP BY d, engine_version ORDER BY d;
```

| المؤشّر | العتبة | التوقّف |
|---|---|---|
| ملاحظات لكل مستند | زيادة متوقّعة | > ×5 |
| `blocks_approval` | — | أي حجب جديد غير مُفسَّر |
| `AuditRun` فاشل | صفر | أي فشل |
| زمن المعالجة | — | > ضعف السابق |

### التراجع

إرجاع سطرين. لا migration، لا بيانات، لا حالة.

---

## الخطوة ٥ — حذف `AuditEngine`

### البوابة

**أسبوع كامل بعد الخطوة ٤ على `live`.** والأمر التالي فارغ:

```bash
grep -rn "audit\.audit_engine\|AuditEngine(" --include="*.py" apps/ core/ \
  | grep -v legacy_audit_adapter | grep -v "^apps/audit/audit_engine.py" | grep -v test
pytest tests/test_engine_callers.py -q
```

> ⚠️ `apps/invoices/services/processor.py:215` سيظهر — استيراد `run_audit` داخل
> فرع `if not USE_NEW_RULE_ENGINE`. يُزال في الخطوة ٦ب البند ٤، **لا هنا**.
> فالخطوة ٥ تنتظر ٦ب فعليًا؛ أو تُحذف `AuditEngine` وتُبقى `run_audit`.

### ما يُحذف

```
apps/audit/audit_engine.py                     ← 18 قاعدة + REGISTERED_RULES
                                                 + SEVERITY_RISK_WEIGHTS (40/25/10/5)
apps/audit/rules/  (ما لا يستورده غيره)         ← تحقّق قبل الحذف
```

### التراجع

`git revert`. الملف في التاريخ ولا بيانات تتبعه.

**الحصيلة: من ٥ منظومات حكم إلى ٤ · من ٤ مخططات ترجيح إلى ٣.**

---

## الخطوة ٦أ — الظلّ

### التحقق: الوضع منفَّذ فعلًا

فحصت `compat.py:72` و`audit_tasks.py:46` — `shadow` ليس موصوفًا فحسب، بل يعمل:
V2 أساسيًا، وV1 في الخلفية بـ`triggered_by="shadow"`، ونتيجته تُحفَظ ولا تُعرَض.

```python
# على dev فقط
AUDIT_ENGINE_VERSION = "shadow"
```

### استعلام المقارنة — قلب هذه الخطوة

```sql
SELECT
    v2.document_type,
    COUNT(*)                                          AS pairs,
    SUM(v2.risk_level <> v1.risk_level)                AS level_mismatch,
    ROUND(AVG(v2.risk_score - v1.risk_score), 2)       AS avg_score_delta,
    ROUND(MAX(ABS(v2.risk_score - v1.risk_score)), 2)  AS max_abs_delta,
    SUM(v2.blocks_approval AND NOT v1.blocks_approval) AS newly_blocked,
    SUM(v1.blocks_approval AND NOT v2.blocks_approval) AS newly_released
FROM re_audit_run v2
JOIN re_audit_run v1
  ON  v1.document_id   = v2.document_id
  AND v1.organization_id = v2.organization_id
  AND v1.triggered_by  = 'shadow'
  AND v2.triggered_by <> 'shadow'
  AND ABS(TIMESTAMPDIFF(MINUTE, v1.started_at, v2.started_at)) <= 30
WHERE v2.started_at >= NOW() - INTERVAL 7 DAY
GROUP BY v2.document_type;
```

### البوابة

| المؤشّر | يمضي إذا | يتوقّف إذا |
|---|---|---|
| `level_mismatch / pairs` | < 5% | ≥ 5% |
| `newly_blocked` | 0 | > 0 |
| `max_abs_delta` | < 15 | ≥ 15 |

> **`newly_blocked` أخطر من `level_mismatch`.** اختلاف مستوى يُقرأ ويُراجَع؛
> حجبٌ جديد يمنع اعتمادًا كان يُعتمَد — أثر مباشر على عمل المدقق.

**النسبة المقيسة:** ______ / ______ · **`newly_blocked`:** ______

---

## الخطوة ٦ب — تحويل مستدعي V1 الأربعة

### الشرط الحاكم 🔴

**التحويل يمرّ بـ`run_audit_compat` حصرًا، لا باستيراد مباشر لـ`AuditPipelineV2`.**
استيراد V2 مباشرة يُعطِّل التراجع بتغيير إعداد — وهو كل قيمة هذه الخطوة (المخاطرة `R6`).

التوقيع متطابق، فالتحويل استبدال استيراد:

```
AuditPipeline().run(document_id, document_type, organization_id, triggered_by)
run_audit_compat(document_id, document_type, organization_id, triggered_by, force_rerun)
```

### البند ١ — `bootstrap_readiness_window.py` 🟢

```diff
-from apps.rule_engine.executors.audit_pipeline import AuditPipeline
+from apps.rule_engine.pipeline.v2.compat import run_audit_compat
```
```diff
-    AuditPipeline().run(
+    run_audit_compat(
```
أمر إداري، لا مسار مستخدم. **اشحنه أولًا** — يختبر التحويل بأقل ثمن.
واحذف مدخله من `_V1_DIRECT_CALLERS` في `tests/test_engine_callers.py`.

### البند ٢ — `apps/reports/services/gaap_service.py:20` 🟡

نفس التبديل. **راقب:** تقرير GAAP قد يتغيّر محتواه إن اختلفت الدرجة.

### البند ٣ — `apps/rule_engine/api/views.py:135` 🟡

نفس التبديل. هذا يُصلح عيبًا قائمًا: **مدقّق يعيد التدقيق عبر API يحصل اليوم
على جيل محرّك مختلف عن الرفع التلقائي.** بعد التحويل يتّحد المصدر.

### البند ٤ — `apps/invoices/services/processor.py:437` 🔴 الأخطر

```diff
-            from apps.rule_engine.tasks.audit_tasks import run_audit_task
+            from apps.rule_engine.tasks.audit_tasks_v2 import run_audit_compat_task
```
```diff
-            run_audit_task.delay(
+            run_audit_compat_task.delay(
```

**أعلى حركة في المنتج. يُشحن منفردًا، آخِرًا، وثلاثة أيام على `dev`.**

وفي نفس الدفعة: أزل فرع `if not USE_NEW_RULE_ENGINE` واستيراد `run_audit`
(السطران 411 و215) — الراية فقدت معناها بعد حذف `AuditEngine`.

**بعد هذا البند:** انشقاق V1/V2 يسقط · ادّعاء `compat.py` يصير صحيحًا لأول مرة.

---

## الخطوة ٧ — تثبيت الإعداد

`finai_backend/settings_canonical.py` — بجوار `USE_NEW_RULE_ENGINE`:

```python
# أي جيل من الأنبوب يحكم على المستند. كان يأتي من افتراضي مخبوء داخل
# pipeline/v2/compat.py، بينما توثيق ذلك الملف يعلن أن تبديل النسخة
# «يحتاج تغيير إعداد فقط» — والإعداد لم يكن معرَّفًا. قيمة معرَّفة صراحةً
# أفضل من افتراضي مخبوء: أول من يقرأ الإعدادات يرى ما يعمل.
#   "v2"     — الأنبوب المرحلي (الافتراضي)
#   "v1"     — تراجع فوري بلا نشر
#   "shadow" — v2 أساسيًا و v1 في الخلفية للمقارنة
AUDIT_ENGINE_VERSION = os.environ.get("AUDIT_ENGINE_VERSION", "v2")
```

يُنهي فشل `test_audit_engine_version_is_defined_explicitly`، ويصحّح الادّعاء `D5`.

**⚠️ هذه الخطوة آمنة تمامًا ويمكن شحنها اليوم** — تثبّت القيمة التي تعمل فعلًا.

---

## الخطوة ٨ — تصحيح الوثائق العشرة

### `README.md` — بالقيم المقيسة

| البند | الحالي | يُستبدَل بـ |
|---|---|---|
| عدد القواعد | «30 structured rules» | «**173** قاعدة منفَّذة في المحرك النشط · **236** تعريفًا في الكتالوج ينتظر تنفيذًا» ← يُولَّد لا يُكتب |
| الأوزان | «critical 25 · high 15 · medium 8 · low 3» | **يُحذف.** الدرجة `ناجحة/الإجمالي` غير مرجّحة، والترجيح في `RiskEngine` مركّب من خمسة مكوّنات لا من أربعة أوزان |
| العتبات | «≥85 low · ≥70 medium · ≥50 high» | «`Invoice.risk_level`: ≥70 high · ≥40 medium · وإلا low (ثلاثة مستويات) · `AuditRun.risk_level`: ≥75 critical · ≥50 high · ≥25 medium (أربعة)» |
| قاعدة البيانات | «SQLite 3 (default)» · `POSTGRES_*` | «MySQL 8 في الإنتاج · SQLite للاختبارات» |
| خارطة الطريق | «[ ] Unit test suite» | **يُشطب** — 3,932 اختبارًا |
| Django | «4.2 LTS» | يُحدَّث مع الترقية |

### الشيفرة

| # | الملف | الإجراء |
|---|---|---|
| D1 | `apps/audit/audit_engine.py:487` | يُحذف الملف في الخطوة ٥ ⇒ الادّعاء يزول معه |
| D2 | `legacy_audit_adapter.py:11` | تُستبدَل قائمة `Callers:` بـ: «المستدعون محسوبون في `tests/test_engine_callers.py` — لا تُكتب قائمة يدوية هنا» |
| D3 | `legacy_audit_adapter.py:29` | ادّعاء Liskov يصير صحيحًا بعد الخطوة ١؛ يُضاف إليه: «مُثبَت في `tests/test_adapter_contract.py`» |
| D4 | `legacy_audit_adapter.py:47` | «Drop-in replacement» ← «drop-in لعقد `AuditReport` المُختبَر في `tests/test_adapter_contract.py`» |
| D5 | `pipeline/v2/compat.py:5` | يصير صحيحًا بعد ٦ب و٧ |

### القاعدة الدائمة

> **لا يُكتب في تعليق أو وثيقة رقمٌ أو قائمةٌ يمكن حسابها.** يُكتب الأمر الذي
> يحسبها، أو يُترك للاختبار. هذا هو الجذر الذي أنتج كل عَرَض في هذا المشروع.

---

## الخطوة ٩ — `Docs/` و`docs/`

```
git ls-tree -r --name-only HEAD -- Docs | wc -l   →  114
git ls-tree -r --name-only HEAD -- docs | wc -l   →   54  (59 بعد الرقعة)
```

مجلّدان يختلفان بحالة حرف واحد. على macOS أو Windows **لا يُستنسخ المستودع
صحيحًا** — يدمج Git المجلّدين ويُبلّغ عن ملفات معدّلة لم يلمسها أحد. ولم يلاحظه
أحد لأن التطوير والخادم كلاهما Linux.

### الإجراء — على Linux حصرًا

```bash
git mv Docs Documentation
git status --short | head -20      # يجب أن يكون 113 rename، صفر delete
pytest -q 2>&1 | tail -5
grep -rn "Docs/" --include="*.py" --include="*.md" . | grep -v Documentation
```

الخطوة الأخيرة إلزامية: **قِستُها — ١٣ مرجعًا في ١٣ ملفًا** خارج `Docs/` نفسه،
منها `apps/audit/audit_engine.py:485` (يزول مع الخطوة ٥) و`Docs/payment/00.md`
مُشار إليه من ثلاثة اختبارات فوترة وأمر إداري. كلها تعليقات ونصوص توثيق — لا
استيراد ولا مسار ملف تُقرأ في وقت التشغيل، فالإصلاح استبدال نصّي آمن:

> 🔴 **الأمر الأصلي هنا كان معيبًا وأُزيل.** كان `sed` يشمل
> `docs/UNIFICATION_PLAN.md` و`docs/UNIFICATION_STEPS_4_9.md` — أي هذه
> الوثيقة نفسها — فيحوّل تعليماتها إلى `git mv Documentation Documentation`.
> **التعليمات كانت ستُدمّر نفسها.** الصيغة المحصَّنة:

```bash
# ١. اعرض ما سيُمسّ — لا تُنفّذ بعد
grep -rl "Docs/" --include="*.py" --include="*.md" --include="*.sh" . \
  | grep -v "/Documentation/" \
  | grep -v "docs/UNIFICATION_" \
  | grep -v "docs/CTO_DECISION"

# ٢. راجع القائمة بعينك، ثم مرّرها إلى:
#    xargs sed -i 's|Docs/|Documentation/|g'

# ٣. الروابط الداخلية داخل Documentation/ تُصلَح منفصلة
grep -rl "Docs/" Documentation/ | xargs sed -i 's|Docs/|Documentation/|g'
```

> **قاعدة:** `sed -i` بلا عرض مسبق لما سيُمسّ لا يُوثَّق في خطة.

> ⚠️ **لا تنفّذها على macOS/Windows.** استخدم خادم Linux، أو خطوتين عبر اسم
> وسيط (`Docs` → `_tmpdocs` → `Documentation`).

**قابلية العكس:** `git mv` معاكس.

---

## الترتيب النهائي للشحنات

| # | الشحنة | البوابة | الحصيلة |
|---|---|---|---|
| 1 | الخطوات ١·٢·٣ + ٧ | ✅ **جاهزة الآن — مخاطرة صفر** | ٣ حرّاس · جسر مكتمل · إعداد صريح |
| 2 | الخطوة ٩ | Linux | المستودع يُستنسخ على أي نظام |
| 3 | الخطوة ٠ | — | **الأرقام التي تقرّر ما بعدها** |
| 4 | الخطوة ٦أ (إن لزم) | فرق 5–15 نقطة | نسبة اختلاف مقيسة |
| 5 | الخطوة ٤ | بوابة ٠ أو ٦أ | مسار المستندات على المحرك الموحّد |
| 6 | ٦ب البنود ١·٢·٣ | ٤ مستقرّة أسبوعًا | ثلاثة متجاوزين أقل |
| 7 | ٦ب البند ٤ | منفردًا · ٣ أيام dev | **انشقاق V1/V2 يسقط** |
| 8 | الخطوة ٥ | ٦ب مكتملة | **من ٥ منظومات إلى ٣** |
| 9 | الخطوة ٨ | الأخيرة | الوثائق تطابق الكود |

**الشحنة ١ يمكن أن تخرج اليوم.** والشحنة ٣ استعلام. وما بينهما وبعدهما مرهون
بأرقامك لا بهذه الوثيقة.
