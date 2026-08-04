"""Security response headers, chiefly Content-Security-Policy.

**What this policy stops:** loading script/style/font from a host not listed
below, so an injected `<script src="https://attacker/x.js">` is refused;
exfiltration by fetch/XHR to an arbitrary host (`connect-src`); plugins
(`object-src 'none'`); `<base href>` hijacking, which silently repoints every
relative URL on the page; posting the page's forms elsewhere (`form-action`);
and framing by another origin (`frame-ancestors`).

**What it does NOT stop:** an injected *inline* `<script>…</script>`. The
templates carry 119 inline scripts, 49 inline event handlers and 47 inline
style blocks, so `'unsafe-inline'` is unavoidable until those are moved out.
Saying so here matters: the presence of a CSP header invites the assumption
that XSS is handled, and it is not.

**Path to tightening**, in order — each step is independently shippable:
  1. move inline `onclick=` handlers to `addEventListener`
  2. move inline `<script>` bodies into files under `static/`, or emit a
     per-request nonce
  3. drop `'unsafe-inline'` from `script-src`
  4. repeat for `style-src`

`CSP_REPORT_ONLY=True` emits the report-only header instead, so a tightened
policy can be trialled on production without breaking a page — violations are
reported by the browser and nothing is blocked. Use it for step 3.
"""

import os

from django.conf import settings


class SecurityHeadersMiddleware:
    CSP = (
        "default-src 'self'; "
        # 'unsafe-inline' is required by the templates (see module docstring).
        # 'unsafe-eval' was here too and has been REMOVED: nothing in this
        # codebase needs eval(), and leaving it turns any injected string into
        # executable code — it defeats much of what the rest of this policy
        # buys. Re-add it only with a named dependency that provably requires
        # it, never "just in case".
        "script-src 'self' 'unsafe-inline' "
        "https://accounts.google.com https://apis.google.com "
        "https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://unpkg.com "
        "https://cdn.tailwindcss.com; "
        "style-src 'self' 'unsafe-inline' "
        "https://fonts.googleapis.com https://cdn.jsdelivr.net; "
        "font-src 'self' https://fonts.gstatic.com data:; "
        "img-src 'self' data: blob: https:; "
        "connect-src 'self' https://accounts.google.com https://api.openai.com; "
        # youtube: the intro video embed on the public site. Without it the
        # embed is blocked and the marketing page renders an empty frame.
        "frame-src 'self' https://accounts.google.com "
        "https://www.youtube.com https://youtube.com https://www.youtube-nocookie.com; "
        "object-src 'none'; base-uri 'self'; form-action 'self'; "
        # Clickjacking. X-Frame-Options covers older browsers; this is the
        # modern equivalent and was missing.
        "frame-ancestors 'none'; "
        # Any http:// subresource on an https page is upgraded rather than
        # silently mixed-content-blocked.
        "upgrade-insecure-requests"
    )

    PERMISSIONS_POLICY = "geolocation=(), microphone=(), camera=(), payment=()"

    def __init__(self, get_response):
        self.get_response = get_response
        self.report_only = os.environ.get("CSP_REPORT_ONLY", "False") == "True"
        self.csp_header = (
            "Content-Security-Policy-Report-Only" if self.report_only
            else "Content-Security-Policy"
        )

    def __call__(self, request):
        response = self.get_response(request)
        if not getattr(settings, "DEBUG", True):
            response[self.csp_header] = self.CSP
            response["Permissions-Policy"] = self.PERMISSIONS_POLICY
            response["Cross-Origin-Opener-Policy"] = "same-origin"
            # Referrer-Policy is set by Django's SECURE_REFERRER_POLICY, and
            # Cross-Origin-Resource-Policy is deliberately NOT set here: it
            # would block the CDN and font subresources allowed above.
        return response
