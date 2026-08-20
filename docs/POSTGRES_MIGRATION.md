# ترحيل MySQL → PostgreSQL — إجراء مُجرَّب

> كل رقم هنا من بروفة كاملة على **نسخة بيانات الإنتاج** (`live-20260819-184446`)
> على Postgres 16 وMySQL 8.4، 2026‑08‑20. لا شيء منه مأخوذ من معرفة عامّة.
> **الحالة:** الترحيل مُثبَت تقنيًّا · وبقي قرار عمل واحد (§4).

---

## ١. الخلاصة أوّلًا

| | |
|---|---|
| المخطّط | **196 هجرة · 214 جدولًا** تُبنى على قاعدة فارغة **بلا تعديل سطر واحد** |
| البيانات | **9,642 كائنًا** حُمّلت بالكامل |
| القيود | **12 من 13** تُبنى على بيانات الإنتاج |
| العائق الوحيد | `invoice_unique_number_per_org` — 41 مجموعة · 85 صفًّا · **قرار عمل** |
| تعديل الشيفرة المطلوب | فرع `postgres` في `core/utils/database.py` — **سطور معدودة** |
| SQL خام في المستودع | **موضع واحد** (`SELECT 1`) |

---

## ٢. لماذا الترحيل — ما يشتريه فعلًا

**١ — DDL معامِلاتي.** هذا وحده يبرّره. يومي 17–18 أغسطس، هجرة فاشلة على MySQL
تركت عمودًا مُثبَّتًا وهجرة غير مسجَّلة، فدخلت حاويتان حلقة إقلاع. **على PostgreSQL
تتراجع الهجرة الفاشلة كاملة** — تلك الحالة تصير مستحيلة.

**٢ — ثلاثة عشر قيدًا شرطيًّا لا يبنيها MySQL.** يطبع `models.W036` ويمضي، فتقرأ
الشيفرة كأنها محروسة وهي ليست كذلك. **ودليل ذلك في هذا المستودع:** القيد
`invoice_unique_number_per_org` وُضع في `0008` لمنع تكرار الفواتير، ولم يُبنَ قطّ —
فتراكم 85 صفًّا مكرّرًا، أغلبها ندوب عيب FI‑01.

**٣ — `JSONB`** بدل نصّ: فهرسة واستعلام.

---

## ٣. الإجراء — ست خطوات مُجرَّبة

### ٠ · بروفة على نسخة، لا على الإنتاج

```bash
docker run -d --name pg-rehearse -e POSTGRES_PASSWORD=x -e POSTGRES_DB=finai_pg -p 15432:5432 postgres:16
docker run -d --name my-replica -e MYSQL_ROOT_PASSWORD=x -p 13306:3306 mysql:8.4
```

⚠️ **قاعدة MySQL تُنشأ بترميز الـdump نفسه، وإلا فشلت المفاتيح الأجنبية:**

```sql
CREATE DATABASE finai_live CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

> **مزلق مقيس:** بترميز MySQL 8.4 الافتراضي (`utf8mb4_0900_ai_ci`) تفشل أوّل هجرة
> تُنشئ مفتاحًا أجنبيًّا نحو جدول مستعاد:
> `(3780) Referencing column ... are incompatible`.

### ١ · المخطّط من النماذج، لا من الـdump

```bash
DB_BACKEND=postgres DB_NAME=finai_pg … python manage.py migrate --noinput
```

**النتيجة المقيسة: 196 هجرة · 214 جدولًا · صفر خطأ.**
ولا يُنقَل مخطّط MySQL — يُبنى من النماذج نظيفًا، وتُبنى معه القيود الثلاثة عشر.

### ٢ · أسقِط القيود الجزئية، واحفظ تعريفاتها

```sql
SELECT indexdef FROM pg_indexes
 WHERE schemaname='public' AND indexdef LIKE '%UNIQUE%' AND indexdef LIKE '%WHERE%';
```

> **لماذا:** `loaddata` يتوقّف عند **أوّل** مخالفة. إسقاطها يُحمّل كل شيء ثم يكشف
> **كل** العوائق في جولة واحدة، بدل ثلاث عشرة جولة.

### ٣ · فرّغ ما بذرته الهجرات

```sql
TRUNCATE TABLE <كل جداول public عدا django_migrations> RESTART IDENTITY CASCADE;
```

> **مزلق مقيس:** هجرات البذر تُنشئ صفوفًا (`GAAP-CONS-001` وغيرها)، فيصطدم بها
> الـdump: `duplicate key ... re_rule_definition_rule_code_key`.
> **المخطّط من `migrate`، والبيانات من الـdump، ولا شيء بينهما.**

### ٤ · النقل عبر ORM لا عبر SQL

```bash
# من MySQL
python manage.py dumpdata --natural-foreign --natural-primary \
  -e contenttypes -e auth.Permission -e sessions.Session -e admin.LogEntry \
  --indent 0 -o prod_data.json

# إلى PostgreSQL
python manage.py loaddata prod_data.json
```

**النتيجة المقيسة: `Installed 9642 object(s)`.**

> **ولماذا ORM:** يتجاوز فروق الأنواع بين المحرّكين، **ويُسقط خطر سلسلة الهاش
> تمامًا** — `JSONField` يُسلسَل من كائن بايثون ولا يمرّ بتطبيع `JSONB` أصلًا.
> هذا كان أكبر ما خشيته، والبروفة أسقطته.

### ٥ · أعِد بناء القيود — واحدًا واحدًا

كل فهرس على حدة، فتعرف أيّها رُفض ولماذا.

> ⚠️ في حلقة `bash`، أعطِ `docker exec -i` مُدخَلًا فارغًا (`</dev/null`) أو اقرأ
> من واصف مستقلّ (`3<`) — وإلا ابتلع بقيّة الحلقة وأبلغ عن نجاح لم يُقَس.
> **وقع هذا هنا: قِيس فهرس واحد وقُرئ الجدول كأن الثلاثة عشر مرّت.**

### ٦ · البوابة

```
عدد صفوف كل جدول = المصدر
17/17 سلسلة تدقيق سليمة        ← verify_chain
مجاميع مالية متطابقة
migrate --check يخرج بصفر
```

---

## ٤. العائق الوحيد — وهو قرار عمل

```
invoice_unique_number_per_org   ON invoices (organization_id, invoice_number)
                                WHERE NOT is_deleted AND invoice_number <> ''
41 مجموعة · 85 صفًّا زائدًا
```

**مقيس على بيانات الإنتاج:**

| | |
|---|---|
| التوزيع الزمني | 29 زوجًا خلال 5 ثوانٍ · 31 خلال دقيقة · 20 خلال ساعة · 5 أبعد |
| مقابل إصلاح FI‑01 (2026‑08‑15) | **126 صفًّا قبله · صفر بعده** |
| الطبيعة | `test_invoice_tadgeeg` · `zatca_test_invoice` · `Tableau_Training_Data_row*` |
| الحالة | `flagged` أو `processing` عالق |
| المنظّمات | 11 · أغلبها حسابات الفريق |

⇒ **ندوب عيب مُشخَّص ومُصلَح، لا سجلّات محاسبية.** والقيد وُضع أصلًا ليمنع ذلك العيب.

**والخيارات:**

| | |
|---|---|
| **أ** | تعليم النسخ الأحدث `is_deleted=1` — **لا حذف** · القيد الجزئي يستثنيها فيُبنى · وتبقى للمراجعة |
| **ب** | ترحيل بلا هذا القيد، وبناؤه بعد التنظيف — يُبقي الباب مفتوحًا |
| **ج** | مراجعة يدوية للـ25 التي تباعدت أكثر من دقيقة، وآلية للستّين الباقية |

**التوصية: (أ)** — لا صفّ يُفقَد، والقيد يُبنى، والمراجعة تبقى ممكنة.
**وهو قرار عمل لا قرار تقني.**

---

## ٤ب. خطوة إلزامية: فهارس عدم حسّاسية الأحرف

**تُنفَّذ في التحوّل، لا قبله.** على MySQL الترميز `utf8mb4_unicode_ci` **لا يميّز**
حالة الأحرف، فقيود التفرّد النصّية محروسة اليوم. وPostgres يميّز ⇒ **تُرخى بصمت.**

**والصمت هو الخطر:** عائق `invoice_unique_number_per_org` يوقف الاستيراد فيُجبرك
على حسمه. أمّا هذا فالترحيل ينجح، والقاعدة تعمل، **ثم يُنشئ مستخدم حسابًا ثانيًا
ببريده نفسه بحرف كبير بعد شهور.**

**مقيس على بيانات الإنتاج:** 15 حقلًا فريدًا نصّيًّا · **صفر تصادم قائم** ⇒ الفهارس
تُبنى نظيفة بلا تنظيف. و12 منها للمشروع (`auth` و`sessions` و`token_blacklist`
أطراف ثالثة، لا تُلمس).

```sql
-- مُولَّدة من النماذج، لا مكتوبة بيد. كلّها بُنيت على نسخة الإنتاج: 12/12.
CREATE UNIQUE INDEX ci_auth_users_email                     ON auth_users (LOWER(email)) WHERE email <> '';
CREATE UNIQUE INDEX ci_payments_paymenttransaction_idempotency_key
       ON payments_paymenttransaction (LOWER(idempotency_key)) WHERE idempotency_key <> '';
CREATE UNIQUE INDEX ci_audit_cases_case_number              ON audit_cases (LOWER(case_number)) WHERE case_number <> '';
CREATE UNIQUE INDEX ci_re_rule_definition_rule_code         ON re_rule_definition (LOWER(rule_code)) WHERE rule_code <> '';
CREATE UNIQUE INDEX ci_organization_api_keys_key_hash       ON organization_api_keys (LOWER(key_hash)) WHERE key_hash <> '';
CREATE UNIQUE INDEX ci_billing_plan_code                    ON billing_plan (LOWER(code)) WHERE code <> '';
CREATE UNIQUE INDEX ci_billing_addon_code                   ON billing_addon (LOWER(code)) WHERE code <> '';
CREATE UNIQUE INDEX ci_cms_platform_setting_key             ON cms_platform_setting (LOWER(key)) WHERE key <> '';
CREATE UNIQUE INDEX ci_cms_seo_setting_page_key             ON cms_seo_setting (LOWER(page_key)) WHERE page_key <> '';
CREATE UNIQUE INDEX ci_documents_canonicalfielddefinition_field_code
       ON documents_canonicalfielddefinition (LOWER(field_code)) WHERE field_code <> '';
CREATE UNIQUE INDEX ci_storage_management_storageprovider_name
       ON storage_management_storageprovider (LOWER(name)) WHERE name <> '';
CREATE UNIQUE INDEX ci_zatca_rejection_codes_code           ON zatca_rejection_codes (LOWER(code)) WHERE code <> '';
```

**وأُثبتت بزرع مخالف:** قبل بنائها قَبِل Postgres
`casetest.probe@example.com` و`CASETEST.PROBE@EXAMPLE.COM` معًا. بعدها:

```
duplicate key value violates unique constraint "ci_auth_users_email"
```

⚠️ **ولا تُكتب هجرة Django بها الآن.** على MySQL هي زائدة، وتطبيقها اليوم يضيف
12 فهرسًا للإنتاج بلا مكسب. موضعها هذه الخطوة، بين §5 و§6 من الإجراء.

---

## ٥. تعديلات الشيفرة المطلوبة

| | |
|---|---|
| `core/utils/database.py` | فرع `postgres` — **مُنفَّذ** · وحارسه `tests/test_postgres_backend_selection.py` |
| `_normalized_backend` | لم يكن يعرف الكلمة، فالفرع كان غير قابل للبلوغ · **مُصلَح** |
| `requirements` | `psycopg2-binary` **مُعلَن ومقفول أصلًا** — لا تغيير |
| `docker-compose.yml` | خدمة Postgres بدل MySQL — لم تُكتب بعد |
| `backup.sh` | `pg_dump` بدل `mysqldump` — لم يُكتب بعد |

---

## ٦. ما لم يُقَس بعد

| البند | لماذا يهمّ |
|---|---|
| **التسلسلات (`sequences`)** | بعد `loaddata` قد تبقى عند 1، فيصطدم أوّل إدراج. المزلق الكلاسيكي — ولم أختبر إدراجًا بعد التحميل |
| **حسّاسية حالة الأحرف** | MySQL `utf8mb4_unicode_ci` **لا يميّز** الأحرف؛ Postgres يميّز ⇒ قيد البريد **يُرخى** فيصير حسابان لنفس العنوان ممكنَين. يحتاج `CITEXT` أو فهرسًا على `LOWER()` |
| **الأداء** | لم يُقَس |
| **زمن التوقّف** | 9,642 كائنًا حُمّلت بسرعة، لكن على عتاد الخادم غير مقيس |
| **الرجوع** | لم يُجرَّب رجوعٌ من Postgres إلى MySQL |

⚠️ **البندان الأولان يجب قياسهما قبل أي تنفيذ على الإنتاج.**
