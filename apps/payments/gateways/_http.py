"""HTTP helpers for payment gateways.

Every outbound call from a gateway adapter goes through
``http_post`` / ``http_get`` here, so the SSRF-allow-list check runs
exactly once per call — adapters don't have to remember to import
the guard separately. (F-10)
"""
from __future__ import annotations

import requests

from core.security.outbound_guard import assert_outbound_allowed


DEFAULT_TIMEOUT_SECONDS = 10


def http_post(url, **kwargs):
    assert_outbound_allowed(url)
    timeout = kwargs.pop("timeout", DEFAULT_TIMEOUT_SECONDS)
    return requests.post(url, timeout=timeout, **kwargs)


def http_get(url, **kwargs):
    assert_outbound_allowed(url)
    timeout = kwargs.pop("timeout", DEFAULT_TIMEOUT_SECONDS)
    return requests.get(url, timeout=timeout, **kwargs)
