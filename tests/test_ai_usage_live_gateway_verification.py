"""One opt-in live provider verification through the tenant usage gateway.

Run explicitly only:
  DJANGO_SETTINGS_MODULE=finai_backend.settings.test \
  pytest -q --no-cov tests/test_ai_usage_live_gateway_verification.py

The test asserts accounting metadata only; it neither prints credentials nor
records the provider response content in assertions/output.
"""
from __future__ import annotations

import os

import pytest

from apps.authentication.models import Organization
from core.ai.gateway import chat_completion


pytestmark = pytest.mark.live_ai


@pytest.mark.django_db
def test_one_live_gateway_call_writes_successful_usage_record(settings):
    if not os.environ.get("OPENAI_API_BASE") or not settings.OPENAI_API_KEY:
        pytest.skip("Live AI proxy credentials are not available in this environment.")

    from apps.ai_safety.models import AIUsageRecord

    settings.AI_USAGE_MODEL_PRICES_PER_MILLION = {
        **settings.AI_USAGE_MODEL_PRICES_PER_MILLION,
        "gpt-5-nano": {"prompt": "0.05", "completion": "0.40"},
    }
    organization = Organization.objects.create(
        name="AI Gateway Live Verification",
        name_ar="منظمة التحقق الحي لبوابة الذكاء",
        country="SA",
        currency="SAR",
        vat_number="300000000000902",
    )

    chat_completion(
        organization=organization,
        operation="health",
        model="gpt-5-nano",
        messages=[{"role": "user", "content": "Reply exactly: ok"}],
        max_tokens=8,
        timeout=20,
    )

    record = AIUsageRecord.objects.get(organization=organization)
    assert record.status == AIUsageRecord.Status.SUCCESS
    assert record.prompt_tokens > 0
    assert record.completion_tokens > 0
    assert record.estimated_cost > 0
    assert record.payload.response_payload["usage"]["prompt_tokens"] == record.prompt_tokens
    assert record.payload.response_payload["usage"]["completion_tokens"] == record.completion_tokens
