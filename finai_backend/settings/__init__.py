"""
finai_backend/settings/__init__.py
====================================
Settings package entry point.

This package provides environment-specific settings modules that layer
on top of the canonical settings.py file in the parent directory.

Usage:
  DJANGO_SETTINGS_MODULE=finai_backend.settings           → uses canonical settings.py (backward-compat)
  DJANGO_SETTINGS_MODULE=finai_backend.settings.base      → base shared settings
  DJANGO_SETTINGS_MODULE=finai_backend.settings.production → production overrides
  DJANGO_SETTINGS_MODULE=finai_backend.settings.test       → test overrides

The canonical finai_backend/settings.py is still the primary settings file
and remains fully functional. This package adds an overlay layer for
environments that need explicit separation.
"""
