# دليل النشر وحلّ الأعطال — Tadgeeg

سجلّ أعطال **وقعت فعلًا على الإنتاج**، بأعراضها وأسبابها وعلاجها. كل بند هنا
كلّف توقّفًا في الخدمة أو وقتًا ضائعًا في تشخيص خاطئ.

> **القاعدة الأولى: انشر على `dev` قبل `live`.**
> ```bash
> bash deployment/docker/update.sh dev     # جرّب هنا
> bash deployment/docker/update.sh live    # ثم انشر
> ```
> كل عطل مسجّل أدناه كان سيظهر على `dev` بلا ضرر. النشر المباشر على الإنتاج هو
> ما حوّلها إلى انقطاع خدمة.

---

## 1. الموقع يعطي 502 و«Database unavailable» في السجل

**العَرَض**

```
web_live-1 | Waiting for MySQL to become available...
web_live-1 | Database unavailable: [Errno 13] Permission denied: '/app/private_media/partner_applications'
```

وتتكرّر كل ثلاث ثوانٍ، وقاعدة البيانات `healthy`.

**السبب الحقيقي: ليس قاعدة البيانات إطلاقًا.**

Docker ينشئ الـvolume الجديد مملوكًا لـ`root`، والحاوية تعمل بمستخدم `www-data`.
وDjango ينشئ `MEDIA_ROOT` و`PARTNER_DOCS_ROOT` **عند الاستيراد**، فيُرفض الإنشاء
ولا يبدأ gunicorn أصلًا.

وسبب التضليل: حلقة انتظار MySQL في `entrypoint.sh` كانت تلتقط **كل** استثناء
وتطبعه بوصفه «Database unavailable» — فبدا عطل صلاحيات وكأنه عطل قاعدة بيانات،
وضاعت ساعة في الاتجاه الخاطئ.

**العلاج**

```bash
docker compose -f deployment/docker/docker-compose.yml run --rm -u root web_live \
  chown -R www-data:www-data /app/private_media /app/media /app/staticfiles /app/logs

docker compose -f deployment/docker/docker-compose.yml up -d web_live celery_live
```

**الوقاية (مطبَّقة)**

- `Dockerfile` صار ينشئ `/app/private_media` ويمنحه لـ`www-data`، فيرث الـvolume
  الجديد الملكية الصحيحة عند أول إنشاء.
- `entrypoint.sh` يميّز `PermissionError` ويطبع سبب العطل وأمر الإصلاح.
- `update.sh` يصحّح الملكية قبل التشغيل، ويكتشف `Permission denied` بعده فيصلح
  ويعيد التشغيل تلقائيًا.

**⚠️ الـvolume الموجود مسبقًا يبقى مملوكًا لـ`root`** — إعادة البناء وحدها لا
تكفي، لا بدّ من `chown` مرة واحدة.

---

## 2. المتصفّح يقول `ERR_CERT_DATE_INVALID` بعد `git pull`

**السبب: الشهادات كانت مُودَعة في git.**

`deployment/docker/certbot/conf/` كان متتبَّعًا (44 ملفًا، **بما فيها المفاتيح
الخاصة**). فكل `git pull` يدهس الروابط الرمزية في `live/` بنسخ المستودع القديمة،
فيقدّم nginx شهادة منتهية بينما الشهادة السليمة موجودة في `archive/`.

**العلاج**

```bash
bash deployment/docker/renew_certs.sh        # يكتشف الروابط الخاطئة ويصلحها
docker compose -f deployment/docker/docker-compose.yml exec nginx nginx -s reload
```

**الترتيب مهمّ**: أعد تحميل nginx **بعد** إصلاح الروابط لا قبله، وإلا بقي يحمل
الشهادة القديمة في الذاكرة.

**الوقاية (مطبَّقة)**: `certbot/conf/` لم يعد متتبَّعًا وأُضيف إلى `.gitignore`.

**⚠️ المفاتيح الخاصة ما زالت في تاريخ git** — اعتبرها مكشوفة، والتجديد بـ
`--force-renewal` يُصدر مفتاحًا جديدًا.

---

## 3. «40 UNAPPLIED migrations» مع أن الهجرات تعمل

**السبب: قياس الاستعداد بالإشارة الخاطئة.**

`docker compose exec python -c "import django"` يُنشئ عملية **جديدة**، فينجح فور
إقلاع الحاوية — بينما الـentrypoint ما زال داخل `migrate`. فالفحص يسأل عن
الهجرات قبل أن تنتهي.

**العلاج**: الإشارة الصحيحة هي آخر ما يفعله الـentrypoint — ربط gunicorn للمنفذ
8000. مطبَّق في `update.sh`.

**وإن كانت الهجرات غير مطبَّقة فعلًا:**

```bash
docker compose -f deployment/docker/docker-compose.yml exec web_live \
  python manage.py migrate --noinput
```

أربعون هجرة تستغرق دقائق. **لا تقاطعها.**

> **لا تستخدم `--fake` على كل شيء** — يعلّم الهجرات كمطبَّقة دون إنشاء الجداول،
> فتفشل الاستعلامات لاحقًا بلا تفسير مفهوم. استخدمه لهجرة واحدة بعينها فقط، وبعد
> التأكّد من وجود جدولها.

---

## 4. قائمة «الفوترة والاشتراك» تختفي من لوحة التحكم

**السبب: هجرات غير مطبَّقة + معالج سياق يبتلع الأخطاء.**

`apps/billing/context_processors.py:83` فيه `except Exception` عريض يُرجع سياقًا
فارغًا فيه `show_billing_nav=False`. فأي عطل فوترة — عمود ناقص مثلًا — يظهر
**كقائمة غير موجودة**، بلا رسالة خطأ.

**العلاج**: طبّق الهجرات (البند 3).

**تحقّق**: القائمة مقيّدة بالدور أيضًا — تظهر فقط لـ`{admin, cao, finance_manager}`
أو `is_staff`. اختفاؤها عن مدقّق (`senior_auditor`) سلوك صحيح لا عطل.

**⚠️ عيب قائم لم يُصلَح**: ابتلاع الاستثناء يحوّل أي عطل إلى ميزة مفقودة بصمت.
يستحق إصلاحًا مستقلًا.

---

## 5. النشر يتوقّف بـ «Missing key 'PARTNER_DOCS_ROOT'»

**هذا ليس عطلًا — هذا حارس يعمل.**

ملف بيئة أُنشئ قبل هذه المراحل يجتاز فحص «الملف موجود» بينما تنقصه المفاتيح
الجديدة، فيستعمل التطبيق المسار الافتراضي **داخل نظام ملفات الحاوية** — أي خارج
الـvolume — فتُمحى مستندات الشركاء عند إعادة البناء التالية، **بصمت**.

**العلاج**: انسخ الكتلة من `deployment/docker/env/live.env.example` إلى
`live.env` على الخادم. الملفات الحقيقية ليست في المستودع (تحوي أسرارًا).

---

## 6. `test.tadgeeg.com` يفشل تجديد شهادته

```
DNS problem: NXDOMAIN looking up A for www.test.tadgeeg.com
```

النطاق `www.test.tadgeeg.com` غير موجود في DNS. إمّا تضيف سجلًا له، أو تزيله من
`certbot/conf/renewal/test.tadgeeg.com.conf`. لا علاقة له بـ`tadgeeg.com`.

---

## 7. المدفوعات ترجع 401 من Moyasar

```
"You provided your secret key ID instead of the full secret key"
```

القيمة المخزَّنة في `MOYASAR_SECRET_KEY` هي **معرّف** المفتاح لا المفتاح الكامل
(الطول 22 حرفًا؛ الحقيقي أطول بكثير). من لوحة Moyasar → API keys: أظهر المفتاح
الكامل أو ولّد جديدًا، وضعه في `live.env`.

**⚠️ عيب قائم**: `templates/billing/plans.html:343` يعرض ردّ البوابة الخام في
`alert()` للعميل. يجب رسالة عامة وتسجيل التفصيل في الخادم.

---

## فحص قبْلي: قيود التفرّد الجديدة

**قبل أي نشر يحمل هجرة `AddConstraint(UniqueConstraint(...))`.** الهجرة تُطبَّق على
بيانات قائمة، فإن حوت تكرارًا فشلت — و`migrate` يعمل داخل `entrypoint.sh` تحت
`set -e`، أي أن الفشل **يقتل الحاوية عند الإقلاع** فتدخل حلقة إعادة تشغيل بسبب
`restart: unless-stopped`. لا يتوقّف النشر فحسب، بل ينزل الموقع.

```bash
# قراءة فقط — لا يعدّل شيئًا
docker compose -f deployment/docker/docker-compose.yml exec -T db_live \
  mysql -u root -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE" -e "
SELECT file_id, version_number, COUNT(*) AS n
FROM storage_management_filestoragemapping
GROUP BY file_id, version_number HAVING n > 1;"
```

**صفر صفوف ⇒ انشر. أي صفّ ⇒ توقّف** — أي نسخة تبقى قرار بيانات لا قرار نشر.

قيد `webhooks.unique_webhook_endpoint_event` لا يحتاج هذا الفحص: `event_key` يُضاف
حقلًا جديدًا `null=True`، وكل الصفوف القائمة تصير `NULL`، وفهرس التفرّد في MySQL
يسمح بـ`NULL` متعدد.

## ترتيب النشر الآمن

```bash
# 0. الفحص القبْلي أعلاه إن كانت الدفعة تحمل قيد تفرّد

# 1. نسخة احتياطية (قاعدة البيانات + مستندات الشركاء)
bash deployment/docker/backup.sh live

# 2. جرّب على dev أولًا
bash deployment/docker/update.sh dev

# 3. انشر
bash deployment/docker/update.sh live
#    أو مع نسخة احتياطية وتحقّق تلقائيين:
bash deployment/docker/redeploy.sh live

# 4. تحقّق يدويًا
curl -s -o /dev/null -w "%{http_code} ssl=%{ssl_verify_result}\n" https://tadgeeg.com/
curl -s -o /dev/null -w "%{http_code}\n" https://tadgeeg.com/media/partner_applications/   # يجب 404
```

**الفرق بين السكربتين**: `update.sh` ينشر. `redeploy.sh` يأخذ نسخة احتياطية
ويتحقّق بعد النشر ويوقف كل شيء إن كانت مستندات الشركاء قابلة للتنزيل.

## قاعدتان مستخلصتان

1. **العطل يجب ألّا يبدو كميزة غير موجودة.** ابتلاع الاستثناءات حوّل خطأ صلاحيات
   إلى «قاعدة بيانات غير متاحة»، وخطأ فوترة إلى «قائمة غير موجودة». كلاهما كلّف
   ساعات من التشخيص في الاتجاه الخاطئ.

2. **الحارس الذي لم يُختبَر بإفشاله ليس حارسًا.** كل فحص في `update.sh` جُرِّب
   بجعله يفشل — مفتاح ناقص، ومسار داخل جذر media، وهجرة غير مطبَّقة.
