# قرار CTO — الشحنة ١

> **التاريخ:** 2026-08-08 · **الفرع:** `claude` · **الـcommit:** محتوى `99d57a6`
> **الحالة:** ✅ **معتمَدة للدفع** · 🔴 **البوابة التالية مغلقة**

---

## ١. الحكم

**الشحنة ١ اجتازت.** المعايير الأربعة كلها:

| المعيار | المطلوب | الواقع |
|---|---|---|
| الفشل المقصود وحده | ١ فقط | ✅ ١ — `test_audit_engine_version_is_defined_explicitly` |
| عدد المجموع | ≥ 3932 | ✅ 3940 = 3932 + 8 (اختبارات الرقعة) — متّسق حسابيًا |
| سقوف المستدعين | مطابقة | ✅ مطابقة حرفيًا · صفر انحراف |
| لا اختبار مُسكَت | صفر | ✅ لا `xfail` · لا `skip` · لا assert مُضعَف |

**3,935 ناجحًا · 1 فاشل مقصود · 4 متخطّى.**

### الدفع مصرَّح به

```bash
git push -u origin claude
```

ثم Pull Request إلى `main`. اذكر في وصفه أن الفشل الواحد مقصود ويُصلَح في
الخطوة ٧.

---

## ٢. أخطائي التي كشفها التقرير

### أ. اسم الجدول — خطأ مني

كتبت `re_audit_runs` في **أربع وثائق**. الاسم الحقيقي `re_audit_run` مفرد
(`apps/rule_engine/models/audit_execution.py:94`). تحققت وأكّدت.

**وهذا نفس الجذر الذي أطارده:** كتبت اسمًا **لم أحسبه**. سطر `grep` واحد كان
سيمنعه. صُحّح في الوثائق الأربع وسُجّل في `EXECUTION_TRACKER` §15 انحراف ٢١.

### ب. الاستعلام كان MySQL على قاعدة SQLite

`NOW() - INTERVAL 30 DAY` و`SUM(x='critical')` لا تعملان على SQLite.
ترجمة المنفّذ عبر ORM كانت التصرّف الصحيح.

**الاستعلام المصحَّح — MySQL (الإنتاج):**

```sql
SELECT engine_version, document_type, COUNT(*) AS runs,
       ROUND(AVG(risk_score),2) AS avg_score,
       SUM(risk_level='critical') AS critical_count,
       SUM(blocks_approval) AS blocked
FROM re_audit_run
WHERE started_at >= NOW() - INTERVAL 30 DAY
GROUP BY engine_version, document_type
ORDER BY runs DESC;
```

**المكافئ عبر ORM (أي قاعدة):**

```python
from django.db.models import Count, Avg, Sum, Q
from django.utils import timezone
from datetime import timedelta
from apps.rule_engine.models import AuditRun

(AuditRun.objects
 .filter(started_at__gte=timezone.now() - timedelta(days=30))
 .values("engine_version", "document_type")
 .annotate(runs=Count("id"),
           avg_score=Avg("risk_score"),
           critical=Count("id", filter=Q(risk_level="critical")),
           blocked=Count("id", filter=Q(blocks_approval=True)))
 .order_by("-runs"))
```

---

## ٣. مصدر الرقعة — تحقّقت منه

المنفّذ لم يجد ملف الرقعة، فولّدها من `origin/chore/unify-audit-engines`.
**القرار صحيح، والمحتوى مطابق:** بصمة `md5` لـ`legacy_audit_adapter.py` في
فرعه = بصمة نسختي بالضبط. اختلاف الـhash (`47463d4` مقابل `99d57a6`) من
`format-patch` وحده — تاريخ الالتزام يُعاد كتابته.

**لكن انتبه:** `origin/chore/unify-audit-engines` **موجود على GitHub**، أي أن
هذا الـcommit دُفع إلى مستودعك من مصدر لم أُحدّده. `origin/claude` كان مطابقًا
لـ`main` تمامًا (`3d29066`). راجع `Settings → Security log` — خاصةً أن رمز
الوصول كان مكشوفًا. **وسحبُ الرمز إن لم يتمّ بعد يسبق كل ما في هذا الملف.**

---

## ٤. الادّعاء الذي لم يتحقّق منه المنفّذ — تحقّقت منه أنا

`apps/audit/tasks.py:139`:

```python
ar.save(update_fields=["audit_report", "updated_at"])
audited += 1                                            # نجح
logger.info("... rules_failed=%d ...", report.failed_count, ...)   # AttributeError
except Exception as exc:
    logger.error("[Task:audit_high_risk] Failed for doc %s: %s", ...)
```

`AuditRunResult` قبل الرقعة عرّف `failed_rules` **ولم يعرّف `failed_count`**.

**فالمهمة كانت تُبلّغ عن فشل لكل مستند دقّقته بنجاح**، والقيمة المُعادة
`{"audited": N}` تعدّه ناجحًا. السجل والعدّاد يتناقضان في كل تشغيل.

الرقعة تُصلحه. وهذا يصحّح تحليلي السابق: قلت إن `tasks.py` يقرأ ثلاثة حقول —
فوّتُّ سطر السجل. الرقم الصحيح: **4 حقول من 12** عبر مستدعيَيه، وأحد النواقص
كان يتعطّل في الإنتاج فعلًا.

---

## ٥. 🔴 البوابة مفتوحة — لا شيء يُشحن بعد الشحنة ١

بيانات المنفّذ: **صفر صفوف** في نافذة الثلاثين يومًا. الإجمالي في dev المحلية
ثلاثة صفوف من 2026-05-11 — جيل واحد (`"2.0"`)، نوع مستند واحد، درجة واحدة
مكرّرة (50.00) ثلاث مرات.

**هذه ليست بيانات. لا قرار يُبنى عليها.**

وصفر صفوف في dev دلالة في ذاتها: بيئة التطوير لا تُنتج حركة تدقيق. فأي اختبار
ظلّ عليها (الخطوة ٦أ) **لن يعطي عيّنة** — وهذا يغيّر خطة الخطوة ٦أ ويحتاج
حلًّا قبل الوصول إليها.

### ما يفتح البوابة

1. استعلام الإنتاج (§2 أعلاه) — **الطريق الأقصر**، ثلاث ثوانٍ
2. أو نسخة من `re_audit_run` من الإنتاج إلى بيئة تحليل
3. أو توليد حركة تمثيلية على dev — بيانات مصطنعة تُوسَم كذلك ولا تُقرأ كقياس

---

## ٦. المصرَّح به الآن — بلا انتظار البوابة

| # | العمل | لماذا آمن |
|---|---|---|
| 1 | **دفع `claude` + PR** | اجتاز بمخرَج مُثبَت |
| 2 | **الخطوة ٧** — `AUDIT_ENGINE_VERSION = os.environ.get(..., "v2")` | يثبّت القيمة العاملة فعلًا · يُنهي الفشل الوحيد |
| 3 | **الخطوة ٩** — `git mv Docs Documentation` | 13 مرجعًا نصّيًا · Linux حصرًا |
| 4 | **سحب شهادات TLS** | خارج نطاق التوحيد · لا ينتظر شيئًا |
| 5 | **ترقية Django 5.2** | حاجز واحد: نمط `STORAGES` من `settings/test.py` |
| 6 | **إكمال ملف القفل** | 10 حزم غائبة منها `pyotp` و`mysqlclient` |

## ٧. المحجوب

الخطوات ٤ · ٥ · ٦أ · ٦ب — كلها حتى تصل أرقام الإنتاج.

---

## ٨. ملاحظة على أداء المنفّذ

التقرير من أفضل ما يمكن أن يصل: أبلغ عن غياب ملف الرقعة بدل تجاوزه بصمت،
واعترض على اسم جدول كتبتُه أنا، وميّز ضوضاء بوابة التغطية عن فشل اختبار، وصرّح
بأن بيانات dev ليست إنتاجًا، وسجّل في §9 أنه لم يتحقّق من ادّعاء رسالة الالتزام.

**§8 غير فارغة، وفيها خطأ للمشرف لا للمنفّذ.** هذا بالضبط ما يجعل التقرير
قابلًا للاعتماد.
