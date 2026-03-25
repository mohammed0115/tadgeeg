"""
Query helpers (selectors) for storage management.
These functions encapsulate common query patterns and keep views/services thin.
"""
from typing import Optional

from django.db.models import Count, Q, Sum

from apps.storage_management.exceptions import StorageConfigurationError
from apps.storage_management.models import (
    AuditFile,
    OrganizationStoragePolicy,
    StorageProvider,
)
from apps.storage_management.services.storage.resolver import StorageResolver

_resolver = StorageResolver()


def get_storage_provider_for_org(organization, purpose: str = "upload") -> StorageProvider:
    """
    Return the StorageProvider that should handle files for the given
    organisation and purpose.

    Args:
        organization: An Organisation model instance.
        purpose: 'upload', 'backup', 'archive', or 'temp'.

    Returns:
        A StorageProvider instance.

    Raises:
        StorageConfigurationError: if no provider is configured.
    """
    return _resolver.get_provider(organization, purpose=purpose)


def get_default_storage_provider() -> Optional[StorageProvider]:
    """
    Return the global default StorageProvider, or None if none is set.
    """
    return StorageProvider.objects.filter(is_default=True, is_active=True).first()


def get_active_providers():
    """
    Return all active StorageProvider instances, ordered by default-first then name.
    """
    return StorageProvider.objects.filter(is_active=True).order_by("-is_default", "name")


def get_files_for_org(organization, filters: Optional[dict] = None):
    """
    Return a queryset of AuditFile records for the given organisation,
    with optional filter support.

    Args:
        organization: An Organisation model instance.
        filters: Optional dict with supported keys:
            - status (str): AuditFile.Status value
            - file_type (str): e.g. 'pdf'
            - uploaded_by_id (uuid): filter by uploader
            - date_from (date): created_at >= date_from
            - date_to (date): created_at <= date_to
            - search (str): search original_name and checksum

    Returns:
        A Django QuerySet of AuditFile objects.
    """
    qs = AuditFile.objects.filter(organization=organization).select_related(
        "uploaded_by", "organization"
    ).prefetch_related("storage_mappings__storage_provider")

    if not filters:
        return qs

    if filters.get("status"):
        qs = qs.filter(status=filters["status"])

    if filters.get("file_type"):
        qs = qs.filter(file_type__iexact=filters["file_type"])

    if filters.get("uploaded_by_id"):
        qs = qs.filter(uploaded_by_id=filters["uploaded_by_id"])

    if filters.get("date_from"):
        qs = qs.filter(created_at__date__gte=filters["date_from"])

    if filters.get("date_to"):
        qs = qs.filter(created_at__date__lte=filters["date_to"])

    if filters.get("search"):
        term = filters["search"]
        qs = qs.filter(
            Q(original_name__icontains=term) | Q(checksum__icontains=term)
        )

    return qs


def get_storage_stats(organization=None) -> dict:
    """
    Return storage usage statistics.

    Args:
        organization: If provided, scope stats to this organisation.
                      If None, return platform-wide stats.

    Returns:
        dict with:
            - total_files (int)
            - total_size_bytes (int)
            - by_status (dict of status -> count)
            - by_provider (list of dicts: provider_name, file_count, total_bytes)
    """
    qs = AuditFile.objects.all()
    if organization is not None:
        qs = qs.filter(organization=organization)

    total_files = qs.count()
    total_size = qs.aggregate(total=Sum("file_size"))["total"] or 0

    by_status = {}
    for row in qs.values("status").annotate(count=Count("id")):
        by_status[row["status"]] = row["count"]

    # Per-provider breakdown via FileStorageMapping
    from apps.storage_management.models import FileStorageMapping

    mapping_qs = FileStorageMapping.objects.select_related("storage_provider")
    if organization is not None:
        mapping_qs = mapping_qs.filter(file__organization=organization)

    provider_stats = (
        mapping_qs
        .values("storage_provider__name", "storage_provider__provider_type")
        .annotate(file_count=Count("id"), total_bytes=Sum("file_size"))
        .order_by("-total_bytes")
    )

    by_provider = [
        {
            "provider_name": row["storage_provider__name"],
            "provider_type": row["storage_provider__provider_type"],
            "file_count": row["file_count"],
            "total_bytes": row["total_bytes"] or 0,
        }
        for row in provider_stats
    ]

    return {
        "total_files": total_files,
        "total_size_bytes": total_size,
        "by_status": by_status,
        "by_provider": by_provider,
    }
