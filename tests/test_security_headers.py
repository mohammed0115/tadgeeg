"""Guards on the CSP in core/utils/security_headers.py.

These exist because the policy is easy to loosen by accident — a directive is
one string in one long concatenation, and a bad edit produces no error, no
failing page, and no log line. It produces a header that looks fine and stops
less. So each test below names the specific attack the directive blocks; if a
test fails, the question to answer is "did we mean to allow that?".

Note also: I once reported CSP as *absent* on this project because I grepped
`settings_canonical.py` and not the middleware. A test that imports the real
middleware is the cheap fix for that class of mistake.
"""

import pytest
from django.test import override_settings

from core.utils.security_headers import SecurityHeadersMiddleware


def _policy():
    """The header value the browser actually receives, not the source text.

    Reading the file would match `'unsafe-eval'` in the comment that explains
    its removal — which is exactly the false positive this indirection avoids.
    """
    return SecurityHeadersMiddleware.CSP


def _directive(name):
    for part in _policy().split("; "):
        if part.split(" ")[0] == name:
            return part
    return None


def test_unsafe_eval_is_present_because_alpine_needs_it():
    """Not an endorsement — a record of a shipped regression.

    I removed 'unsafe-eval' on the reasoning that nothing here calls eval(),
    and broke every Alpine page on production. Alpine compiles each x-show /
    x-model / x-data expression with `new Function`; CSP blocked it, the pages
    still returned 200, and the login form rendered all three panels at once
    with empty error boxes. Nothing failed server-side, so nothing noticed.

    This test exists so the next person to read the policy and think "eval is
    obviously unnecessary" finds out here instead of on production. Removing it
    is a migration to alpinejs/csp, not a header edit — invert this test then,
    with the migration in the same change.
    """
    assert "'unsafe-eval'" in _directive("script-src")


def test_frame_ancestors_blocks_clickjacking():
    assert _directive("frame-ancestors") == "frame-ancestors 'none'"


def test_object_src_none_blocks_plugin_based_execution():
    assert _directive("object-src") == "object-src 'none'"


def test_base_uri_is_locked_to_self():
    """An injected <base href> silently repoints every relative URL on the page."""
    assert _directive("base-uri") == "base-uri 'self'"


def test_form_action_is_locked_to_self():
    """Otherwise an injected form posts the user's credentials to another host."""
    assert _directive("form-action") == "form-action 'self'"


def test_connect_src_does_not_allow_arbitrary_hosts():
    """connect-src is the exfiltration path: fetch/XHR to anywhere."""
    directive = _directive("connect-src")
    assert "*" not in directive and "https:" not in directive.replace("https://", "")


def test_youtube_is_frameable_so_the_intro_video_still_renders():
    """Regression: tightening frame-src to 'self' blanks the marketing embed."""
    assert "https://www.youtube.com" in _directive("frame-src")


def test_unsafe_inline_is_still_present_and_that_is_a_known_gap():
    """Not an endorsement — an assertion that we know.

    119 templates carry inline <script>, so removing this breaks the site. When
    that is fixed, this test should be inverted, not deleted. Until then the
    policy does NOT stop injected inline script, and nobody should read the
    presence of a CSP header as "XSS is handled".
    """
    assert "'unsafe-inline'" in _directive("script-src")


# ── Header emission ───────────────────────────────────────────────────────────

def _response_headers(**env):
    import os
    from unittest import mock

    with mock.patch.dict(os.environ, env, clear=False):
        middleware = SecurityHeadersMiddleware(lambda request: _FakeResponse())
        return middleware(object())


class _FakeResponse(dict):
    pass


@override_settings(DEBUG=False)
def test_csp_is_enforced_in_production():
    headers = _response_headers(CSP_REPORT_ONLY="False")
    assert headers["Content-Security-Policy"] == _policy()
    assert "Content-Security-Policy-Report-Only" not in headers
    assert headers["Cross-Origin-Opener-Policy"] == "same-origin"
    assert "camera=()" in headers["Permissions-Policy"]


@override_settings(DEBUG=False)
def test_report_only_mode_reports_without_blocking():
    """The safe way to trial dropping 'unsafe-inline' on production."""
    headers = _response_headers(CSP_REPORT_ONLY="True")
    assert headers["Content-Security-Policy-Report-Only"] == _policy()
    assert "Content-Security-Policy" not in headers


@override_settings(DEBUG=True)
def test_no_csp_under_debug_so_local_tooling_is_not_blocked():
    assert "Content-Security-Policy" not in _response_headers()
