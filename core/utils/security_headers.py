from django.conf import settings


class SecurityHeadersMiddleware:
    CSP = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' "
        "https://accounts.google.com https://apis.google.com "
        "https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://unpkg.com; "
        "style-src 'self' 'unsafe-inline' "
        "https://fonts.googleapis.com https://cdn.jsdelivr.net; "
        "font-src 'self' https://fonts.gstatic.com data:; "
        "img-src 'self' data: blob: https:; "
        "connect-src 'self' https://accounts.google.com; "
        "frame-src https://accounts.google.com; "
        "object-src 'none'; base-uri 'self'; form-action 'self';"
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if not getattr(settings, "DEBUG", True):
            response["Content-Security-Policy"] = self.CSP
            response["Permissions-Policy"] = "geolocation=(), microphone=(), camera=(), payment=()"
            response["Cross-Origin-Opener-Policy"] = "same-origin"
        return response
