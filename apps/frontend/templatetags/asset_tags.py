from django import template
from django.conf import settings
from django.contrib.staticfiles.storage import staticfiles_storage


register = template.Library()


@register.simple_tag
def safe_static(path: str) -> str:
    """
    Resolve a static asset without crashing template rendering when the
    manifest is stale or missing an entry.
    """
    try:
        return staticfiles_storage.url(path)
    except Exception:
        base = getattr(settings, "STATIC_URL", "/static/") or "/static/"
        if not base.endswith("/"):
            base = f"{base}/"
        return f"{base}{path.lstrip('/')}"
