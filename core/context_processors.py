"""Template context processors used across the product."""

from __future__ import annotations

from core.branding import get_branding_context


def branding(request):
    return get_branding_context(getattr(request, "LANGUAGE_CODE", None))
