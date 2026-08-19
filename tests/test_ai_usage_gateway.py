"""Contract tests for the tenant-aware OpenAI usage gateway."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from apps.authentication.models import Organization
from core.ai import gateway


class _SuccessCompletions:
    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            id="cmpl_test_123",
            model="gpt-4o-mini",
            usage=SimpleNamespace(prompt_tokens=120, completion_tokens=30),
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))],
        )


class _SuccessClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.chat = SimpleNamespace(completions=_SuccessCompletions())


class _AuthenticationFailureCompletions:
    def create(self, **kwargs):
        error = RuntimeError("authentication failed")
        error.status_code = 401
        raise error


class _AuthenticationFailureClient:
    def __init__(self, **kwargs):
        self.chat = SimpleNamespace(completions=_AuthenticationFailureCompletions())


def _organization() -> Organization:
    return Organization.objects.create(
        name="AI Usage Tenant",
        name_ar="منظمة قياس الذكاء",
        country="SA",
        currency="SAR",
        vat_number="300000000000001",
    )


@pytest.mark.django_db
def test_gateway_requires_organization_before_provider_call():
    with pytest.raises(gateway.AIOrganizationRequired):
        gateway.chat_completion(
            organization=None,
            operation="assistant",
            messages=[{"role": "user", "content": "hello"}],
            client_factory=_SuccessClient,
        )


@pytest.mark.django_db
def test_gateway_persists_success_tokens_price_and_sanitized_payload(settings):
    from apps.ai_safety.models import AIUsageRecord

    settings.AI_USAGE_MODEL_PRICES_PER_MILLION = {
        "gpt-4o-mini": {"prompt": "0.15", "completion": "0.60"},
    }
    org = _organization()
    response = gateway.chat_completion(
        organization=org,
        operation="extraction",
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "normal input"}],
        max_tokens=100,
        client_factory=_SuccessClient,
        extra_headers={"Authorization": "Bearer must-not-persist"},
    )

    assert response.id == "cmpl_test_123"
    record = AIUsageRecord.objects.get(organization=org)
    assert record.status == AIUsageRecord.Status.SUCCESS
    assert record.operation == "extraction"
    assert record.prompt_tokens == 120
    assert record.completion_tokens == 30
    assert str(record.estimated_cost) == "0.000036"
    assert record.payload.request_payload["extra_headers"]["Authorization"] == "<redacted>"
    assert record.payload.response_payload["content"] == '{"ok": true}'


@pytest.mark.django_db
def test_gateway_persists_auth_failure_without_hiding_it():
    from apps.ai_safety.models import AIUsageRecord

    org = _organization()
    with pytest.raises(RuntimeError, match="authentication failed"):
        gateway.chat_completion(
            organization=org,
            operation="classification",
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "hello"}],
            client_factory=_AuthenticationFailureClient,
        )

    record = AIUsageRecord.objects.get(organization=org)
    assert record.status == AIUsageRecord.Status.FAILED
    assert record.failure_kind == AIUsageRecord.FailureKind.AUTH_401
