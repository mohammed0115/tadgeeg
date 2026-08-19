from __future__ import annotations

import uuid

import pytest

from apps.ai_safety.analysis_requests import admit_analysis_request
from apps.authentication.models import Organization


def _organization(name: str, vat_number: str) -> Organization:
    return Organization.objects.create(
        name=name,
        name_ar=name,
        country="SA",
        currency="SAR",
        vat_number=vat_number,
    )


@pytest.mark.django_db
def test_second_request_for_same_org_document_is_cached_not_run():
    from apps.ai_safety.models import AnalysisRequest

    organization = _organization("Analysis tenant", "300000000000101")
    document_id = uuid.uuid4()

    first = admit_analysis_request(
        organization=organization, document_id=document_id, cooldown_seconds=60
    )
    second = admit_analysis_request(
        organization=organization, document_id=document_id, cooldown_seconds=60
    )

    assert first.should_run is True
    assert first.is_cached is False
    assert second.should_run is False
    assert second.is_cached is True
    assert list(AnalysisRequest.objects.values_list("is_cached", flat=True)) == [True, False]


@pytest.mark.django_db
def test_analysis_cooldown_is_tenant_scoped():
    document_id = uuid.uuid4()
    org_a = _organization("Tenant A", "300000000000102")
    org_b = _organization("Tenant B", "300000000000103")

    first = admit_analysis_request(
        organization=org_a, document_id=document_id, cooldown_seconds=60
    )
    other_tenant = admit_analysis_request(
        organization=org_b, document_id=document_id, cooldown_seconds=60
    )

    assert first.should_run is True
    assert other_tenant.should_run is True
