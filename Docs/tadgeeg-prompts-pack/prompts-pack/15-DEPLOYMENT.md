# 15 - النشر والـ DevOps (Deployment & DevOps)

> **الهدف:** prompts لنشر تدقيق على السيرفر (Docker, Nginx, Gunicorn, Celery, Redis, SSL) والصيانة والمراقبة.

---

## 📋 ملاحظة قبل البدء

المشروع يحتوي على scripts نشر جاهزة في:
```
deployment/
├── 00_setup_server.sh
├── 01_install_dependencies.sh
├── 02_setup_postgres.sh
├── 03_setup_redis.sh
├── 04_setup_nginx.sh
├── 05_setup_gunicorn.sh
├── 06_setup_celery.sh
├── 07_setup_ssl.sh
└── 08_deploy.sh
```

استخدم هذه السكريبتات كنقطة بداية وعدّلها حسب الحاجة.

---

## 🐳 Prompt 15.1: Dockerfile محدّث للإنتاج

```
أنشئ Dockerfile متعدد المراحل (multi-stage) محسّن للإنتاج لمشروع تدقيق:

المتطلبات:
- Python 3.11-slim كقاعدة
- Stage 1 (builder): تثبيت dependencies + collectstatic
- Stage 2 (runtime): نسخ فقط الملفات الضرورية
- مستخدم غير-root اسمه `tadgeeg`
- WORKDIR=/app
- تثبيت Tesseract OCR + Arabic language pack
- تثبيت poppler-utils (لتحويل PDF)
- تثبيت weasyprint dependencies (للـ PDF reports)
- HEALTHCHECK يفحص /health/
- EXPOSE 8000
- CMD: gunicorn finai_backend.wsgi:application

أيضاً أنشئ:
- .dockerignore (يستثني .git, __pycache__, venv, node_modules, *.pyc, media/, staticfiles/)
- docker-compose.yml للإنتاج مع: web (Django), celery_worker, celery_beat, redis, postgres, nginx
- docker-compose.dev.yml للتطوير
- entrypoint.sh: ينتظر postgres + redis، يعمل migrate + collectstatic، ثم يشغّل gunicorn

اعطني الملفات كاملة جاهزة للاستخدام.
```

---

## 🌐 Prompt 15.2: Nginx Configuration

```
أنشئ ملف إعداد Nginx كامل لتدقيق على المسار `/etc/nginx/sites-available/tadgeeg`:

المتطلبات:
- Server block للدومين tadgeeg.com + www.tadgeeg.com
- إعادة توجيه HTTP → HTTPS
- SSL بـ Let's Encrypt (شهادة في /etc/letsencrypt/live/tadgeeg.com/)
- HTTP/2 enabled
- Gzip compression للنصوص + JSON + CSS + JS
- Client max body size = 50MB (للـ uploads)
- Proxy إلى Gunicorn على unix socket (/run/gunicorn/tadgeeg.sock)
- /static/ → /var/www/tadgeeg/staticfiles/ مع cache headers طويلة
- /media/ → /var/www/tadgeeg/media/ مع authentication check
- WebSocket support (للـ /ws/notifications/)
- Rate limiting: 10 req/sec للـ /api/, 5 req/min للـ /api/auth/login/
- Security headers: HSTS, X-Frame-Options, X-Content-Type-Options, CSP, Referrer-Policy
- لوج خاص في /var/log/nginx/tadgeeg-access.log و tadgeeg-error.log

اعطني الملف كاملاً + سكريبت تفعيله (ln -s + nginx -t + reload).
```

---

## 🦄 Prompt 15.3: Gunicorn + systemd

```
أنشئ إعداد Gunicorn كامل لتدقيق:

الملفات المطلوبة:
1. `/etc/systemd/system/gunicorn-tadgeeg.service` - service file
2. `/etc/systemd/system/gunicorn-tadgeeg.socket` - socket file (للـ unix socket)
3. `gunicorn.conf.py` في جذر المشروع

في gunicorn.conf.py:
- bind = "unix:/run/gunicorn/tadgeeg.sock"
- workers = (CPU count * 2) + 1
- worker_class = "gevent" (لدعم WebSockets/الطلبات الطويلة)
- worker_connections = 1000
- max_requests = 1000 + max_requests_jitter = 50 (لإعادة تشغيل العمال دورياً)
- timeout = 120
- keepalive = 5
- preload_app = True
- accesslog = "/var/log/gunicorn/tadgeeg-access.log"
- errorlog = "/var/log/gunicorn/tadgeeg-error.log"
- loglevel = "info"

في systemd service:
- User=tadgeeg, Group=www-data
- WorkingDirectory=/var/www/tadgeeg
- Environment="DJANGO_SETTINGS_MODULE=finai_backend.settings"
- EnvironmentFile=/var/www/tadgeeg/.env.production
- ExecStart=/var/www/tadgeeg/venv/bin/gunicorn -c gunicorn.conf.py finai_backend.wsgi:application
- Restart=always, RestartSec=5

اعطني الملفات + الأوامر لتفعيلها.
```

---

## 🌿 Prompt 15.4: Celery Workers + Beat (Production)

```
أنشئ إعداد Celery production-grade لتدقيق:

الملفات:
1. `/etc/systemd/system/celery-tadgeeg.service` - workers
2. `/etc/systemd/system/celerybeat-tadgeeg.service` - scheduler
3. `/etc/conf.d/celery-tadgeeg` - environment variables

في celery.service:
- 3 workers مختلفة بـ queues:
  * worker-default (queue=default, concurrency=4) - مهام عامة
  * worker-ocr (queue=ocr, concurrency=2) - معالجة OCR ثقيلة
  * worker-reports (queue=reports, concurrency=2) - توليد PDF
- استخدم --max-memory-per-child=300000 (300MB) لإعادة تشغيل العامل عند تجاوز الذاكرة
- استخدم --max-tasks-per-child=100 لتجنب memory leaks
- لوج: /var/log/celery/tadgeeg-%n%I.log

في celerybeat.service:
- DatabaseScheduler (django_celery_beat)
- لوج: /var/log/celery/tadgeeg-beat.log
- pid file: /var/run/celery/tadgeeg-beat.pid

أيضاً أعدّ مهام دورية في `apps/core/tasks.py`:
- cleanup_expired_sessions كل ساعة
- send_daily_audit_summary كل يوم 8 صباحاً
- generate_monthly_compliance_report أول كل شهر
- delete_soft_deleted_records_older_than_30days يومياً منتصف الليل
- check_subscription_expiry يومياً 9 صباحاً

اعطني الملفات + كود المهام + التسجيل في django_celery_beat.
```

---

## 🔒 Prompt 15.5: SSL + Security Hardening

```
أنشئ سكريبت bash كامل `secure-server.sh` لتأمين سيرفر تدقيق (Ubuntu 22.04):

الخطوات:
1. تحديث النظام: apt update && apt upgrade -y
2. تثبيت ufw وفتح: 22 (ssh), 80, 443 فقط، رفض الباقي
3. تثبيت fail2ban + إعداد jail لـ ssh و nginx
4. تثبيت certbot + الحصول على شهادة SSL لـ tadgeeg.com
5. إعداد auto-renewal: cron job يجدد الشهادة كل شهر
6. تعطيل root login عبر SSH (PermitRootLogin no)
7. تغيير منفذ SSH من 22 إلى 2222 (اختياري)
8. تثبيت unattended-upgrades للتحديثات الأمنية التلقائية
9. إنشاء مستخدم tadgeeg + إضافته لمجموعة sudo + www-data
10. إعداد .ssh/authorized_keys مع المفتاح العام
11. تعطيل password authentication في sshd
12. إعداد ClamAV لفحص الملفات المرفوعة (uploads)

أيضاً:
- إعدادات security في settings.py للإنتاج:
  * SECURE_SSL_REDIRECT = True
  * SESSION_COOKIE_SECURE = True
  * CSRF_COOKIE_SECURE = True
  * SECURE_HSTS_SECONDS = 31536000
  * SECURE_HSTS_INCLUDE_SUBDOMAINS = True
  * SECURE_HSTS_PRELOAD = True
  * SECURE_CONTENT_TYPE_NOSNIFF = True
  * SECURE_BROWSER_XSS_FILTER = True
  * X_FRAME_OPTIONS = "DENY"

اعطني السكريبت كاملاً + checklist للتشغيل.
```

---

## 📊 Prompt 15.6: Monitoring + Logging (Sentry, Prometheus, Grafana)

```
أعدّ نظام مراقبة كامل لتدقيق:

1. **Sentry** (تتبع الأخطاء):
   - أضف sentry-sdk[django, celery, redis] إلى requirements.txt
   - إعداد في settings.py مع DSN من env
   - تفعيل tracing (10% sample rate)
   - تفعيل profiling
   - فلترة بيانات حساسة (passwords, tokens) قبل الإرسال
   - tag كل event بـ organization_id

2. **Prometheus + django-prometheus**:
   - إضافة `django_prometheus` للـ INSTALLED_APPS
   - إضافة middleware في البداية والنهاية
   - عمل expose لـ /metrics/ endpoint (محمي بـ admin-only)
   - metrics مخصصة:
     * tadgeeg_invoices_processed_total
     * tadgeeg_audit_violations_detected_total
     * tadgeeg_ocr_processing_seconds (histogram)
     * tadgeeg_active_users (gauge)

3. **Grafana dashboard** (JSON):
   - panel: عدد الفواتير المعالجة (آخر 24 ساعة)
   - panel: زمن الاستجابة (P50, P95, P99)
   - panel: Error rate
   - panel: Celery queue lengths
   - panel: Database connection pool
   - panel: Redis memory usage

4. **Structured logging** (JSON):
   - python-json-logger في requirements
   - LOGGING في settings.py مع formatter JSON
   - كل log يحوي: timestamp, level, logger, message, organization_id, user_id, request_id
   - إرسال لـ /var/log/tadgeeg/app.log
   - rotation: 100MB max, 10 ملفات

5. **Healthcheck endpoints** في core/views.py:
   - /health/ - basic (200 OK)
   - /health/db/ - يفحص DB connection
   - /health/redis/ - يفحص Redis
   - /health/celery/ - يفحص Celery (يرسل ping task)
   - /health/full/ - كل الفحوصات

اعطني الكود الكامل.
```

---

## 💾 Prompt 15.7: Backup + Disaster Recovery

```
أنشئ نظام نسخ احتياطي شامل لتدقيق:

1. **سكريبت backup يومي** `/usr/local/bin/tadgeeg-backup.sh`:
   - PostgreSQL dump (pg_dump --format=custom --compress=9)
   - نسخ media/ folder
   - نسخ .env.production
   - تشفير النسخة بـ GPG
   - رفع لـ S3 / Backblaze B2 / DigitalOcean Spaces
   - الاحتفاظ بآخر 30 نسخة يومية + 12 نسخة شهرية + 7 نسخ أسبوعية
   - إرسال notification لـ Slack/Email عند النجاح/الفشل

2. **cron job**:
   - يومياً 2:00 صباحاً
   - تنظيف النسخ القديمة كل أسبوع

3. **سكريبت restore** `/usr/local/bin/tadgeeg-restore.sh`:
   - يأخذ اسم النسخة كـ argument
   - يحمّل من S3
   - يفك التشفير
   - يعمل drop + create للـ DB
   - يعمل pg_restore
   - يستعيد media/
   - يعيد تشغيل services

4. **Disaster Recovery Plan** (markdown):
   - RPO (Recovery Point Objective): 24 ساعة
   - RTO (Recovery Time Objective): 4 ساعات
   - خطوات الاستعادة الكاملة (سيرفر جديد من الصفر)
   - جهات الاتصال للطوارئ
   - checklist تجربة الاستعادة شهرياً

5. **Database replication** (اختياري):
   - إعداد PostgreSQL streaming replication
   - master في الرياض، replica في جدة (مثلاً)
   - failover script

اعطني السكريبتات + الوثائق.
```

---

## 🚀 Prompt 15.8: CI/CD Pipeline (GitHub Actions)

```
أنشئ GitHub Actions pipeline كامل لتدقيق `.github/workflows/`:

1. **`ci.yml`** (يعمل عند كل PR):
   - Job 1: lint
     * black --check
     * isort --check
     * flake8
     * bandit (security check)
   - Job 2: test
     * setup PostgreSQL service
     * setup Redis service
     * تثبيت dependencies
     * تشغيل migrations
     * pytest --cov=apps --cov-report=xml
     * upload coverage to Codecov
   - Job 3: type-check
     * mypy apps/
   - Job 4: build-docker
     * docker build (no push, just verify)

2. **`deploy-staging.yml`** (يعمل عند push على main):
   - يبني Docker image
   - يرفعها لـ GitHub Container Registry
   - SSH للسيرفر staging.tadgeeg.com
   - يسحب الصورة الجديدة
   - يعمل migrate + collectstatic
   - يعيد تشغيل containers
   - smoke tests على /health/
   - Slack notification

3. **`deploy-production.yml`** (يعمل يدوياً أو عند tag v*):
   - نفس staging لكن:
   - يتطلب approval من مراجع
   - يعمل DB backup قبل النشر
   - blue-green deployment
   - rollback تلقائي إذا فشل healthcheck

4. **`security-scan.yml`** (يعمل أسبوعياً):
   - safety check (Python dependencies)
   - npm audit (Node dependencies)
   - trivy scan (Docker image)
   - يفتح GitHub issue إذا وجد ثغرات

5. **`backup-test.yml`** (شهرياً):
   - يحمّل آخر backup
   - يستعيده على environment اختبار
   - يشغّل smoke tests
   - يبلّغ Slack بالنتيجة

اعطني الملفات كاملة + secrets المطلوبة في GitHub.
```

---

## 🔧 Prompt 15.9: Environment Variables Management

```
أنشئ نظام إدارة متغيرات بيئة محكم لتدقيق:

1. **`.env.example`** (في الريبو، جميع المتغيرات بقيم وهمية):
```
# Django
DJANGO_SECRET_KEY=change-me
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=tadgeeg.com,www.tadgeeg.com
DJANGO_SETTINGS_MODULE=finai_backend.settings.production

# Database
DATABASE_URL=postgresql://user:pass@localhost:5432/tadgeeg

# Redis
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2

# OpenAI
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o
OPENAI_MAX_RETRIES=3

# Email
EMAIL_HOST=smtp.sendgrid.net
EMAIL_PORT=587
EMAIL_HOST_USER=apikey
EMAIL_HOST_PASSWORD=SG...
DEFAULT_FROM_EMAIL=noreply@tadgeeg.com

# Storage (S3)
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_STORAGE_BUCKET_NAME=tadgeeg-media
AWS_S3_REGION_NAME=me-south-1

# Sentry
SENTRY_DSN=https://...

# Tadgeeg Branding
PRODUCT_NAME=Tadgeeg AI
COMPANY_NAME=Get Solution Company
SUPPORT_EMAIL=support@tadgeeg.com

# Security
ALLOWED_CIDR_NETS=10.0.0.0/8
SECURE_SSL_REDIRECT=True

# ZATCA
ZATCA_API_URL=https://gw-fatoora.zatca.gov.sa
ZATCA_CERT_PATH=/secrets/zatca-cert.pem
```

2. **سكريبت validation** `scripts/check_env.py`:
   - يقرأ .env.example
   - يفحص أن كل المتغيرات موجودة في .env الفعلي
   - يفحص ألا توجد قيم وهمية في الإنتاج
   - يطبع تقرير

3. **استخدام django-environ**:
   - تحديث settings.py لاستخدام environ.Env
   - فصل settings/ إلى:
     * base.py - مشترك
     * development.py - تطوير
     * production.py - إنتاج
     * testing.py - اختبارات

4. **Secrets management**:
   - في الإنتاج: AWS Secrets Manager / HashiCorp Vault
   - سكريبت `load_secrets.sh` يجلب من Vault ويحول لـ env vars
   - أبداً لا تضع .env في git

اعطني الملفات + الإعدادات.
```

---

## 📦 Prompt 15.10: Zero-Downtime Deployment Script

```
أنشئ سكريبت deployment ذكي بدون توقف للخدمة `deployment/deploy.sh`:

الخطوات:
1. **Pre-flight checks**:
   - فحص مساحة القرص (>5GB متاح)
   - فحص الذاكرة (>1GB متاح)
   - فحص أن الـ branch هو main
   - فحص أن tests نجحت في CI

2. **Backup**:
   - أخذ snapshot من DB
   - tag نسخة Docker الحالية كـ "rollback-{timestamp}"

3. **Pull + Build**:
   - git pull origin main
   - docker compose build --no-cache web

4. **Migrate**:
   - تشغيل migrations في container منفصل
   - فحص أن migrations آمنة (لا تحذف عمود مستخدم)
   - فشل = إيقاف النشر

5. **Rolling update**:
   - تشغيل instance جديد على بورت مختلف
   - فحص /health/full/
   - تحديث Nginx upstream لتوجيه التراف للجديد
   - إيقاف الـ instance القديم
   - تكرار للـ Celery workers

6. **Post-deploy**:
   - collectstatic
   - clear cache (Redis FLUSHDB حذرة)
   - warm up cache (طلبات لأهم الصفحات)
   - smoke tests

7. **Rollback** (إذا فشل أي شيء):
   - استعادة Docker image القديمة
   - استعادة DB من snapshot
   - إعادة تشغيل services
   - تنبيه فوري للفريق

8. **Notifications**:
   - Slack: بدء النشر، نجاح، فشل
   - Sentry release tracking
   - تحديث statuspage.io

اعطني السكريبت كاملاً + توثيق الاستخدام.
```

---

## 🧪 Prompt 15.11: Load Testing + Performance

```
أنشئ سيناريوهات اختبار حمل لتدقيق باستخدام Locust:

1. **`locustfile.py`**:
```python
from locust import HttpUser, task, between

class TadgeegUser(HttpUser):
    wait_time = between(1, 3)
    
    def on_start(self):
        # تسجيل دخول
        self.client.post("/api/auth/login/", json={
            "email": "test@tadgeeg.com",
            "password": "..."
        })
    
    @task(3)
    def view_dashboard(self):
        self.client.get("/dashboard/")
    
    @task(2)
    def list_invoices(self):
        self.client.get("/api/invoices/?page=1")
    
    @task(1)
    def upload_invoice(self):
        with open("tests/fixtures/invoice.pdf", "rb") as f:
            self.client.post("/api/invoices/upload/", files={"file": f})
    
    @task(1)
    def view_reports(self):
        self.client.get("/reports/dashboard/")
```

2. **سيناريوهات**:
   - smoke: 10 users لمدة دقيقتين (هل يعمل أصلاً؟)
   - load: 100 users لمدة 15 دقيقة (الحمل المعتاد)
   - stress: 500 users لمدة 30 دقيقة (الحد الأقصى)
   - spike: من 10 إلى 200 users فجأة (Black Friday سيناريو)
   - soak: 50 users لمدة 4 ساعات (تسريب ذاكرة؟)

3. **Performance targets**:
   - P95 response time < 500ms للصفحات
   - P95 < 200ms للـ API
   - Error rate < 0.1%
   - 99.9% uptime

4. **سكريبت تشغيل** `run_load_tests.sh`:
   - يشغل locust headless
   - يولد تقرير HTML
   - يقارن النتائج بالـ baseline
   - يفشل إذا تجاوز الحدود

5. **تحسينات بعد الاختبار**:
   - فهرسة DB queries بطيئة (django-silk أو django-debug-toolbar)
   - إضافة caching (Redis) للـ queries المتكررة
   - استخدام select_related + prefetch_related
   - تفعيل CDN للـ static files
   - تحسين queries في اللوحات (dashboards)

اعطني الكود + سكريبتات التشغيل + تقرير نموذجي.
```

---

## ✅ Checklist النشر للإنتاج

قبل نشر تدقيق على الإنتاج، تأكد من:

### الأمان
- [ ] DEBUG=False
- [ ] SECRET_KEY قوي (50+ حرف عشوائي)
- [ ] ALLOWED_HOSTS محدد
- [ ] HTTPS مفعّل بشهادة صالحة
- [ ] CSRF + Session cookies آمنة
- [ ] HSTS header مفعّل
- [ ] Rate limiting على endpoints حساسة
- [ ] CORS محدود لدومينات معروفة
- [ ] لا توجد passwords في git history
- [ ] firewall (ufw) مفعّل، فقط 80/443/22
- [ ] fail2ban مفعّل
- [ ] SSH keys فقط (لا passwords)

### الأداء
- [ ] PostgreSQL محسّن (shared_buffers, work_mem)
- [ ] Redis caching مفعّل
- [ ] Static files على CDN أو Nginx
- [ ] Media files على S3
- [ ] Gzip مفعّل في Nginx
- [ ] Database indexes في الأماكن الصحيحة
- [ ] N+1 queries مفحوصة (django-silk)

### الموثوقية
- [ ] Daily backups تعمل
- [ ] Restore tested شهرياً
- [ ] Sentry مفعّل
- [ ] Healthcheck endpoints تعمل
- [ ] Monitoring dashboard (Grafana)
- [ ] Alerts على Slack/Email عند الأخطاء
- [ ] Rollback plan موثّق
- [ ] Log rotation مفعّل

### الامتثال
- [ ] Terms of Service + Privacy Policy منشورة
- [ ] GDPR compliance (data export + delete)
- [ ] ZATCA Phase 2 مفعّل
- [ ] Audit logs محفوظة لـ 7 سنوات
- [ ] Data retention policy موثّقة
- [ ] DPA (Data Processing Agreement) مع AWS/Vendors

### العمليات
- [ ] Runbook لكل عملية متكررة
- [ ] On-call rotation محدد
- [ ] Incident response plan
- [ ] Post-mortem template جاهز
- [ ] Status page (status.tadgeeg.com)
- [ ] Documentation محدّث

---

## 🎯 الخطوة التالية

🎉 **مبروك! انتهيت من حزمة البرمت كاملة.**

الآن لديك:
- ✅ 16 ملف يغطي كل جوانب المشروع
- ✅ +100 prompt جاهز للاستخدام
- ✅ تعليمات واضحة + كود نموذجي
- ✅ checklists للجودة

**خطة عمل مقترحة:**
1. ابدأ بـ `00-PROJECT-CONTEXT.md` لتجهيز السياق
2. ثم `01-BRANDING-IDENTITY.md` لتطبيق الهوية البصرية
3. ثم `02-LANDING-PAGE.md` للصفحة الرئيسية (الأهم بصرياً)
4. ثم `03-AUTH-PAGES.md` ثم `04-DASHBOARD.md`
5. باقي الملفات حسب الأولوية

**نصائح أخيرة:**
- 📌 احفظ نسخة من المشروع قبل أي تغيير كبير
- 📌 اعمل branch جديد لكل feature
- 📌 شغّل tests بعد كل تغيير
- 📌 راجع الـ git diff قبل الـ commit
- 📌 لا تنسخ كود AI بشكل أعمى - افهمه أولاً

**بالتوفيق مع تدقيق! 🚀**

---

> _"الجودة ليست عملاً، بل عادة." - أرسطو_

