"""Middleware: Audit Trail + Request Timing"""

import time
import logging
from django.conf import settings

logger = logging.getLogger("finai")


class AuditTrailMiddleware:
    """Log all mutating API requests to the audit trail."""

    MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if (
            request.method in self.MUTATING_METHODS
            and request.path.startswith("/api/")
            and hasattr(request, "user")
            and request.user.is_authenticated
        ):
            logger.info(
                f"[AUDIT] {request.method} {request.path} | "
                f"User: {request.user.email} | Status: {response.status_code}"
            )

        return response


class RequestTimingMiddleware:
    """Add X-Response-Time header to all responses."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start = time.time()
        response = self.get_response(request)
        ms = int((time.time() - start) * 1000)
        response["X-Response-Time"] = f"{ms}ms"
        return response


class SecurityHeadersMiddleware:
    """Attach baseline security headers suitable for the current template stack."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.csp_policy = "; ".join(
            [
                "default-src 'self'",
                "base-uri 'self'",
                "frame-ancestors 'none'",
                "form-action 'self'",
                "img-src 'self' data: blob: https:",
                "font-src 'self' data: https://fonts.gstatic.com",
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
                "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
                "connect-src 'self' https://api.openai.com https://accounts.google.com https://openidconnect.googleapis.com https://oauth2.googleapis.com",
                "frame-src 'self' https://accounts.google.com",
                "object-src 'none'",
            ]
        )

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
        response.setdefault("Referrer-Policy", getattr(settings, "SECURE_REFERRER_POLICY", "same-origin"))
        response.setdefault("Content-Security-Policy", self.csp_policy)
        response.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        return response
