"""The PDF renderer must not become an SSRF gadget.

Reports are rendered from tenant data — vendor names, descriptions, fields that
arrived through OCR of an uploaded document. If any of that reaches an
`<img src>`, a `url()` or an `@import`, WeasyPrint resolves it *from the
server*, inside the network. The trigger is uploading an invoice; on a cloud
host the payoff is instance credentials from 169.254.169.254.

WeasyPrint 68.1 shipped a CSS-injection variant of precisely this
(PYSEC-2026-3412), whose published proof of concept pointed at that address.
Upgrading fixed that parser bug. These tests pin the category instead: whatever
opens a path — a future parser bug, a template change, a new report type — the
fetch itself is refused.
"""

import pytest

from apps.reports.views import _safe_url_fetcher


# ── Internal addresses ───────────────────────────────────────────────────────

@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/",          # AWS/GCP/Azure metadata
    "http://169.254.169.254/computeMetadata/v1/",
    "http://127.0.0.1:8000/admin/",                      # the app's own admin
    "http://localhost/",
    "http://10.0.0.5/internal",
    "http://192.168.1.1/",
    "http://172.16.0.9/",
    "http://[::1]/",
])
def test_internal_addresses_are_refused(url):
    with pytest.raises(ValueError, match="internal address|Refusing"):
        _safe_url_fetcher(url)


def test_the_metadata_endpoint_specifically_is_refused():
    """Named on its own: this is the one that costs the whole account."""
    with pytest.raises(ValueError) as caught:
        _safe_url_fetcher("http://169.254.169.254/latest/meta-data/iam/security-credentials/")
    assert "169.254.169.254" in str(caught.value)


# ── Bypasses ─────────────────────────────────────────────────────────────────

def test_a_hostname_resolving_to_an_internal_address_is_refused(monkeypatch):
    """The standard bypass for a string-matching blocklist.

    `metadata.example.com` looks external and resolves to 169.254.169.254.
    Blocking on the literal string in the URL would let this straight through,
    which is why the fetcher resolves DNS before deciding.
    """
    import socket

    def fake_getaddrinfo(host, *args, **kwargs):
        return [(socket.AF_INET, None, None, "", ("169.254.169.254", 80))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    with pytest.raises(ValueError, match="internal address"):
        _safe_url_fetcher("http://metadata.totally-external.com/")


def test_a_host_with_one_internal_answer_among_several_is_refused(monkeypatch):
    """DNS can return several addresses. One internal answer is enough — the
    fetch would follow whichever the stack picks."""
    import socket

    def fake_getaddrinfo(host, *args, **kwargs):
        return [
            (socket.AF_INET, None, None, "", ("93.184.216.34", 80)),
            (socket.AF_INET, None, None, "", ("127.0.0.1", 80)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    with pytest.raises(ValueError, match="internal address"):
        _safe_url_fetcher("http://mixed-answers.example.com/")


@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "file:///app/deployment/docker/env/live.env",
    "gopher://127.0.0.1:6379/_FLUSHALL",
    "ftp://internal/backup.tar",
])
def test_non_http_schemes_are_refused(url):
    """file:// would read the env file straight into a PDF a customer downloads."""
    with pytest.raises(ValueError, match="Refusing to fetch"):
        _safe_url_fetcher(url)


def test_an_unresolvable_host_is_refused_rather_than_passed_through():
    with pytest.raises(ValueError, match="Refusing to fetch"):
        _safe_url_fetcher("http://this-host-does-not-exist.invalid/x.png")


# ── What must still work ─────────────────────────────────────────────────────

def test_data_uris_are_allowed():
    """Embedded images are how logos and QR codes reach a report — blocking
    these would break every PDF while stopping no request."""
    tiny_png = (
        "data:image/png;base64,"
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    result = _safe_url_fetcher(tiny_png)
    assert result is not None


def test_the_fetcher_is_actually_wired_into_the_renderer():
    """A perfect fetcher that nothing calls protects nothing."""
    import inspect

    from apps.reports import views

    source = inspect.getsource(views._render_report_pdf_bytes)
    assert "url_fetcher=_safe_url_fetcher" in source
    assert "presentational_hints=False" in source


def test_weasyprint_is_past_the_css_injection_advisory():
    """PYSEC-2026-3412 affects <= 68.1. The fetcher above is defence in depth,
    not a reason to stay on a vulnerable build."""
    from importlib.metadata import version

    major = int(version("weasyprint").split(".")[0])
    assert major >= 69, "weasyprint <= 68.1 carries the CSS-injection SSRF advisory"
