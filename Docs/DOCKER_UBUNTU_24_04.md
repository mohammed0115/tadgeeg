# Docker Deployment on Ubuntu 24.04

هذا الدليل يشرح تشغيل مشروع `Django + MySQL + Gunicorn + Nginx` باستخدام Docker على سيرفر Ubuntu 24.04.

## الملفات المضافة

- `Dockerfile`
- `docker-compose.yml`
- `.dockerignore`
- `docker/entrypoint.sh`
- `docker/nginx/default.conf.template`

## 1) تثبيت Docker على Ubuntu 24.04

```bash
sudo apt update
sudo apt install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
```

## 2) تجهيز متغيرات البيئة

انسخ ملف المثال:

```bash
cp .env.example .env
```

ثم عدّل القيم المهمة داخل `.env`:

- `DJANGO_SECRET_KEY`
- `SECRET_KEY`
- `DEBUG=False`
- `ALLOWED_HOSTS`
- `SITE_URL`
- `NGINX_HOST`
- `DB_NAME`
- `DB_USER`
- `DB_PASSWORD`
- `MYSQL_ROOT_PASSWORD`
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `OPENAI_API_KEY`

## 3) أول تشغيل على السيرفر

من داخل مجلد المشروع شغّل:

```bash
docker compose build
docker compose up -d
```

في أول تشغيل، حاوية `web` تقوم تلقائيًا بـ:

- انتظار MySQL حتى يصبح جاهزًا
- تنفيذ `migrate`
- تنفيذ `collectstatic`
- تشغيل Gunicorn

## 4) إنشاء حساب مشرف

```bash
docker compose exec web python manage.py createsuperuser
```

## 5) التحقق من الخدمات

```bash
docker compose ps
docker compose logs -f web
docker compose logs -f nginx
docker compose logs -f db
```

## 6) التحديث بعد رفع كود جديد

```bash
git pull
docker compose down
docker compose up -d --build
```

## 7) الملفات الدائمة (Persistent Data)

يتم حفظ البيانات التالية داخل Docker Volumes:

- `mysql_data` لقاعدة البيانات
- `static_volume` لملفات `staticfiles`
- `media_volume` لملفات `media`
- `logs_volume` لسجلات التطبيق

## 8) الوصول من المتصفح

- التطبيق عبر Nginx: `http://YOUR_SERVER_IP`
- لوحة الإدارة: `http://YOUR_SERVER_IP/admin/`

## 9) ملاحظات مهمة

- الإعداد الحالي يشغل Nginx على المنفذ `80`.
- إذا أردت HTTPS، أضف شهادة SSL داخل Nginx أو ضع المشروع خلف Reverse Proxy خارجي.
- لا ترفع ملف `.env` إلى GitHub.
- إذا غيّرت أي متغيرات بيئة، أعد تشغيل الخدمات:

```bash
docker compose down
docker compose up -d
```
