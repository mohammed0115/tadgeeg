from __future__ import annotations

from apps.api_access.models import OrganizationAPIKey


def list_safe_api_keys(organization):
    return OrganizationAPIKey.objects.filter(organization=organization).values(
        "id", "name", "key_prefix", "scopes", "monthly_limit", "used_this_month", "is_active", "created_at", "revoked_at"
    )


def get_api_key_for_organization(organization, key_id):
    return OrganizationAPIKey.objects.filter(pk=key_id, organization=organization).first()
