import logging
from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponseForbidden, HttpResponse

logger = logging.getLogger("finai")

_ADMIN_URL   = "/" + getattr(settings, "ADMIN_URL", "admin/").lstrip("/")
_ALLOWLIST   = [ip.strip() for ip in getattr(settings, "ADMIN_IP_ALLOWLIST", []) if ip.strip()]
_MAX_ATTEMPTS = 10
_LOCKOUT_SECS = 900


def _client_ip(request):
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return (xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR", "")).split(":")[0]


class AdminSecurityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path.startswith(_ADMIN_URL):
            return self.get_response(request)

        ip = _client_ip(request)

        if _ALLOWLIST and ip not in _ALLOWLIST:
            logger.warning("[ADMIN] Blocked IP %s — not in allowlist", ip)
            return HttpResponseForbidden("Access denied.")

        attempts = cache.get(f"admin_fail:{ip}", 0)
        if attempts >= _MAX_ATTEMPTS:
            logger.warning("[ADMIN] IP %s locked out after %d attempts", ip, attempts)
            return HttpResponse("Too many failed attempts. Try again later.", status=429)

        response = self.get_response(request)

        if request.method == "POST" and request.path == _ADMIN_URL + "login/" and response.status_code == 200:
            cache.set(f"admin_fail:{ip}", attempts + 1, _LOCKOUT_SECS)
            logger.warning("[ADMIN] Failed login attempt #%d from %s", attempts + 1, ip)
        elif response.status_code in (301, 302):
            cache.delete(f"admin_fail:{ip}")

        return response
