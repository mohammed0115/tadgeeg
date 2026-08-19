from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import RequestFactory

from apps.authentication.models import Organization
from core.ai.middleware import AIOrganizationContextMiddleware
from core.services.ai_budget import get_current_org_id

User = get_user_model()


@pytest.mark.django_db
def test_ai_organization_context_is_bound_only_for_current_request():
    organization = Organization.objects.create(
        name="Context Tenant",
        name_ar="منظمة السياق",
        country="SA",
        currency="SAR",
        vat_number="300000000000301",
    )
    user = User.objects.create_user(
        email="context@example.test",
        password="StrongPass1!",
        full_name="Context User",
        role=User.Role.SENIOR_AUDITOR,
        organization=organization,
    )
    seen: list[str | None] = []

    def _response(_request):
        seen.append(str(get_current_org_id()))
        return object()

    request = RequestFactory().get("/api/v1/invoices/")
    request.user = user
    AIOrganizationContextMiddleware(_response)(request)

    assert seen == [str(organization.id)]
    assert get_current_org_id() is None
