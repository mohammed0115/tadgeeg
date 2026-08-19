from __future__ import annotations

from apps.billing.services.features import require_feature
from apps.api_access.models import OrganizationAPIKey


class APIAccessError(PermissionError):
    pass


_POLICY = {
    "limited": {"max_keys": 1, "monthly_limit": 10_000, "scopes": ["invoices:read", "reports:read"]},
    "full": {"max_keys": 3, "monthly_limit": 100_000, "scopes": ["invoices:read", "invoices:write", "reports:read"]},
}


def issue_key(*, organization, name: str, actor=None):
    decision = require_feature(organization, "api")
    if decision.tier not in _POLICY:
        raise APIAccessError("API contract requires an explicit commercial quota.")
    policy = _POLICY[decision.tier]
    if OrganizationAPIKey.objects.filter(organization=organization, is_active=True).count() >= policy["max_keys"]:
        raise APIAccessError("The package API key limit has been reached.")
    return OrganizationAPIKey.issue(
        organization=organization, name=name, scopes=policy["scopes"],
        monthly_limit=policy["monthly_limit"], created_by=actor,
    )


def revoke_key(*, key: OrganizationAPIKey, actor=None):
    if key.organization_id != getattr(actor, "organization_id", key.organization_id):
        raise APIAccessError("API key tenant mismatch.")
    key.is_active = False
    key.save(update_fields=["is_active", "updated_at"] if hasattr(key, "updated_at") else ["is_active"])
