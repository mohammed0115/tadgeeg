"""UI helpers for the component library.

  • ``dict_get`` filter — look up ``row[key]`` from a template, used by
    the ``_data_table.html`` partial.
  • ``vite_asset`` tag — read ``static/dist/manifest.json`` and emit the
    hashed filename when present, falling back to the raw input.
  • ``inject_meta_csp_nonce`` tag — places the nonce into <head> so
    client JS (csp-nonce.js) can copy it onto dynamic <script>s.
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

from django import template
from django.conf import settings
from django.utils.safestring import mark_safe

register = template.Library()
logger = logging.getLogger("frontend.ui_tags")


# ─── Generic helpers ───────────────────────────────────────────────────────
@register.filter
def dict_get(d, key):
    """``{{ row|dict_get:"vendor_name" }}`` — safe attribute/item lookup."""
    if d is None:
        return ""
    if isinstance(d, dict):
        return d.get(key, "")
    return getattr(d, key, "")


@register.filter
def get_item(d, key):
    """Alias kept for callers using ``|get_item``."""
    return dict_get(d, key)


# ─── Vite manifest ─────────────────────────────────────────────────────────
@lru_cache(maxsize=1)
def _load_manifest() -> dict:
    manifest_path = Path(settings.BASE_DIR) / "static" / "dist" / "manifest.json"
    if not manifest_path.exists():
        return {}
    try:
        return json.loads(manifest_path.read_text())
    except json.JSONDecodeError as exc:
        logger.warning("Vite manifest is malformed: %s", exc)
        return {}


@register.simple_tag
def vite_asset(name: str) -> str:
    """Resolve a source path to its hashed dist path.

    Usage::
        <link rel="stylesheet" href="{% vite_asset 'js/app.js' %}.css">
        <script type="module" src="{% vite_asset 'js/app.js' %}"></script>

    If the manifest is missing (e.g. dev environment without `npm run build`
    yet), this returns ``/static/dist/<name>`` so a 404 makes the problem
    visible instead of failing silently.
    """
    manifest = _load_manifest()
    entry = manifest.get(name)
    static_base = (getattr(settings, "STATIC_URL", "/static/") or "/static/").rstrip("/")
    if entry and entry.get("file"):
        return f"{static_base}/dist/{entry['file']}"
    return f"{static_base}/dist/{name}"


# ─── Role / permission filters ─────────────────────────────────────────────
@register.filter(name="can")
def has_capability(user, capability: str) -> bool:
    """``{% if request.user|can:"approve_invoices" %}`` — gate UI elements
    on the same capability table the API enforces server-side."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    checker = getattr(user, "has_role_capability", None)
    if callable(checker):
        return bool(checker(capability))
    return False


@register.filter(name="has_role")
def has_role(user, roles_csv: str) -> bool:
    """``{% if request.user|has_role:"admin,cao,senior_auditor" %}``"""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    accepted = {r.strip() for r in (roles_csv or "").split(",") if r.strip()}
    return getattr(user, "role", "") in accepted


# ─── CSP nonce ─────────────────────────────────────────────────────────────
@register.simple_tag(takes_context=True)
def csp_nonce_meta(context):
    """Emit ``<meta name="csp-nonce" content="...">`` if the request has a
    CSP nonce attached (set by the CSP middleware). No-op otherwise."""
    request = context.get("request")
    nonce = getattr(request, "csp_nonce", "") if request else ""
    if not nonce:
        return ""
    return mark_safe(f'<meta name="csp-nonce" content="{nonce}">')
