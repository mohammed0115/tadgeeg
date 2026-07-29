"""
finai_backend/settings/test.py
=================================
Test-specific settings.

Usage:
  DJANGO_SETTINGS_MODULE=finai_backend.settings.test

Used by pytest / CI. Disables external services, forces sync Celery,
uses lightweight caching, and targets the test database.
"""

from finai_backend.settings.base import *  # noqa: F401, F403

# ── Core ──────────────────────────────────────────────────────────────────────
DEBUG = False  # Tests should behave like production
SECRET_KEY = "test-secret-key-not-for-production-use"  # noqa: S105
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
globals().pop("STATICFILES_STORAGE", None)
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# ── Database — use in-memory SQLite for speed unless CI sets a real DB ────────
import os

_test_db_backend = os.environ.get("TEST_DB_BACKEND", "sqlite")

if _test_db_backend == "mysql":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": os.environ.get("TEST_DB_NAME", "finai_test"),
            "USER": os.environ.get("TEST_DB_USER", "finai_test"),
            "PASSWORD": os.environ.get("TEST_DB_PASSWORD", "test_password"),
            "HOST": os.environ.get("TEST_DB_HOST", "127.0.0.1"),
            "PORT": os.environ.get("TEST_DB_PORT", "3306"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": ":memory:",
        }
    }

# ── Cache — use local memory (no Redis needed in tests) ───────────────────────
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "test-cache",
    }
}

# ── Celery — run synchronously so tasks execute inline ───────────────────────
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# ── Email — capture in memory (inspectable in tests) ─────────────────────────
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# ── Media — use temp dir to avoid polluting real media/ ───────────────────────
import tempfile
MEDIA_ROOT = tempfile.mkdtemp()

# ── Channels — in-memory layer (no Redis in tests) ────────────────────────────
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    }
}

# ── Passwords — use faster hasher in tests ───────────────────────────────────
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",  # Fast but insecure — tests only
]

# ── Logging — suppress in tests unless debugging ─────────────────────────────
LOGGING["root"]["level"] = "ERROR"  # type: ignore[index]

# TADGEEG — tests assert against stable English source strings, not the Arabic
# production locale. Templates render {% trans %} in English here; tests that
# specifically check Arabic use explicit translation.override("ar").
LANGUAGE_CODE = "en"

# Tests assert raw amounts (e.g. "150000"), not grouped ("150,000"). The Arabic
# production locale renders numbers without grouping, so disabling the separator
# in tests keeps number assertions deterministic and locale-independent.
USE_THOUSAND_SEPARATOR = False
