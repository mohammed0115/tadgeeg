"""
Rate Limiting Middleware — Per Organization
==========================================
Uses Redis to enforce API rate limits per organisation (not per user IP).
Configurable via settings.RATE_LIMITS dict.

Default limits:
  upload:    20 requests / minute
  api:       200 requests / minute
  ai:        10 requests / minute  (OpenAI-backed endpoints)
"""

import logging
from django.conf import settings
from django.http import JsonResponse
from django.core.cache import cache
from rest_framework_simplejwt.authentication import JWTAuthentication

logger = logging.getLogger("finai")

# Default limits: (requests, window_seconds)
DEFAULT_LIMITS = {
    "upload":  (20,  60),
    "ai":      (10,  60),
    "api":     (200, 60),
    "default": (300, 60),
}

UPLOAD_PATHS = {"/api/v1/invoices/upload/", "/api/v1/documents/upload/typed/", "/api/v1/documents/upload/"}
AI_PATHS     = {"/api/v1/analytics/", "/api/v1/reports/generate/"}


def _get_limit_key(path: str):
    if any(path.startswith(p) for p in UPLOAD_PATHS):
        return "upload"
    if any(path.startswith(p) for p in AI_PATHS):
        return "ai"
    if path.startswith("/api/"):
        return "api"
    return "default"


class OrgRateLimitMiddleware:
    """
    Rate limit API requests per organization.
    Skipped for: non-API paths, unauthenticated users, superusers.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.limits = getattr(settings, "RATE_LIMITS", DEFAULT_LIMITS)
        self.jwt_authentication = JWTAuthentication()

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

    def __call__(self, request):
        # Only check API paths
        if not request.path.startswith("/api/"):
            return self.get_response(request)

        # Skip for unauthenticated or superusers
        user = self._get_user(request)
        if not user or not user.is_authenticated or user.is_superuser:
            return self.get_response(request)

        org = getattr(user, "organization", None)
        if not org:
            return self.get_response(request)

        limit_key = _get_limit_key(request.path)
        max_requests, window = self.limits.get(limit_key, self.limits["default"])

        cache_key = f"ratelimit:{org.id}:{limit_key}"

        try:
            current = cache.get(cache_key, 0)
            if current >= max_requests:
                logger.warning(f"Rate limit hit: org={org.id} path={request.path} type={limit_key}")
                return JsonResponse({
                    "error": "rate_limit_exceeded",
                    "message": f"تجاوزت الحد المسموح ({max_requests} طلب / {window} ثانية). حاول لاحقاً.",
                    "retry_after": window,
                }, status=429)

            # Increment counter
            if current == 0:
                cache.set(cache_key, 1, timeout=window)
            else:
                cache.incr(cache_key)

            response = self.get_response(request)

            # Add rate limit headers
            response["X-RateLimit-Limit"]     = str(max_requests)
            response["X-RateLimit-Remaining"] = str(max(0, max_requests - current - 1))
            response["X-RateLimit-Window"]    = str(window)
            return response

        except Exception as e:
            # If Redis is unavailable, allow the request
            logger.error(f"Rate limit check failed (Redis?): {e}")
            return self.get_response(request)


# ── Settings snippet (add to settings.py) ────────────────────────────────────
SETTINGS_SNIPPET = """
# Rate Limiting (add to settings.py)
RATE_LIMITS = {
    "upload":  (20,  60),   # 20 uploads per minute per org
    "ai":      (10,  60),   # 10 AI requests per minute per org
    "api":     (300, 60),   # 300 API calls per minute per org
    "default": (500, 60),
}

MIDDLEWARE = [
    ...
    "core.utils.rate_limit.OrgRateLimitMiddleware",  # Add after auth middleware
    ...
]
"""
