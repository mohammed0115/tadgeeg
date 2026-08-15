"""
Idempotency-Key middleware.

Implements the contract from
``Documentation/tadgeeg_enterprise_readiness_pack/API_AND_ERP_INTEGRATION_CONTRACTS.md`` §14:

  Same key + same payload  → same response (replayed from cache).
  Same key + different payload → 409 Conflict.
  No key on a write request   → pass-through (header is opt-in for now).

Scope:
  • POST / PUT / PATCH / DELETE
  • Path starts with /api/
  • Authenticated request only — anonymous writers don't need replay safety.

This is a SEMANTIC idempotency cache: the response body, status, and
content-type are stored against the (organization, key, payload-hash)
triplet for 24 hours. The same client retrying with the same key/payload
gets the EXACT same bytes back, so an ERP that loses a connection
mid-POST and retries doesn't create a duplicate document.

A different payload with the same key is a programming error in the
client (key reuse) — we reject with 409 rather than silently overwriting.

Failure mode:
  • If the cache backend is down, we PASS THROUGH (do nothing). Idempotency
    is best-effort safety, not a hard correctness requirement; failing the
    write because redis hiccupped is worse than letting it through.
"""

from __future__ import annotations

import hashlib
import json
import logging

from django.core.cache import cache
from django.http import HttpResponse, JsonResponse

logger = logging.getLogger("finai")

_IDEMPOTENT_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_HEADER = "HTTP_IDEMPOTENCY_KEY"
_TTL_SECONDS = 60 * 60 * 24  # 24 h


def _payload_digest(request) -> str:
    """Stable hash of the request body. Independent of header order so the
    same logical request from two HTTP libraries hashes identically."""
    body = request.body or b""
    h = hashlib.sha256()
    h.update(request.method.encode("utf-8"))
    h.update(b"\x1f")
    h.update(request.path.encode("utf-8"))
    h.update(b"\x1f")
    h.update(body)
    return h.hexdigest()[:32]


def _scope_id(request) -> str:
    """Per-organization scope when authenticated, else per-IP. Prevents one
    tenant from poisoning another tenant's idempotency space."""
    user = getattr(request, "user", None)
    org = getattr(user, "organization", None)
    if org is not None:
        return f"org:{org.id}"
    return "ip:" + (request.META.get("REMOTE_ADDR") or "0.0.0.0")


class IdempotencyMiddleware:
    """Replay-safe writes via the standard ``Idempotency-Key`` header."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            request.method not in _IDEMPOTENT_METHODS
            or not request.path.startswith("/api/")
        ):
            return self.get_response(request)

        key = request.META.get(_HEADER, "").strip()
        if not key:
            return self.get_response(request)
        # Cap key length to prevent oversize cache key abuse.
        if len(key) > 128:
            return JsonResponse({
                "error": "idempotency_key_too_long",
                "message": "Idempotency-Key must be ≤ 128 characters.",
            }, status=400)

        payload_hash = _payload_digest(request)
        scope = _scope_id(request)
        cache_key = f"idempotency:v1:{scope}:{key}"

        try:
            cached = cache.get(cache_key)
        except Exception as exc:
            logger.warning("Idempotency cache unreachable; passing through: %s", exc)
            return self.get_response(request)

        if cached is not None:
            stored_hash = cached.get("payload_hash")
            if stored_hash != payload_hash:
                # Same key, different payload — almost certainly a bug in the
                # client. Reject loudly so the issue surfaces immediately.
                return JsonResponse({
                    "error": "idempotency_key_conflict",
                    "message": (
                        "An Idempotency-Key was reused with a different "
                        "request body. Generate a fresh key for the new "
                        "request."
                    ),
                }, status=409)
            # Replay the stored response verbatim.
            response = HttpResponse(
                cached["body"],
                status=cached["status"],
                content_type=cached["content_type"],
            )
            response["X-Idempotent-Replay"] = "1"
            return response

        # First time we've seen this key — execute and memoize.
        response = self.get_response(request)

        # Only cache 2xx writes. Caching a 5xx would re-deliver a server
        # error for 24h — useless. Caching a 4xx for client errors is also
        # not what idempotency is for.
        if 200 <= response.status_code < 300:
            try:
                cache.set(cache_key, {
                    "payload_hash":  payload_hash,
                    "status":        response.status_code,
                    "content_type":  response.get("Content-Type", "application/json"),
                    "body":          response.content,
                }, _TTL_SECONDS)
            except Exception as exc:
                logger.warning("Idempotency cache write failed: %s", exc)

        return response
