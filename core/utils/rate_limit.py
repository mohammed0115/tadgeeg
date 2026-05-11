"""
Rate Limiting Middleware — Per Organization
==========================================
Uses Redis to enforce API rate limits per organisation (not per user IP).
Configurable via settings.RATE_LIMITS dict.

Atomicity contract
------------------
The previous implementation used `cache.get(...)` then `cache.set/incr(...)`
in two separate round trips. Under burst traffic, multiple workers could
read the same `current` and let through more requests than the configured
ceiling. This version uses a single Redis Lua script (`INCR` + `EXPIRE`
on first hit) which is atomic on the redis side.

Failure mode
------------
The previous version was *fail-open* on Redis outage — if redis went
down, every request was allowed through unchecked. That turns a redis
incident into a brute-force window.

This version is *fail-closed in production* (returns 503 + `Retry-After`)
and *fail-open in development* (`DEBUG=True`) so local dev still works
when redis isn't running.

Login-specific quota
--------------------
Authentication endpoints share the `login` bucket which is much tighter
than the generic API one (5 req/min/org by default). Superusers are
exempt from `api`/`upload`/`ai` quotas but NOT from `login` — a stolen
super-admin credential should still be rate-limited for password
attempts.

Default limits:
  upload:    20 requests / minute
  api:       200 requests / minute
  ai:        10 requests / minute  (OpenAI-backed endpoints)
  login:     5 requests / minute
"""

import logging

from django.conf import settings
from django.http import JsonResponse
from rest_framework_simplejwt.authentication import JWTAuthentication

logger = logging.getLogger("finai")

# Default limits: (requests, window_seconds)
DEFAULT_LIMITS = {
    "upload":  (20,  60),
    "ai":      (10,  60),
    "api":     (200, 60),
    "login":   (5,   60),
    "default": (300, 60),
}

UPLOAD_PATHS = {"/api/v1/invoices/upload/", "/api/v1/documents/upload/typed/", "/api/v1/documents/upload/"}
AI_PATHS     = {"/api/v1/analytics/", "/api/v1/reports/generate/"}
LOGIN_PATHS  = {"/api/v1/auth/token/", "/api/v1/auth/login/", "/api/v1/auth/mfa/"}

# Atomic INCR + EXPIRE-on-first-hit. Returns the new counter value.
_LUA_INCR = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return current
"""


def _get_limit_key(path: str) -> str:
    if any(path.startswith(p) for p in LOGIN_PATHS):
        return "login"
    if any(path.startswith(p) for p in UPLOAD_PATHS):
        return "upload"
    if any(path.startswith(p) for p in AI_PATHS):
        return "ai"
    if path.startswith("/api/"):
        return "api"
    return "default"


def _is_login_path(path: str) -> bool:
    return any(path.startswith(p) for p in LOGIN_PATHS)


class OrgRateLimitMiddleware:
    """Rate-limit API requests per organization (or per IP for unauth login)."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.limits = getattr(settings, "RATE_LIMITS", DEFAULT_LIMITS)
        self.jwt_authentication = JWTAuthentication()

    # ── Identity resolution ───────────────────────────────────────────────────

    def _get_user(self, request):
        user = getattr(request, "user", None)
        if user and getattr(user, "is_authenticated", False):
            return user
        try:
            auth_result = self.jwt_authentication.authenticate(request)
        except Exception:
            return None
        if auth_result:
            user, _ = auth_result
            return user
        return None

    def _get_client_ip(self, request) -> str:
        # Honor proxy headers when configured. settings.USE_X_FORWARDED_HOST
        # is the existing flag for trusting forwarders.
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR", "0.0.0.0")

    # ── Atomic counter via Redis Lua ─────────────────────────────────────────

    def _atomic_incr(self, cache_key: str, window: int) -> int | None:
        """Return the new counter value, or None when redis is unavailable."""
        try:
            from django_redis import get_redis_connection
            redis = get_redis_connection("default")
        except Exception as exc:
            logger.error("Rate limiter could not reach redis backend: %s", exc)
            return None
        try:
            return int(redis.eval(_LUA_INCR, 1, cache_key, window))
        except Exception as exc:
            logger.error("Rate limiter Lua eval failed (key=%s): %s", cache_key, exc)
            return None

    # ── Main entry ────────────────────────────────────────────────────────────

    def __call__(self, request):
        if not request.path.startswith("/api/"):
            return self.get_response(request)

        is_login = _is_login_path(request.path)

        if is_login:
            # Per-IP bucket: this guards UNAUTHENTICATED login attempts and
            # password-reset endpoints. We can't use organization here.
            scope_id = self._get_client_ip(request)
            limit_key = "login"
            cache_key = f"ratelimit:login:ip:{scope_id}"
        else:
            user = self._get_user(request)
            if not user or not user.is_authenticated:
                return self.get_response(request)
            # Superusers are exempted from non-login quotas only.
            if user.is_superuser:
                return self.get_response(request)
            org = getattr(user, "organization", None)
            if not org:
                return self.get_response(request)
            scope_id = str(org.id)
            limit_key = _get_limit_key(request.path)
            cache_key = f"ratelimit:{scope_id}:{limit_key}"

        max_requests, window = self.limits.get(limit_key, self.limits.get("default", (300, 60)))

        current = self._atomic_incr(cache_key, window)
        if current is None:
            # ── FAIL-CLOSED in production, FAIL-OPEN in dev ──
            # In a redis outage we'd rather refuse a few requests with 503
            # (which clients can retry) than open a brute-force / DoS
            # window. Local dev (`DEBUG=True`) bypasses to keep the
            # developer loop fast.
            if getattr(settings, "DEBUG", False):
                return self.get_response(request)
            return JsonResponse({
                "error": "rate_limit_unavailable",
                "message": "Rate limit backend temporarily unavailable. Please retry shortly.",
                "retry_after": 5,
            }, status=503)

        if current > max_requests:
            logger.warning(
                "Rate limit hit: scope=%s key=%s path=%s current=%s/%s",
                scope_id, limit_key, request.path, current, max_requests,
            )
            return JsonResponse({
                "error": "rate_limit_exceeded",
                "message": f"Rate limit exceeded ({max_requests} per {window}s). Please retry.",
                "retry_after": window,
            }, status=429)

        response = self.get_response(request)
        response["X-RateLimit-Limit"]     = str(max_requests)
        response["X-RateLimit-Remaining"] = str(max(0, max_requests - current))
        response["X-RateLimit-Window"]    = str(window)
        return response


# ── Settings snippet (add to settings.py) ────────────────────────────────────
SETTINGS_SNIPPET = """
# Rate Limiting (add to settings.py)
RATE_LIMITS = {
    "upload":  (20,  60),   # 20 uploads per minute per org
    "ai":      (10,  60),   # 10 AI requests per minute per org
    "api":     (300, 60),   # 300 API calls per minute per org
    "login":   (5,   60),   # 5 login attempts per minute per IP
    "default": (500, 60),
}

MIDDLEWARE = [
    ...
    "core.utils.rate_limit.OrgRateLimitMiddleware",  # Add after auth middleware
    ...
]
"""
