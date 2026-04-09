"""
core/utils/coerce.py
====================
Type-coercion utilities shared across services, views, and tasks.

Replaces inline _safe_decimal / _safe_date / _to_float closures that were
defined multiple times in views.py, validation_service.py, and normalizers.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional


# ── Date formats tried in order ───────────────────────────────────────────────
_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d-%m-%Y",
    "%Y/%m/%d",
    "%d %b %Y",
    "%d %B %Y",
    "%d/%m/%y",
    "%d-%m-%y",
)


def to_float(value, default: float = 0.0) -> float:
    """Safely coerce *value* to float, returning *default* on failure."""
    try:
        return float(value)
    except (TypeError, ValueError, ArithmeticError):
        return default


def to_decimal(value, default: Decimal = Decimal("0")) -> Decimal:
    """Safely coerce *value* to Decimal, returning *default* on failure."""
    if value is None or value == "":
        return default
    try:
        cleaned = str(value).replace(",", "").strip()
        return Decimal(cleaned)
    except (InvalidOperation, ValueError, TypeError, AttributeError):
        return default


def to_date(value) -> Optional[date]:
    """
    Safely coerce *value* to a :class:`datetime.date`.

    Accepts:
    - ``date`` / ``datetime`` instances (returned directly)
    - ISO 8601 strings and common regional formats

    Returns ``None`` if the value cannot be parsed.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = str(value).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def get_client_ip(request) -> str:
    """Extract the real client IP from a Django request, respecting X-Forwarded-For."""
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")
