from unittest.mock import patch

from apps.webhooks.models import WebhookDelivery, WebhookEndpoint
from apps.webhooks.services import emit


def test_emit_same_event_creates_one_delivery_and_one_dispatch(organization):
    endpoint = WebhookEndpoint.objects.create(
        organization=organization,
        url="https://hooks.example.test/tadgeeg",
        secret="test-secret",
        events=["invoice.created"],
    )
    payload = {"invoice_id": "inv-1", "total": "115.00"}

    with patch("core.services.async_runner.run_in_background") as enqueue:
        assert emit("invoice.created", organization, payload) == 1
        assert emit("invoice.created", organization, payload) == 0

    assert WebhookDelivery.objects.filter(endpoint=endpoint).count() == 1
    assert enqueue.call_count == 1


def test_emit_distinct_event_payload_creates_distinct_delivery(organization):
    endpoint = WebhookEndpoint.objects.create(
        organization=organization,
        url="https://hooks.example.test/tadgeeg",
        secret="test-secret",
        events=["invoice.created"],
    )

    with patch("core.services.async_runner.run_in_background"):
        emit("invoice.created", organization, {"invoice_id": "inv-1"})
        emit("invoice.created", organization, {"invoice_id": "inv-2"})

    assert WebhookDelivery.objects.filter(endpoint=endpoint).count() == 2
