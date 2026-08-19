"""Run one bounded live gateway verification without exposing credentials.

Usage:
  DJANGO_SETTINGS_MODULE=finai_backend.settings.test \
  python scripts/verify_ai_usage_gateway_live.py

The script leaves the resulting AIUsageRecord intact so the caller can inspect
accounting evidence. It deliberately prints no request/response content.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Direct script execution starts with scripts/ on sys.path, not the project root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "finai_backend.settings.test")
django.setup()

from apps.ai_safety.models import AIUsageRecord
from apps.authentication.models import Organization
from core.ai.gateway import chat_completion


ORG_NAME = "AI Usage Gateway Local Verification"
ORG_VAT = "300000000000901"


def main() -> int:
    organization, _ = Organization.objects.get_or_create(
        vat_number=ORG_VAT,
        defaults={
            "name": ORG_NAME,
            "name_ar": "منظمة تحقق قياس الذكاء الاصطناعي",
            "country": "SA",
            "currency": "SAR",
        },
    )
    before = AIUsageRecord.objects.filter(organization=organization).count()
    try:
        chat_completion(
            organization=organization,
            operation="health",
            model="gpt-5-nano",
            messages=[{"role": "user", "content": "Reply exactly: ok"}],
            max_tokens=8,
            timeout=20,
        )
    except Exception as exc:
        record = AIUsageRecord.objects.filter(organization=organization).first()
        print({
            "provider_success": False,
            "error_class": type(exc).__name__,
            "usage_recorded": record is not None,
            "status": getattr(record, "status", None),
            "failure_kind": getattr(record, "failure_kind", None),
        })
        return 2

    record = AIUsageRecord.objects.filter(organization=organization).first()
    if record is None or record.status != AIUsageRecord.Status.SUCCESS:
        print({"provider_success": False, "usage_recorded": False})
        return 3
    print({
        "provider_success": True,
        "usage_recorded": True,
        "record_id": str(record.id),
        "model": record.model,
        "prompt_tokens": record.prompt_tokens,
        "completion_tokens": record.completion_tokens,
        "estimated_cost": str(record.estimated_cost),
        "record_count_before": before,
        "record_count_after": before + 1,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
