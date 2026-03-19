from django.conf import settings
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

ACCESS_COOKIE = getattr(settings, "JWT_AUTH_COOKIE", "fin_access")


class JWTCookieAuthentication(JWTAuthentication):
    """Try HttpOnly cookie first, then fall back to Authorization header."""

    def authenticate(self, request):
        cookie_token = request.COOKIES.get(ACCESS_COOKIE)
        if cookie_token:
            try:
                validated_token = self.get_validated_token(cookie_token.encode("utf-8"))
                user = self.get_user(validated_token)
                return user, validated_token
            except (InvalidToken, TokenError):
                return None
        return super().authenticate(request)


try:
    from drf_spectacular.extensions import OpenApiAuthenticationExtension

    class JWTCookieAuthenticationScheme(OpenApiAuthenticationExtension):
        target_class = "core.utils.jwt_cookie_auth.JWTCookieAuthentication"
        name = "JWTCookieAuth"

        def get_security_definition(self, auto_schema):
            return {"type": "apiKey", "in": "cookie", "name": ACCESS_COOKIE}
except ImportError:
    pass
