from django.conf import settings
from django.utils import timezone

ACCESS_COOKIE  = getattr(settings, "JWT_AUTH_COOKIE", "fin_access")
REFRESH_COOKIE = getattr(settings, "JWT_AUTH_REFRESH_COOKIE", "fin_refresh")
SECURE         = getattr(settings, "JWT_AUTH_COOKIE_SECURE", True)
SAMESITE       = getattr(settings, "JWT_AUTH_COOKIE_SAMESITE", "Lax")
HTTP_ONLY      = getattr(settings, "JWT_AUTH_COOKIE_HTTP_ONLY", True)


def set_auth_cookies(response, access_token: str, refresh_token: str) -> None:
    """Attach JWT pair as HttpOnly cookies to response."""
    from rest_framework_simplejwt.tokens import AccessToken
    try:
        at = AccessToken(access_token)
        access_max_age = int((at.current_time + at.lifetime - timezone.now()).total_seconds())
    except Exception:
        access_max_age = 3600

    response.set_cookie(
        ACCESS_COOKIE, access_token,
        max_age=access_max_age,
        httponly=HTTP_ONLY, secure=SECURE, samesite=SAMESITE, path="/",
    )
    response.set_cookie(
        REFRESH_COOKIE, refresh_token,
        max_age=7 * 24 * 3600,
        httponly=HTTP_ONLY, secure=SECURE, samesite=SAMESITE,
        path="/api/v1/auth/token/refresh/",
    )


def clear_auth_cookies(response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth/token/refresh/")
