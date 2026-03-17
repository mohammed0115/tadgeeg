"""
Structured JSON Logging — Phase 2

Provides:
  JsonFormatter          — converts every log record to a single JSON line
  CorrelationIdMiddleware — generates X-Request-ID per HTTP request and stores
                            it in a contextvars.ContextVar so all code in the
                            same request (including deferred Celery tasks) can
                            include it in log output
  get_correlation_id()   — read current correlation ID from anywhere
  set_correlation_id()   — set current correlation ID (used by Celery signals)

JSON log line structure (all fields always present):
  {
    "timestamp": "2026-03-17T10:23:45.123Z",
    "level":     "INFO",
    "logger":    "finai.documents",
    "message":   "Processing document abc-123",
    "request_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
    "task_id":   null,
    "task_name": null,
    "user_id":   42,
    "org_id":    7,
    "exc_info":  null          // present only when exception is logged
  }

Usage in views / services / tasks:
    logger = logging.getLogger("finai")
    logger.info("Done", extra={"doc_id": str(doc.pk)})

Extra fields are merged into the JSON object automatically.
"""

from __future__ import annotations

import contextvars
import json
import logging
import traceback
import uuid
from datetime import datetime, timezone
from typing import Optional

# ── Correlation ID context variable ──────────────────────────────────────────
# One ContextVar per thread / async task / Celery worker coroutine.
# Value: string UUID or empty string when no request context is active.

_correlation_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "correlation_id", default=""
)


def get_correlation_id() -> str:
    return _correlation_id.get()


def set_correlation_id(value: str) -> contextvars.Token:
    """Set the correlation ID and return a token for resetting later."""
    return _correlation_id.set(value)


def new_correlation_id() -> str:
    """Generate a fresh UUID4 correlation ID."""
    return str(uuid.uuid4())


# ── JSON Formatter ────────────────────────────────────────────────────────────

class JsonFormatter(logging.Formatter):
    """
    Formats log records as single-line JSON objects.

    Extra fields added via logger.info("msg", extra={"key": val}) are merged
    into the top-level JSON object.  Reserved keys (timestamp, level, etc.)
    are never overridden by extra.

    Compatible with Elastic Common Schema (ECS) field names where possible.
    """

    # Fields that should never be overridden by caller-supplied extras
    _RESERVED = frozenset({
        "timestamp", "level", "logger", "message",
        "request_id", "task_id", "task_name",
        "user_id", "org_id", "exc_info",
    })

    # LogRecord attributes that are standard Python internals — we skip them
    # so they don't pollute the JSON with noise.
    _SKIP_ATTRS = frozenset({
        "args", "created", "exc_info", "exc_text", "filename",
        "funcName", "levelname", "levelno", "lineno", "message",
        "module", "msecs", "msg", "name", "pathname", "process",
        "processName", "relativeCreated", "stack_info", "thread",
        "threadName", "taskName",
    })

    def format(self, record: logging.LogRecord) -> str:
        # Base structure
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.%f"
        )[:-3] + "Z"

        obj: dict = {
            "timestamp":  ts,
            "level":      record.levelname,
            "logger":     record.name,
            "message":    record.getMessage(),
            "request_id": get_correlation_id() or None,
            "task_id":    getattr(record, "task_id", None),
            "task_name":  getattr(record, "task_name", None),
            "user_id":    getattr(record, "user_id", None),
            "org_id":     getattr(record, "org_id", None),
        }

        # Exception info
        if record.exc_info:
            obj["exc_info"] = self.formatException(record.exc_info)
        elif record.exc_text:
            obj["exc_info"] = record.exc_text

        # Stack info
        if record.stack_info:
            obj["stack_info"] = self.formatStack(record.stack_info)

        # Caller location (useful for debugging)
        obj["location"] = f"{record.pathname}:{record.lineno}"

        # Merge caller-supplied extras (but never overwrite reserved keys)
        for key, val in record.__dict__.items():
            if key in self._SKIP_ATTRS or key.startswith("_"):
                continue
            if key in self._RESERVED:
                continue
            try:
                json.dumps(val)   # ensure serialisable
                obj[key] = val
            except (TypeError, ValueError):
                obj[key] = str(val)

        try:
            return json.dumps(obj, ensure_ascii=False)
        except Exception:
            # Absolute last resort — never drop a log line
            return json.dumps({"timestamp": ts, "level": record.levelname,
                                "message": repr(record.getMessage()),
                                "error": "json_serialisation_failed"})


# ── Django Middleware ─────────────────────────────────────────────────────────

class CorrelationIdMiddleware:
    """
    Django middleware that:
      1. Reads X-Request-ID from incoming request (trusts upstream proxy).
         If absent, generates a new UUID4.
      2. Stores the ID in the ContextVar so all log lines in this request carry it.
      3. Adds X-Request-ID to every response for client-side tracing.

    Place FIRST in MIDDLEWARE list so the ID is available to all downstream
    middleware and views.
    """

    HEADER_IN  = "HTTP_X_REQUEST_ID"   # WSGI environ key (Django convention)
    HEADER_OUT = "X-Request-ID"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Prefer X-Request-ID from reverse proxy (Nginx / ALB already generated one)
        raw = request.META.get(self.HEADER_IN, "").strip()
        # Validate: must be a non-empty, reasonably short alphanumeric/dash string
        if raw and len(raw) <= 64 and raw.replace("-", "").replace("_", "").isalnum():
            request_id = raw
        else:
            request_id = new_correlation_id()

        token = set_correlation_id(request_id)
        request.correlation_id = request_id

        try:
            response = self.get_response(request)
        finally:
            _correlation_id.reset(token)

        response[self.HEADER_OUT] = request_id
        return response


# ── Request-aware logging helper ─────────────────────────────────────────────

class RequestContextFilter(logging.Filter):
    """
    Logging filter that injects request context into every record so the
    JsonFormatter can include it without the caller passing extra={} every time.

    Add to every handler in LOGGING config (not just to specific loggers)
    so third-party loggers also carry the correlation ID.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = get_correlation_id() or None
        return True
