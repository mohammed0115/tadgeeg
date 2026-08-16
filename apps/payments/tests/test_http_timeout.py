from unittest.mock import patch

from apps.payments.gateways import _http


def test_http_post_uses_default_timeout():
    with patch("apps.payments.gateways._http.assert_outbound_allowed"), patch(
        "apps.payments.gateways._http.requests.post"
    ) as post:
        _http.http_post("https://gateway.example.test/pay")

    assert post.call_args.kwargs["timeout"] == _http.DEFAULT_TIMEOUT_SECONDS


def test_http_get_preserves_explicit_timeout():
    with patch("apps.payments.gateways._http.assert_outbound_allowed"), patch(
        "apps.payments.gateways._http.requests.get"
    ) as get:
        _http.http_get("https://gateway.example.test/status", timeout=3)

    assert get.call_args.kwargs["timeout"] == 3
