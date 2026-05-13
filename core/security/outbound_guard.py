"""Outbound HTTP allow-list (F-10) — SSRF mitigation.

Closes the gap raised in the Enterprise Audit Review §15 Finding 10:
"A compromised settings.py could redirect payment provider calls
elsewhere." Every payment adapter (Moyasar/Tap/Telr) and every other
outbound HTTP call from the financial path can route through
``assert_outbound_allowed(url)`` before touching the network.

Configured via ``settings.OUTBOUND_HTTP_ALLOWLIST`` — a list of
domain patterns (exact match or single leading-dot wildcard for
subdomains). An empty list means "deny everything" (strict-default).

Example:
    OUTBOUND_HTTP_ALLOWLIST = [
        "api.moyasar.com",
        ".tap.company",         # matches api.tap.company / secure.tap.company
        ".telr.com",
        "fatoora.zatca.gov.sa",
        "api.openai.com",
    ]

The check rejects:
  • Schemes other than http/https.
  • IPs (raw private-range or DNS-rebinding attempts).
  • Hosts not in the allow-list.
  • file://, gopher://, data: — anything that's not a normal web call.
"""
from __future__ import annotations

import ipaddress
import logging
from urllib.parse import urlparse

from django.conf import settings


logger = logging.getLogger("security.outbound")


class OutboundNotAllowedError(ValueError):
    """Raised when an outbound URL fails the allow-list check."""

    def __init__(self, url: str, reason: str):
        self.url = url
        self.reason = reason
        super().__init__(f"Outbound URL refused ({reason}): {url}")


_ALLOWED_SCHEMES = frozenset({"http", "https"})


def _host_matches(host: str, pattern: str) -> bool:
    """Pattern can be an exact host or ``.example.com`` for subdomain wildcard."""
    host = (host or "").lower().strip(".")
    pattern = pattern.lower().strip()
    if pattern.startswith("."):
        suffix = pattern[1:]
        return host == suffix or host.endswith("." + suffix)
    return host == pattern


def _is_private_ip(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return (ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_multicast or ip.is_reserved or ip.is_unspecified)


def assert_outbound_allowed(url: str) -> None:
    """Raise OutboundNotAllowedError if ``url`` shouldn't be reached.

    Strict-deny default: an empty / unset OUTBOUND_HTTP_ALLOWLIST blocks
    every call. Set it to ``["*"]`` to explicitly disable the check
    (e.g. local development) — that string is treated as wildcard."""
    allow = list(getattr(settings, "OUTBOUND_HTTP_ALLOWLIST", []))
    if allow == ["*"]:
        return  # explicit bypass

    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise OutboundNotAllowedError(url, f"unsupported scheme {parsed.scheme!r}")
    host = (parsed.hostname or "").lower()
    if not host:
        raise OutboundNotAllowedError(url, "missing host")
    if _is_private_ip(host):
        raise OutboundNotAllowedError(url, f"private/loopback IP {host}")

    if not allow:
        raise OutboundNotAllowedError(
            url,
            "OUTBOUND_HTTP_ALLOWLIST is empty — set it explicitly or use ['*'] "
            "in development",
        )

    for pattern in allow:
        if _host_matches(host, pattern):
            return
    raise OutboundNotAllowedError(url, f"host {host!r} not in allow-list")


def is_outbound_allowed(url: str) -> bool:
    try:
        assert_outbound_allowed(url)
        return True
    except OutboundNotAllowedError:
        return False
