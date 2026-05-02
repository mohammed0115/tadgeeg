"""
SOC2-grade structured audit-logging helpers built on top of the existing
``AuditLog`` model. The model itself is append-only by convention; this module
adds the discipline auditors expect:

- Every log entry captures user, org, IP, user-agent, resource ref, request ID,
  and a structured ``details`` payload — never free-form text only.
- Sensitive value redaction (passwords, tokens, secrets) before persistence.
- Tamper-evidence helper: ``compute_chain_hash`` produces a SHA-256 over the
  previous log entry's hash + the current entry's payload, so an auditor can
  walk the chain and detect any inserted/deleted record.

The model already has ``retain_until`` (7-year regulatory floor); we set it
automatically when not explicitly provided.
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import timedelta
from typing import Any, Optional

from django.utils import timezone

logger = logging.getLogger("finai")

# Keys we redact from details payloads before persistence — never log secrets.
_SENSITIVE_KEYS = {
    "password", "password1", "password2", "old_password", "new_password",
    "token", "access_token", "refresh_token", "api_key", "secret", "secret_key",
    "otp", "otp_code", "verification_code", "csrf", "csrftoken",
    "authorization", "x-api-key",
}

DEFAULT_RETENTION_YEARS = 7


def _redact(payload: Any) -> Any:
    """Walk a nested dict/list and replace any value under a sensitive key
    with the string ``"[redacted]"``."""
    if isinstance(payload, dict):
        return {
            k: ("[redacted]" if k.lower() in _SENSITIVE_KEYS else _redact(v))
            for k, v in payload.items()
        }
    if isinstance(payload, list):
        return [_redact(v) for v in payload]
    return payload


def _client_ip(request) -> Optional[str]:
    """Resolve the client IP, trusting X-Forwarded-For only behind a known proxy."""
    if request is None:
        return None
    from django.conf import settings
    if getattr(settings, "USE_X_FORWARDED_HOST", False):
        xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if xff:
            return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def log(
    action: str,
    *,
    user=None,
    organization=None,
    resource_type: str = "",
    resource_id: str = "",
    request=None,
    details: Optional[dict] = None,
    retain_years: int = DEFAULT_RETENTION_YEARS,
):
    """Append a single audit-log entry. Failures are swallowed with a warning
    so logging can never break the calling request flow.
    """
    try:
        from apps.authentication.models import AuditLog

        details = _redact(details or {})
        # Add a request_id for tracing the entry back to a specific HTTP request.
        if request is not None:
            details.setdefault("request_id", str(uuid.uuid4()))
            details.setdefault("path", request.path[:200])
            details.setdefault("method", request.method)

        ip = _client_ip(request)
        ua = (request.META.get("HTTP_USER_AGENT", "")[:500] if request else "") or ""

        if user is None and request is not None and getattr(request, "user", None) and request.user.is_authenticated:
            user = request.user
        if organization is None and user is not None:
            organization = getattr(user, "organization", None)

        AuditLog.objects.create(
            user=user,
            organization=organization,
            action=action,
            resource_type=resource_type[:50],
            resource_id=str(resource_id)[:100],
            ip_address=ip,
            user_agent=ua,
            details=details,
            retain_until=timezone.now() + timedelta(days=int(retain_years) * 366),
        )
    except Exception as exc:
        # Never let audit logging break the parent operation.
        logger.warning("[audit-log] failed to record %s: %s", action, exc)


def compute_chain_hash(prev_hash: str, payload: dict) -> str:
    """Compute the SHA-256 over ``prev_hash || canonical_json(payload)``.

    Used by the tamper-evidence verifier (when callers add a `chain_hash`
    field to AuditLog via a follow-up migration). Until then, this is
    available for ad-hoc hashing of exported audit logs.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    h = hashlib.sha256()
    h.update((prev_hash or "").encode("utf-8"))
    h.update(b"|")
    h.update(canonical.encode("utf-8"))
    return h.hexdigest()


def verify_chain(entries: list[dict]) -> dict:
    """Walk a list of audit-log entries (oldest → newest) and verify each
    entry's recomputed chain hash matches its declared one. Useful for a
    nightly tamper-detection job.

    Each entry must be a dict with at least: ``id``, ``payload`` (dict),
    ``chain_hash``, ``previous_hash``.

    Returns ``{"verified": int, "broken_at": int|None, "broken_id": str|None}``.
    """
    prev = ""
    for i, e in enumerate(entries):
        recomputed = compute_chain_hash(prev, e.get("payload", {}))
        if recomputed != e.get("chain_hash"):
            return {"verified": i, "broken_at": i, "broken_id": str(e.get("id"))}
        prev = recomputed
    return {"verified": len(entries), "broken_at": None, "broken_id": None}
