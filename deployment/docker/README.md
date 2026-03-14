# Docker deployment for `live`, `dev`, `test`

هذا المسار يوفّر نشر Docker كامل داخل مجلد `deployment/` لثلاث بيئات مستقلة:

- `live` → `tadgeeg.com`
- `dev` → `dev.tadgeeg.com`
- `test` → `test.tadgeeg.com`

## المكوّنات

- حاوية MySQL مستقلة لكل بيئة
- حاوية Django + Gunicorn مستقلة لكل بيئة
- حاوية Nginx واحدة تعمل كـ reverse proxy أمام البيئات الثلاث

## الملفات

- `deployment/docker/docker-compose.yml`
- `deployment/docker/deploy.sh`
- `deployment/docker/bootstrap_server.sh`
- `deployment/docker/env/live.env.example`
- `deployment/docker/env/dev.env.example`
- `deployment/docker/env/test.env.example`
- `deployment/docker/render_nginx_config.sh`
- `deployment/docker/enable_https.sh`
- `deployment/docker/renew_certs.sh`

## التشغيل لأول مرة

إذا أردت أمراً واحداً فقط على السيرفر يثبت Docker ويشغّل `live` و`dev` و`test` تلقائيًا:

```bash
sudo bash deployment/docker/bootstrap_server.sh
```

هذا السكربت يقوم بـ:

- تثبيت Docker و Docker Compose إذا لم يكونا موجودين
- إنشاء ملفات `env` من الأمثلة
- توليد `SECRET_KEY` وكلمات مرور MySQL تلقائيًا إذا كانت Placeholder
- تشغيل كل البيئات الثلاث دفعة واحدة
- توليد إعداد Nginx HTTP جاهز قبل الإقلاع

بعد ذلك يمكنك تعديل القيم الحساسة مثل:

- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `EMAIL_HOST_USER`
- `EMAIL_HOST_PASSWORD`
- `OPENAI_API_KEY`

ثم إعادة التشغيل:

```bash
bash deployment/docker/deploy.sh restart all
```

انسخ ملفات البيئة:

```bash
bash deployment/docker/deploy.sh init-env
```

ثم عدّل هذه الملفات:

- `deployment/docker/env/live.env`
- `deployment/docker/env/dev.env`
- `deployment/docker/env/test.env`

وحدّث القيم التالية على الأقل:

- `DJANGO_SECRET_KEY`
- `DB_PASSWORD`
- `MYSQL_ROOT_PASSWORD`
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `EMAIL_HOST_USER`
- `EMAIL_HOST_PASSWORD`
- `OPENAI_API_KEY`

## التشغيل

تشغيل كل البيئات:

```bash
bash deployment/docker/deploy.sh up all
```

أو بيئة واحدة فقط:

```bash
bash deployment/docker/deploy.sh up live
bash deployment/docker/deploy.sh up dev
bash deployment/docker/deploy.sh up test
```

## أوامر مفيدة

```bash
bash deployment/docker/deploy.sh ps
bash deployment/docker/deploy.sh logs nginx
bash deployment/docker/deploy.sh logs web_live
bash deployment/docker/deploy.sh restart live
bash deployment/docker/deploy.sh down
```

## تفعيل HTTPS

بعد التأكد أن DNS للدومينات يشير إلى السيرفر وأن المنفذين `80` و`443` مفتوحان:

```bash
bash deployment/docker/enable_https.sh
```

هذا السكربت يقوم بـ:

- تشغيل Nginx على HTTP لخدمة ACME challenge
- طلب شهادات Let's Encrypt للبيئات الثلاث
- توليد إعداد Nginx جديد مع `443 ssl`
- إعادة تحميل Nginx بعد نجاح الشهادات

## تجديد الشهادات

يدويًا:

```bash
bash deployment/docker/renew_certs.sh
```

وممكن تضيف Cron مثل:

```bash
0 3 * * * cd /path/to/repo && bash deployment/docker/renew_certs.sh >> /var/log/finai-certbot.log 2>&1
```

## إنشاء superuser

```bash
docker compose -f deployment/docker/docker-compose.yml exec web_live python manage.py createsuperuser
```

## ملاحظات

- `Nginx` يفتح `80` و`443`.
- لكل بيئة Volumes منفصلة لـ database/static/media/logs.
- HTTPS مدعوم الآن عبر `enable_https.sh` و`renew_certs.sh`.
