"""Content Security Policy middleware.

Generates a per-request nonce, attaches it to the request object as
``request.csp_nonce`` (read by ``{% csp_nonce_meta %}``), and emits a
``Content-Security-Policy`` header on every HTML response.

Policy is deliberately strict:

  default-src 'self';
  script-src  'self' 'nonce-<N>' https://cdn.jsdelivr.net https://cdn.tailwindcss.com https://unpkg.com;
  style-src   'self' 'unsafe-inline' https://fonts.googleapis.com;
  img-src     'self' data: blob: https:;
  font-src    'self' https://fonts.gstatic.com;
  connect-src 'self' https:;
  frame-ancestors 'none';
  base-uri 'self';
  form-action 'self';

Override via settings.CSP_EXTRA_DIRECTIVES if a deployment needs more.
Set settings.CSP_REPORT_ONLY = True to log violations without blocking
(useful for staged rollout).
"""
from __future__ import annotations

import secrets
from django.conf import settings


_DEFAULT_DIRECTIVES = {
    "default-src": "'self'",
    "script-src":  "'self' 'nonce-{nonce}' https://cdn.jsdelivr.net https://cdn.tailwindcss.com https://unpkg.com",
    "style-src":   "'self' 'unsafe-inline' https://fonts.googleapis.com",
    "img-src":     "'self' data: blob: https:",
    "font-src":    "'self' https://fonts.gstatic.com",
    "connect-src": "'self' https:",
    "frame-ancestors": "'none'",
    "base-uri":    "'self'",
    "form-action": "'self'",
}


class CSPMiddleware:
    """Per-response CSP header + per-request nonce."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.csp_nonce = secrets.token_urlsafe(16)
        response = self.get_response(request)
        if not _is_html(response):
            return response

        directives = dict(_DEFAULT_DIRECTIVES)
        directives.update(getattr(settings, "CSP_EXTRA_DIRECTIVES", {}) or {})

        parts = []
        for key, value in directives.items():
            parts.append(f"{key} {value.format(nonce=request.csp_nonce)}")
        header = "; ".join(parts)

        header_name = (
            "Content-Security-Policy-Report-Only"
            if getattr(settings, "CSP_REPORT_ONLY", False)
            else "Content-Security-Policy"
        )
        response[header_name] = header
        return response


def _is_html(response) -> bool:
    ct = response.get("Content-Type", "")
    return "html" in ct.lower()
