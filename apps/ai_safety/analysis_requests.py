"""Analysis-request admission and duplicate suppression."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone


class AnalysisOrganizationRequired(RuntimeError):
    pass


@dataclass(frozen=True)
class AnalysisAdmission:
    request_id: str
    should_run: bool
    is_cached: bool


def admit_analysis_request(*, organization, document_id, user=None,
                           cooldown_seconds: int | None = None) -> AnalysisAdmission:
    """Record one UI/API analysis request and decide whether provider work runs.

    The check is organization-scoped and serialized. A second click during the
    cooldown becomes an auditable cached event, rather than a second OpenAI
    request and a second billable usage record.
    """
    if not getattr(organization, "pk", None):
        raise AnalysisOrganizationRequired("Analysis requests require an organization.")
    cooldown = int(cooldown_seconds if cooldown_seconds is not None else getattr(
        settings, "AI_ANALYSIS_COOLDOWN_SECONDS", 60
    ))
    from apps.ai_safety.models import AnalysisRequest

    cutoff = timezone.now() - timedelta(seconds=max(0, cooldown))
    with transaction.atomic():
        recent = (
            AnalysisRequest.objects.select_for_update()
            .filter(
                organization=organization,
                document_id=document_id,
                created_at__gte=cutoff,
                is_cached=False,
            )
            .exists()
        )
        request = AnalysisRequest.objects.create(
            organization=organization,
            user=user if getattr(user, "pk", None) else None,
            document_id=document_id,
            is_cached=recent,
        )
    return AnalysisAdmission(
        request_id=str(request.pk),
        should_run=not recent,
        is_cached=recent,
    )
