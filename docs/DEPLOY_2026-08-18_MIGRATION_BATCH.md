# نشر دفعة الهجرات — 2026‑08‑18

نشر `tadgeeg.com` (`72.62.239.220`) من نسخة **1‑8‑2026** إلى `main`.
الدفعة **22 هجرة**، فيها ثلاث سلاسل هاش وقيد فريد وإعادة بناء سلسلة.

هذا ليس دليلًا عامًّا — دليل الأعطال العامّ في [runbook-deployment.md](runbook-deployment.md).
هذا إجراء **هذه** الدفعة، مبنيّ على بروفة كاملة على نسخة من بيانات الإنتاج.

---

## ١. ما وجدته البروفة

استُعيدت نسخة بيانات live في قاعدة معزولة على خادم التدريب، وشُغّلت الدفعة عليها.
**فشلت مرّتين قبل أن تمرّ**، والفشلان كلاهما كان سيُسقط الإنتاج في حلقة إقلاع:

### العيب الأول — `documents.0013`

```
MySQLdb.OperationalError:
  (1054, "Unknown column 'invoices.audit_document_id' in 'field list'")
```

الـbackfill قرأ نماذج التطبيق من `django.apps.apps` — السجلّ الحيّ — فبنى
`SELECT` يذكر عمودًا تُنشئه `invoices.0017`. وتلك الهجرة **تعتمد على 0013**، فالترتيب
مفروض بنيويًّا والعمود غائب حتمًا.

**الإصلاح:** السجلّ التاريخي الذي تُمرّره `RunPython`.
**الحرّاس:** `tests/test_migration_0013_historical_registry.py` — 6 اختبارات، منها
سقّاطة على الشجرة كلّها تمنع أي هجرة من طلب السجلّ الحيّ.

### العيب الثاني — `invoices.0016`

```
IntegrityError: (1062, "Duplicate entry
  '88bc8c33-fbb0-48cb-963b-62220dc5b2bb-13'
  for key 'invoice_audit_events.uniq_chain_position_invoiceauditevent'")
```

سلسلة تدقيق مشقوقة في بيانات الإنتاج: تسعة مواضع تحمل أكثر من صفّ، واثنا عشر صفًّا
بلا موضع. كل تصادم بنفس الشكل — حدثان بنفس `previous_hash` وهاشين مختلفين، أي
كاتبان قرآ رأس السلسلة معًا.

`activity_logs` و`authentication` أخذتا `unify` + `rebuild` قبل قيد الشقّ.
`invoices` أخذت القيد وحده.

**الإصلاح:** `apps/invoices/migrations/0015a_rebuild_invoice_audit_chains.py`، على
منوال `authentication/0010` حرفيًّا — إعادة ترقيم وتجزئة، **بلا حذف صفّ**.
**الحرّاس:** `tests/test_invoice_chain_rebuild.py` — 8 اختبارات، منها زرع الشقّ
المقيس وإثبات أن `AddConstraint` كان يفشل قبله ويمرّ بعده.

### ما لم يكن عيبًا

- `ledger.0004` — الجدول فارغ في بيانات live. آمن.
- `activity_logs` · `audit_logs` · `audit_working_papers` · `audit_chain_checkpoints` ·
  `evidence_access` — صفر شقوق.
- قيد `storage_management.0002` الفريد — صفر تكرار.

---

## ٢. الفحص الوقائي — قراءة فقط، قبل أي تغيير

**كل أمر يبدأ بتعريف الخادم. الخطأ هنا يعني نشرًا على الجهاز الخطأ.**

```bash
echo "══ $(hostname) · $(hostname -I | awk '{print $1}') ══"   # يجب: 72.62.239.220
cd /root/tadgeeg   # أو مسار المستودع على الإنتاج
C="docker compose -f deployment/docker/docker-compose.yml"
```

### أ · مفاتيح البيئة

```bash
grep -nE "^DEBUG|^EMAIL_HOST_USER|^EMAIL_HOST_PASSWORD" deployment/docker/env/live.env
```

`DEBUG=False` مع `EMAIL_HOST_USER=` فارغ ⇒ **فشل إقلاع مضمون**
(`ImproperlyConfigured: Production email not configured`). أوقف حتى تُملأ.

### ب · القيد الفريد

```bash
$C exec -T db_live sh -c 'exec mysql -N -B -uroot -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE" -e "
SELECT COUNT(*) FROM (SELECT 1 FROM storage_management_filestoragemapping
GROUP BY file_id, version_number HAVING COUNT(*)>1) d;"'
```

### ج · هجرة نصف‑مطبَّقة — الفحص الذي لم يكن موجودًا

عمود موجود وهجرته غير مسجَّلة. هذه الحالة **شلّت بيئتين** يوم 2026‑08‑17، ولا
يكتشفها فحص الصفوف المكرّرة:

```bash
$C exec -T db_live sh -c 'exec mysql -N -B -uroot -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE" -e "
SELECT CONCAT(\"column_present=\",COUNT(*)) FROM information_schema.columns
 WHERE table_schema=DATABASE() AND table_name=\"documents_documentcanonicaldata\"
   AND column_name=\"organization_id\";
SELECT CONCAT(\"migration_recorded=\",COUNT(*)) FROM django_migrations
 WHERE app=\"documents\" AND name=\"0013_canonical_data_organization\";"'
```

`column_present=1` مع `migration_recorded=0` ⇒ **توقّف.** احذف العمود أولًا
(انظر §٦) وإلا دخلت حلقة `1060`.

### د · الشقوق في سلاسل الهاش

```bash
$C exec -T db_live sh -c 'exec mysql -N -B -uroot -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE" -e "
SELECT CONCAT(\"forked=\",COUNT(*)) FROM (
  SELECT 1 FROM invoice_audit_events WHERE chain_position IS NOT NULL
  GROUP BY chain_partition, chain_position HAVING COUNT(*)>1) d;
SELECT CONCAT(\"null_positions=\",COUNT(*)) FROM invoice_audit_events
 WHERE chain_position IS NULL;"'
```

أي رقم هنا **متوقَّع** — `0015a` هي التي تعالجه. سجّله للمقارنة بمخرَج الهجرة.

---

## ٣. النسخة الاحتياطية

```bash
bash deployment/docker/backup.sh live
```

ثم **انسخها خارج الخادم**. نسخة على نفس القرص ليست نسخة:

```bash
# من جهازك، لا من الخادم
scp -r root@72.62.239.220:/root/tadgeeg/deployment/docker/backups/live-<TS> ./
```

> `backup.sh:183` يطبع IP الإنتاج مثبَّتًا في الشيفرة. على أي خادم آخر يرسلك للمكان الخطأ.

---

## ٤. النشر — يدويًّا، لا عبر `update.sh`

**لماذا لا `update.sh`:** يوم 2026‑08‑17 طبع `4/4 Waiting for services to become
healthy` — سلسلة **غير موجودة في شيفرته** — ثم `✅ Update COMPLETE` فوق حاوية ميتة.
بوابة الصحّة لم تعمل. السبب غير محسوم، ولا يُبنى نشر إنتاج على أداة تُخالف مصدرها.

```bash
# 1 — الكود. لا يمسّ أي حاوية عاملة.
git fetch origin && git log --oneline HEAD..origin/main | wc -l
git reset --hard origin/main
git log -1 --format='%h %s'

# 2 — الصورة. تُبنى بجانب الحاوية العاملة، والموقع يخدم طوال الوقت.
$C build web_live

# 3 — أوقف الكاتبَين. من هنا يبدأ التوقّف المعلن.
#
#     0015a يُعيد ترقيم كل حدث تدقيق في القاعدة. حدث يُكتب أثناء ذلك يأخذ
#     موضعًا من الترقيم القديم — وهو بالضبط السباق الذي أنتج الشقّ أصلًا —
#     فيصطدم بالترقيم الجديد ويُفشل AddConstraint بعده. النافذة قياسها 42
#     ثانية على بيانات الإنتاج، وإغلاقها أرخص من تشخيصها.
$C stop web_live celery_live

# 4 — الهجرة في حاوية تُرمى.  ← نقطة الأمان الكاملة
#     أي فشل هنا رسالة خطأ فقط: لا set -e، لا restart، لا حلقة إقلاع.
$C run --rm --entrypoint sh web_live -c \
  'python manage.py migrate --noinput --fake-initial 2>&1' | tee /tmp/live-migrate.log
```

**فشل هنا؟ أعِد الخدمة فورًا على النسخة القديمة، ثم شخّص:**

```bash
git reset --hard <commit القديم> && $C build web_live && $C up -d web_live celery_live
```

الصورة القديمة ما زالت موجودة والقاعدة لم تكتمل هجرتها — لكن **احذف أثر أي هجرة
نصف‑مطبَّقة أولًا** (§٦)، وإلا دخلت الشيفرة القديمة على مخطّط لا تعرفه.

**اقرأ المخرَج قبل أي خطوة تالية.** المتوقّع:

```
[0013] canonical rows: assigned=… left_null_parent_missing=… left_null_model_unknown=…
[invoices rebuild] organisations=… events_repositioned=…
  Applying invoices.0016_chain_partition_and_fork_constraint... OK
```

أي `Traceback` ⇒ **توقّف** وأعِد الخدمة على القديم كما أعلاه.

```bash
# 5 — نقطة اللاعودة. لا تصلها إلا والمخرَج نظيف.
$C up -d --no-deps web_live celery_live
```

**قياسًا على البروفة، التوقّف المتوقّع من §٣ إلى §٥ نحو دقيقة ونصف** — منها 42
ثانية هجرة والباقي إقلاع gunicorn. انشر في نافذة منخفضة الحركة.

---

## ٥. التحقّق

```bash
sleep 25
$C ps web_live celery_live                                   # لا Restarting
$C run --rm --entrypoint sh web_live -c 'python manage.py migrate --check' \
  && echo "✓ لا هجرات معلّقة"
curl -sS -o /dev/null -w "tadgeeg.com → HTTP %{http_code}\n" https://tadgeeg.com/
curl -sS https://tadgeeg.com/health/ | head -c 300; echo
```

`/health/` يُبلَّغ ولا يحجب: يعيد 503 على Redis متدهور بينما الموقع يخدم تمامًا.
**قاعدة بيانات متدهورة هي الاستثناء، وهي قاتلة.**

**ثم اختبار وظيفي — الأهمّ:** ارفع فاتورة واحدة وتحقّق من ثلاثة:
فاتورة واحدة لا اثنتان · المجموع يظهر · مجموع البنود = الإجمالي.

---

## ٦. التراجع

**فشل في الخطوة 3** (حاوية `--rm`): لا تراجع مطلوب — لم يتغيّر شيء.
إن كانت الهجرة قد طبّقت جزءًا قبل فشلها، احذف أثرها قبل إعادة المحاولة:

```bash
$C exec -T db_live sh -c 'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE" -e "
SET @c := (SELECT column_name FROM information_schema.columns WHERE table_schema=DATABASE()
   AND table_name=\"documents_documentcanonicaldata\" AND column_name=\"organization_id\" LIMIT 1);
SET @s := IF(@c IS NULL,\"SELECT 1\",\"ALTER TABLE documents_documentcanonicaldata DROP COLUMN organization_id\");
PREPARE p FROM @s; EXECUTE p; DEALLOCATE PREPARE p;"'
```

> **كل محاولة فاشلة تُعيد إنشاء العمود.** MySQL يُثبّت DDL فورًا، فالحذف مطلوب
> قبل **كل** إعادة محاولة، لا مرّة واحدة.

**فشل في الخطوة 4** (بعد ترقية الحاوية):

```bash
git reset --hard <commit القديم>
$C build web_live
bash deployment/docker/backup.sh live --restore <مسار النسخة>
$C up -d --no-deps web_live celery_live
```

استعادة القاعدة **إلزامية** — المخطّط تقدّم 22 هجرة والشيفرة القديمة لا تعرفه.

---

## ٧. مخاطر متبقّية، مسجَّلة لا مُصلَحة

| | |
|---|---|
| **السباق نفسه ما زال قائمًا** | حدثا `uploaded`/`processed` يقرآن رأس السلسلة معًا. بعد `0016` يفشل الخاسر بـ`IntegrityError` بدل أن يشقّ السلسلة صامتًا، و`CHAIN_INSERT_RETRIES=5` يُعيد المحاولة — لكن هذا المسار **لم يُقَس** تحت مدّة قفل معاملة الرفع الطويلة |
| **`update.sh` يُخالف مصدره** | نُفّذت نسخة لا تطابق الملف على القرص، فلم تعمل بوابة الصحّة. السبب غير محسوم |
| **الفحص الوقائي في `update.sh`** | يرى الصفوف المكرّرة فقط. §٢‑ج و§٢‑د أعلاه ليسا فيه |
| **`backup_live_database` و`assert_no_unique_constraint_violations`** | `case live\|all` — الهدف `test` يتخطّاهما بلا تحذير |
| **`dev` ليست بيئة مستقلّة** | `dev.env` نسخة من `test.env`: `DB_HOST=db_test`. أي قياس على dev يقيس قاعدة test |
| **إعادة البناء لا تُثبت الماضي** | تُنشئ خطّ أساس قابلًا للتحقّق من لحظتها. هذا نصّ سياسة المستودع في `authentication/0010`، لا تخفيف |

---

## ٨. سجلّ البروفة

| | |
|---|---|
| المصدر | `backup.sh live --db-only` · 2026‑08‑17 12:14 · 1.5 MB مضغوطة |
| البيئة | قاعدة `finai_rehearse` معزولة على خادم التدريب |
| الحجم | 204 جدولًا · 2,121 صفًّا قانونيًّا · 160 فاتورة · 174 هجرة مسجَّلة |
| زمن الفشل الثاني | 30 ثانية |
| المجموعة | 4149 ✓ · 0 ✗ |

**بيانات العملاء المنسوخة تُمسح بعد البروفة** — من خادم التدريب ومن أي جهاز نُسخت إليه.
