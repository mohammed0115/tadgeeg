"""HTTP helpers for payment gateways.

Every outbound call from a gateway adapter goes through
``http_post`` / ``http_get`` here, so the SSRF-allow-list check runs
exactly once per call — adapters don't have to remember to import
the guard separately. (F-10)
"""
from __future__ import annotations

import requests

from core.security.outbound_guard import assert_outbound_allowed


def http_post(url, **kwargs):
    assert_outbound_allowed(url)
    return requests.post(url, **kwargs)


def http_get(url, **kwargs):
    assert_outbound_allowed(url)
    return requests.get(url, **kwargs)
