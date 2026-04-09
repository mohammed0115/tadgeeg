"""
finai_backend/settings/base.py
================================
Base settings — imports everything from the canonical settings.py and
re-exports it. All environment-specific modules import from here.

This file intentionally has no overrides — it is the shared baseline.
Environment-specific modules (production.py, test.py) override only what
they need to change.
"""

# Re-export everything from the canonical settings file.
from finai_backend.settings_canonical import *  # noqa: F401, F403
from finai_backend.settings_canonical import (  # noqa: F401 — explicit for IDE support
    BASE_DIR,
    DEBUG,
    SECRET_KEY,
    INSTALLED_APPS,
    MIDDLEWARE,
    DATABASES,
    CACHES,
    CELERY_BROKER_URL,
    REST_FRAMEWORK,
    LOGGING,
)
