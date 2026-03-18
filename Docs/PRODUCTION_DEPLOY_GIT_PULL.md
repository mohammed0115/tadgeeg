# دليل النشر والتحديث على الإنتاج

هذا الدليل مخصص لبيئة الإنتاج `live` فقط، ويعتمد على مسار Docker الموجود داخل `deployment/docker/`.

إذا كان السيرفر يعمل حالياً بهذا المسار، فهذا هو الدليل الصحيح للنشر بعد `git pull`.

## الملفات المهمة

- `deployment/docker/deploy.sh`
- `deployment/docker/docker-compose.yml`
- `deployment/docker/env/live.env`
- `deployment/docker/env/live.env.example`
- `docker/entrypoint.sh`

## ملاحظات مهمة قبل البدء

- الأوامر التالية تُنفّذ من جذر المشروع.
- هذا المسار يستخدم خدمات الإنتاج التالية: `db_live` و `web_live` و `nginx`.
- عند تشغيل `web_live` يتم تنفيذ `migrate` و `collectstatic` تلقائياً من خلال `docker/entrypoint.sh`.
- الفرع الافتراضي في الأمثلة هو `main`. إذا كان الإنتاج عندك يعمل على فرع آخر فاستبدله.

## 1) النشر الأولي على السيرفر

### المتطلبات

- `git`
- `docker`
- `docker compose`

إذا لم يكن Docker مثبتاً بعد، ثبّته أولاً أو استخدم سكربت التهيئة الآلي الموجود في:

```bash
deployment/docker/bootstrap_server.sh
```

ملاحظة: هذا السكربت يشغّل `live` و `dev` و `test` معاً، لذلك في الإنتاج فقط يفضّل اتباع الخطوات اليدوية أدناه.

### خطوات النشر الأولي

```bash
git clone <repo-url> <repo-dir>
cd <repo-dir>
```

أنشئ ملف البيئة للإنتاج:

```bash
bash deployment/docker/deploy.sh init-env
```

عدّل ملف الإنتاج:

```bash
nano deployment/docker/env/live.env
```

راجع القيم التالية على الأقل:

- `DJANGO_SECRET_KEY`
- `SECRET_KEY`
- `DEBUG=False`
- `ALLOWED_HOSTS`
- `CSRF_TRUSTED_ORIGINS`
- `SITE_URL`
- `DB_NAME`
- `DB_USER`
- `DB_PASSWORD`
- `MYSQL_ROOT_PASSWORD`
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REDIRECT_URI`
- `EMAIL_HOST_USER`
- `EMAIL_HOST_PASSWORD`
- `OPENAI_API_KEY`

شغّل بيئة الإنتاج:

```bash
bash deployment/docker/deploy.sh up live
```

تحقق من حالة الخدمات:

```bash
bash deployment/docker/deploy.sh ps
```

تابع السجلات إذا لزم:

```bash
bash deployment/docker/deploy.sh logs web_live
bash deployment/docker/deploy.sh logs nginx
```

### تفعيل HTTPS

بعد ضبط DNS وفتح المنافذ `80` و `443`:

```bash
bash deployment/docker/enable_https.sh
```

## 2) التحديث بعد `git pull` في الإنتاج

هذا هو المسار الذي تستخدمه في كل تحديث كود على السيرفر.

### الخطوات الآمنة الموصى بها

ادخل إلى مجلد المشروع:

```bash
cd <repo-dir>
```

تحقق من وجود تعديلات محلية قبل السحب:

```bash
git status --short
```

إذا ظهر أي تعديل محلي، لا تنفّذ `git pull` قبل معرفة سببه.

خذ نسخة احتياطية من قاعدة البيانات قبل التحديث:

```bash
mkdir -p backups
docker compose -f deployment/docker/docker-compose.yml exec -T db_live sh -c 'exec mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE"' > backups/live_$(date +%F_%H%M%S).sql
```

اسحب آخر نسخة من الفرع الإنتاجي:

```bash
git fetch origin
git pull --ff-only origin main
```

أعد بناء وتشغيل الإنتاج:

```bash
bash deployment/docker/deploy.sh up live
```

هذا الأمر يقوم بـ:

- إعادة بناء صورة `web_live` إذا تغير الكود أو المتطلبات.
- تشغيل أو تحديث `db_live` و `web_live` و `nginx`.
- تنفيذ `migrate` تلقائياً.
- تنفيذ `collectstatic` تلقائياً.

تحقق بعد التحديث:

```bash
bash deployment/docker/deploy.sh ps
bash deployment/docker/deploy.sh logs web_live
```

تحقق من نقطة الصحة:

```bash
curl -fsS https://tadgeeg.com/health/
```

إذا كان الدومين مختلفاً في إنتاجك، استبدل `tadgeeg.com` بالدومين الصحيح.

## 3) متى أستخدم `up live` ومتى أستخدم `restart live`؟

استخدم هذا الأمر بعد أي `git pull` أو أي تغيير في الكود أو `requirements.txt` أو `Dockerfile`:

```bash
bash deployment/docker/deploy.sh up live
```

استخدم هذا الأمر فقط إذا عدّلت `deployment/docker/env/live.env` ولا تحتاج إعادة build للصورة:

```bash
bash deployment/docker/deploy.sh restart live
```

## 4) أوامر تشغيل سريعة للإنتاج

تشغيل أو تحديث الإنتاج:

```bash
bash deployment/docker/deploy.sh up live
```

إعادة تشغيل الإنتاج:

```bash
bash deployment/docker/deploy.sh restart live
```

إيقاف الإنتاج:

```bash
bash deployment/docker/deploy.sh stop live
```

عرض الخدمات:

```bash
bash deployment/docker/deploy.sh ps
```

سجلات التطبيق:

```bash
bash deployment/docker/deploy.sh logs web_live
```

سجلات Nginx:

```bash
bash deployment/docker/deploy.sh logs nginx
```

## 5) تحديث ملف البيئة في الإنتاج

إذا أضفت متغيرات جديدة في الكود:

```bash
nano deployment/docker/env/live.env
```

بعد الحفظ:

```bash
bash deployment/docker/deploy.sh restart live
```

إذا كان التحديث يتضمن مكتبات جديدة أو تغييرات في صورة Docker، استخدم بدلاً من ذلك:

```bash
bash deployment/docker/deploy.sh up live
```

## 6) Rollback سريع عند حدوث مشكلة

اعرض آخر الإصدارات:

```bash
git log --oneline -n 10
```

ارجع إلى commit سابق:

```bash
git reset --hard <commit>
```

ثم أعد تشغيل الإنتاج:

```bash
bash deployment/docker/deploy.sh up live
```

## 7) Checklist مختصر لكل تحديث إنتاج

```bash
cd <repo-dir>
git status --short
mkdir -p backups
docker compose -f deployment/docker/docker-compose.yml exec -T db_live sh -c 'exec mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE"' > backups/live_$(date +%F_%H%M%S).sql
git fetch origin
git pull --ff-only origin main
bash deployment/docker/deploy.sh up live
bash deployment/docker/deploy.sh ps
bash deployment/docker/deploy.sh logs web_live
```

## 8) ملاحظات تشغيلية

- إذا فشل `git pull` بسبب تعديلات محلية، عالج هذه التعديلات أولاً ولا تكمل بشكل عشوائي.
- إذا تغيرت إعدادات Google OAuth أو البريد، عدّل `deployment/docker/env/live.env` ثم نفّذ `bash deployment/docker/deploy.sh restart live`.
- إذا أضفت dependency جديدة في `requirements.txt` فلا يكفي `restart live`، بل يجب تنفيذ `bash deployment/docker/deploy.sh up live`.
- إذا كانت هناك مشكلة بعد النشر، ابدأ دائماً بـ `bash deployment/docker/deploy.sh logs web_live` ثم `bash deployment/docker/deploy.sh logs nginx`.

## 9) مراجع داخل المشروع

- الدليل العام: `Docs/DEPLOYMENT_GUIDE.md`
- إعداد Docker متعدد البيئات: `deployment/docker/README.md`
- تشغيل الخدمات: `deployment/docker/deploy.sh`
- ملف compose: `deployment/docker/docker-compose.yml`
