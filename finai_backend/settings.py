"""
Tadgeeg AI by Get Solution Company
Django Settings
"""

import os
import sys
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv
from core.utils.database import build_default_database, build_test_database

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# ─── Sentry Error Tracking ───────────────────────────────────────────────────
try:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration
    from sentry_sdk.integrations.celery import CeleryIntegration

    sentry_dsn = os.environ.get("SENTRY_DSN", "").strip()
    if sentry_dsn:
        sentry_sdk.init(
            dsn=sentry_dsn,
            integrations=[
                DjangoIntegration(),
                CeleryIntegration(),
            ],
            traces_sample_rate=0.1,  # 10% transaction sampling
            send_default_pii=False,  # Don't send user email in errors
            environment=os.environ.get("ENVIRONMENT", "development"),
        )
except ImportError:
    pass  # Sentry not installed, error tracking disabled

PRODUCT_NAME = "Tadgeeg AI"
COMPANY_NAME = "Get Solution Company"
COMPANY_NAME_AR = "شركة Get Solution"
PRODUCT_TAGLINE_AR = "منصة الذكاء الاصطناعي للتدقيق المالي والامتثال"
PRODUCT_TAGLINE_EN = "AI platform for financial auditing and compliance"
PRODUCT_DESCRIPTION_AR = "منصة الذكاء الاصطناعي الرائدة للتدقيق المالي والامتثال"
PRODUCT_DESCRIPTION_EN = "Leading AI platform for financial auditing and compliance"

LOG_DIR = Path(os.environ.get("DJANGO_LOG_DIR", BASE_DIR / "logs"))
if not LOG_DIR.is_absolute():
    LOG_DIR = BASE_DIR / LOG_DIR

LOG_FILE = LOG_DIR / "finai.log"
FILE_LOGGING_ENABLED = False

try:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8"):
        pass
    FILE_LOGGING_ENABLED = os.access(LOG_FILE, os.W_OK)
except OSError:
    FILE_LOGGING_ENABLED = False
_SECRET_KEY_FALLBACK = "change-me-in-production-use-long-random-string"
SECRET_KEY = os.environ.get(
    "SECRET_KEY",
    os.environ.get("DJANGO_SECRET_KEY", _SECRET_KEY_FALLBACK),
)

DEBUG = os.environ.get("DEBUG", "True") == "True"

# ── Production safety guards ────────────────────────────────────────────────
# Raise hard errors if dangerous defaults are used outside local development.
_is_local = set(os.environ.get("ALLOWED_HOSTS", "localhost").split(",")) <= {
    "localhost", "127.0.0.1", "testserver", ""
}
if not DEBUG and not _is_local:
    if SECRET_KEY == _SECRET_KEY_FALLBACK:
        raise RuntimeError(
            "FATAL: SECRET_KEY is using the insecure default value. "
            "Set a strong SECRET_KEY in your .env file before deploying."
        )
# ─────────────────────────────────────────────────────────────────────────────

ALLOWED_HOSTS = [host.strip() for host in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if host.strip()]
for default_host in ("testserver", "localhost", "127.0.0.1"):
    if default_host not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(default_host)

CSRF_TRUSTED_ORIGINS_RAW = os.environ.get("CSRF_TRUSTED_ORIGINS", "").strip()
if CSRF_TRUSTED_ORIGINS_RAW:
    CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in CSRF_TRUSTED_ORIGINS_RAW.split(",") if origin.strip()]

USE_X_FORWARDED_HOST = os.environ.get("USE_X_FORWARDED_HOST", "False") == "True"
USE_X_FORWARDED_PORT = os.environ.get("USE_X_FORWARDED_PORT", "False") == "True"

if os.environ.get("ENABLE_SECURE_PROXY_SSL_HEADER", "False") == "True":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# ─── Apps ────────────────────────────────────────────────────────────────────
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "channels",
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "drf_spectacular",
]

LOCAL_APPS = [
    "apps.authentication",
    "apps.documents",
    "apps.transactions",
    "apps.audit",
    "apps.reports",
    "apps.analytics",
    "apps.compliance",
    "apps.invoices",
    "apps.frontend",
    "apps.auditing",
    "apps.rule_engine",
]

# ─── Rule Engine Settings ──────────────────────────────────────────────────────
ALLOWED_RULE_MODULES = ["apps.rule_engine.rules"]
USE_NEW_RULE_ENGINE = True  # Feature flag: False = old AuditEngine, True = new AuditPipeline

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# ─── Middleware ───────────────────────────────────────────────────────────────
MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "core.utils.admin_security.AdminSecurityMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "core.utils.security_headers.SecurityHeadersMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.utils.rate_limit.OrgRateLimitMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.utils.middleware.AuditTrailMiddleware",
    "core.utils.middleware.RequestTimingMiddleware",
    # NOTE: SecurityHeadersMiddleware is already applied at position 4
    # via core.utils.security_headers.SecurityHeadersMiddleware — removed duplicate here.
]

ROOT_URLCONF = "finai_backend.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "django.template.context_processors.i18n",
                "core.context_processors.branding",
            ],
        },
    },
]

WSGI_APPLICATION = "finai_backend.wsgi.application"
ASGI_APPLICATION = "finai_backend.asgi.application"

CHANNEL_REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [CHANNEL_REDIS_URL]},
    }
}

# ─── Database ─────────────────────────────────────────────────────────────────
_RUNNING_PYTEST = "pytest" in Path(sys.argv[0]).name.lower() or "pytest" in sys.modules
if _RUNNING_PYTEST:
    DATABASE_BACKEND, _default_database = build_test_database(BASE_DIR, os.environ)
else:
    DATABASE_BACKEND, _default_database = build_default_database(BASE_DIR, os.environ)
DATABASES = {"default": _default_database}

# ─── Auth ─────────────────────────────────────────────────────────────────────
AUTH_USER_MODEL = "authentication.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ─── Internationalization ─────────────────────────────────────────────────────
LANGUAGE_CODE = "ar"
LANGUAGES = [
    ("ar", "Arabic"),
]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "Asia/Riyadh"
USE_I18N = True
USE_TZ = True

# ─── Static / Media ───────────────────────────────────────────────────────────
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
STATIC_ROOT.mkdir(parents=True, exist_ok=True)
MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
(BASE_DIR / "static").mkdir(parents=True, exist_ok=True)

if not DEBUG:
    STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# ─── S3 / Cloud Media Storage (NFR-2) ─────────────────────────────────────────
# Set AWS_STORAGE_BUCKET_NAME in your .env to enable S3 for media uploads.
# Leave unset to use local filesystem storage (default for dev).
_AWS_BUCKET = os.environ.get("AWS_STORAGE_BUCKET_NAME", "")
if _AWS_BUCKET:
    DEFAULT_FILE_STORAGE = "storages.backends.s3boto3.S3Boto3Storage"
    AWS_STORAGE_BUCKET_NAME = _AWS_BUCKET
    AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID", "")
    AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
    AWS_S3_REGION_NAME = os.environ.get("AWS_S3_REGION_NAME", "me-south-1")  # Bahrain (closest to KSA)
    AWS_S3_FILE_OVERWRITE = False
    AWS_DEFAULT_ACL = None  # Use bucket policy
    AWS_S3_CUSTOM_DOMAIN = os.environ.get("AWS_S3_CUSTOM_DOMAIN", "")
    AWS_QUERYSTRING_AUTH = False  # Public read via bucket policy
    MEDIA_URL = f"https://{AWS_S3_CUSTOM_DOMAIN or f'{_AWS_BUCKET}.s3.amazonaws.com'}/"

SESSION_COOKIE_AGE = 60 * 30
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_SAVE_EVERY_REQUEST = True
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "31536000" if not DEBUG else "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = os.environ.get("SECURE_HSTS_INCLUDE_SUBDOMAINS", "True" if not DEBUG else "False") == "True"
SECURE_HSTS_PRELOAD = os.environ.get("SECURE_HSTS_PRELOAD", "True" if not DEBUG else "False") == "True"
SECURE_BROWSER_XSS_FILTER = True
HEALTH_REDIS_REQUIRED = os.environ.get("HEALTH_REDIS_REQUIRED", "False") == "True"

SECURE_SSL_REDIRECT = os.environ.get("SECURE_SSL_REDIRECT", "True" if not DEBUG else "False") == "True"

if not DEBUG:
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

cache_url = os.environ.get("CACHE_URL")
use_redis_cache = os.environ.get("USE_REDIS_CACHE", "").strip().lower() in {"1", "true", "yes", "on"}

if cache_url or use_redis_cache:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": cache_url or os.environ.get("REDIS_URL", "redis://localhost:6379/1"),
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "finai-local-cache",
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ─── DRF ─────────────────────────────────────────────────────────────────────
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "core.utils.jwt_cookie_auth.JWTCookieAuthentication",
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_PAGINATION_CLASS": "core.utils.pagination.StandardResultsSetPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "100/day",
        "user": "1000/day",
    },
    "DEFAULT_VERSIONING_CLASS": "rest_framework.versioning.AcceptHeaderVersioning",
    "ALLOWED_VERSIONS": ["1.0", "1.1", "2.0"],
    "VERSION_PARAM": "version",
    "DEFAULT_VERSION": "1.0",
    "EXCEPTION_HANDLER": "core.utils.exceptions.custom_exception_handler",
}

RATE_LIMITS = {
    "upload": (20, 60),
    "ai": (10, 60),
    "api": (300, 60),
    "default": (500, 60),
}

# ─── JWT ──────────────────────────────────────────────────────────────────────
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=1),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "ALGORITHM": "HS256",
    "AUTH_HEADER_TYPES": ("Bearer",),
}

# JWT Cookie settings
JWT_AUTH_COOKIE = "fin_access"
JWT_AUTH_REFRESH_COOKIE = "fin_refresh"
JWT_AUTH_COOKIE_SAMESITE = "Lax"
JWT_AUTH_COOKIE_SECURE = not DEBUG
JWT_AUTH_COOKIE_HTTP_ONLY = True

SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

# ─── CORS ─────────────────────────────────────────────────────────────────────
_default_cors = "http://localhost:3000,http://localhost:5173"
if not DEBUG:
    # Build CORS origins from ALLOWED_HOSTS automatically for production
    _hosts = os.environ.get("ALLOWED_HOSTS", "")
    _prod_origins = ",".join(
        f"https://{h.strip()}" for h in _hosts.split(",")
        if h.strip() and not h.strip() in ("localhost", "127.0.0.1")
    )
    _default_cors = _prod_origins or _default_cors

CORS_ALLOWED_ORIGINS = os.environ.get("CORS_ALLOWED_ORIGINS", _default_cors).split(",")
CORS_ALLOW_CREDENTIALS = True

# ─── OpenAPI / Spectacular ────────────────────────────────────────────────────
SPECTACULAR_SETTINGS = {
    "TITLE": f"{PRODUCT_NAME} API",
    "DESCRIPTION": f"REST API for {PRODUCT_NAME} by {COMPANY_NAME}",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "CONTACT": {"email": "support@tadgeeg.com"},
    "LICENSE": {"name": "Proprietary"},
    "TAGS": [
        {"name": "Auth", "description": "Authentication & user management"},
        {"name": "Documents", "description": "Document upload & OCR processing"},
        {"name": "Transactions", "description": "Financial transaction management"},
        {"name": "Audit", "description": "Audit cases & workflow"},
        {"name": "Analytics", "description": "AI anomaly detection & analytics"},
        {"name": "Compliance", "description": "Regulatory compliance checking"},
        {"name": "Reports", "description": "Audit report generation"},
    ],
}

# ─── Celery ───────────────────────────────────────────────────────────────────
CELERY_BROKER_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
# LOCAL DEV: run tasks synchronously when CELERY_TASK_ALWAYS_EAGER=True in .env
CELERY_TASK_ALWAYS_EAGER = os.environ.get("CELERY_TASK_ALWAYS_EAGER", "False") == "True"
CELERY_TASK_EAGER_PROPAGATES = CELERY_TASK_ALWAYS_EAGER

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", "")

# ─── Email ────────────────────────────────────────────────────────────────────
# Falls back to console backend in production if SMTP is not configured,
# so missing email config never silently swallows errors.
_email_user = os.environ.get("EMAIL_HOST_USER", "")
_email_pass = os.environ.get("EMAIL_HOST_PASSWORD", "")
_email_configured = bool(_email_user and _email_pass)

if _email_configured:
    EMAIL_BACKEND = os.environ.get(
        "EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend"
    )
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

EMAIL_HOST          = os.environ.get("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT          = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER     = _email_user
EMAIL_HOST_PASSWORD = _email_pass
EMAIL_USE_TLS       = os.environ.get("EMAIL_USE_TLS", "True") == "True"
DEFAULT_FROM_EMAIL  = os.environ.get("DEFAULT_FROM_EMAIL", _email_user or "noreply@tadgeeg.com")
SITE_URL            = os.environ.get("SITE_URL", f"https://tadgeeg.com" if not DEBUG else "http://localhost:8000")
WASSLA_EMAIL_ASYNC_ENABLED = os.environ.get("WASSLA_EMAIL_ASYNC_ENABLED", "False") == "True"

from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    "nightly-anomaly-scan": {
        "task": "documents.run_nightly_anomaly_scan",
        "schedule": crontab(hour=2, minute=0),   # 2:00 AM daily (Asia/Riyadh)
    },
    "weekly-kpi-report": {
        "task": "documents.generate_weekly_kpi_report",
        "schedule": crontab(hour=6, minute=0, day_of_week=1),  # Monday 6 AM
    },
    "weekly-audit-summary": {
        "task": "audit.run_weekly_audit_summary",
        "schedule": crontab(hour=9, minute=0, day_of_week=1),  # Monday 9 AM
    },
}

# ─── OpenAI ───────────────────────────────────────────────────────────────────
OPENAI_API_KEY    = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL      = os.environ.get("OPENAI_MODEL", "gpt-4o")
OPENAI_MAX_TOKENS = int(os.environ.get("OPENAI_MAX_TOKENS", "4096"))
OPENAI_TIMEOUT    = int(os.environ.get("OPENAI_TIMEOUT", "30"))

if not DEBUG and not OPENAI_API_KEY:
    import warnings
    warnings.warn("OPENAI_API_KEY is not set — AI features will be disabled", RuntimeWarning)

# ─── Tesseract OCR ────────────────────────────────────────────────────────────
TESSERACT_CMD = os.environ.get("TESSERACT_CMD", "/usr/bin/tesseract")
TESSERACT_LANGUAGES = os.environ.get("TESSERACT_LANGUAGES", "ara+eng")

# ─── File Upload ──────────────────────────────────────────────────────────────
ALLOWED_UPLOAD_EXTENSIONS = [
    # Images
    ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".webp",
    # Documents
    ".pdf",
    # Archives
    ".zip",
    # Spreadsheets
    ".xls", ".xlsx", ".xlsm",
    # Data files
    ".csv", ".tsv",
    # Structured data
    ".json", ".jsonl",
]
MAX_UPLOAD_SIZE_MB      = int(os.environ.get("MAX_UPLOAD_SIZE_MB", "50"))
MAX_UPLOAD_SIZE         = MAX_UPLOAD_SIZE_MB * 1024 * 1024
MAX_ZIP_UPLOAD_SIZE_MB  = int(os.environ.get("MAX_ZIP_UPLOAD_SIZE_MB", "200"))
MAX_ZIP_UPLOAD_SIZE     = MAX_ZIP_UPLOAD_SIZE_MB * 1024 * 1024

# ─── Logging ─────────────────────────────────────────────────────────────────
LOGGING_HANDLERS = {
    "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
}

if FILE_LOGGING_ENABLED:
    LOGGING_HANDLERS["file"] = {
        "class": "logging.FileHandler",
        "filename": LOG_FILE,
        "formatter": "verbose",
    }

FINAI_LOG_HANDLERS = ["console", *(["file"] if FILE_LOGGING_ENABLED else [])]

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{asctime}] {levelname} {name} {message}",
            "style": "{",
        },
    },
    "handlers": LOGGING_HANDLERS,
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "finai": {"handlers": FINAI_LOG_HANDLERS, "level": "DEBUG", "propagate": False},
    },
}
LOGIN_URL = '/login/'

ADMIN_URL = os.environ.get("DJANGO_ADMIN_URL", "admin/")
ADMIN_IP_ALLOWLIST = [
    ip.strip()
    for ip in os.environ.get("ADMIN_IP_ALLOWLIST", "").split(",")
    if ip.strip()
]
