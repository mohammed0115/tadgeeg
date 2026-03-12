"""Middleware: Audit Trail + Request Timing"""

import time
import logging

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
