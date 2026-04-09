"""
finai_backend/settings/production.py
=======================================
Production-specific settings.

Usage:
  DJANGO_SETTINGS_MODULE=finai_backend.settings.production

Only overrides settings that must be different in production.
Never import dev-only packages here.
"""

from finai_backend.settings.base import *  # noqa: F401, F403
import os

# ── Security ──────────────────────────────────────────────────────────────────
DEBUG = False

# In production ALLOWED_HOSTS MUST be explicitly set via environment variable.
# If unset, Django will reject all requests.
ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get("ALLOWED_HOSTS", "").split(",")
    if h.strip()
]

# Force secure cookies in production
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
JWT_AUTH_COOKIE_SECURE = True

# HSTS — 1 year, include subdomains, preload
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_SSL_REDIRECT = True

# ── Static files ──────────────────────────────────────────────────────────────
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# ── Logging — production: WARNING level for Django, INFO for app ──────────────
LOGGING["root"]["level"] = "WARNING"  # type: ignore[index]
LOGGING["loggers"]["django"]["level"] = "WARNING"  # type: ignore[index]

# ── Celery ────────────────────────────────────────────────────────────────────
# Tasks must always run asynchronously in production
CELERY_TASK_ALWAYS_EAGER = False
CELERY_TASK_EAGER_PROPAGATES = False

# ── Email — fail loudly if SMTP not configured in production ──────────────────
_email_user = os.environ.get("EMAIL_HOST_USER", "")
_email_pass = os.environ.get("EMAIL_HOST_PASSWORD", "")
if not (_email_user and _email_pass):
    import warnings
    warnings.warn(
        "EMAIL_HOST_USER / EMAIL_HOST_PASSWORD not set — emails will use console backend",
        RuntimeWarning,
        stacklevel=1,
    )
