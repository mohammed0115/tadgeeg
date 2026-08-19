"""Readiness checks for a tenant's configured backup destination."""
from __future__ import annotations

from apps.storage_management.exceptions import StorageConfigurationError
from apps.storage_management.services.storage.resolver import StorageResolver


def backup_destination_readiness(organization) -> dict:
    """Return a non-secret health result for the organization's backup target."""
    resolver = StorageResolver()
    try:
        provider = resolver.get_provider(organization, purpose="backup")
        backend = resolver.get_backend(organization, purpose="backup")
        health = backend.health_check()
    except StorageConfigurationError as exc:
        return {"ready": False, "reason": str(exc), "provider": None}
    return {
        "ready": bool(health.get("healthy")),
        "provider": provider.name,
        "provider_type": provider.provider_type,
        "reason": health.get("message", ""),
    }
