"""Settings package entry point.

`DJANGO_SETTINGS_MODULE=finai_backend.settings` is documented throughout the
project and should behave like the canonical settings module. Re-export the
base settings here so the package import stays backward compatible while the
environment-specific modules remain available.
"""

from .base import *  # noqa: F401,F403
