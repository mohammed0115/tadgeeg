"""
Read-only query helpers for file management.

All functions return QuerySets or plain Python structures — no writes happen here.
"""
from typing import Optional

from django.db.models import Count, Q, QuerySet, Sum

from apps.file_management.models import AuditFileProfile, Folder
from apps.storage_management.models import AuditFile


def get_files_for_org(organization, filters: Optional[dict] = None) -> QuerySet:
    """
    Return an AuditFile QuerySet scoped to the given organisation.

    Supported filter keys
    ---------------------
    file_type : str
        Exact match on AuditFile.file_type (e.g. "pdf", "xlsx").
    status : str
        Exact match on AuditFile.status (uses AuditFile.Status choices).
    folder_id : UUID | str
        Filter to files whose profile is placed in the given folder.
    date_from : datetime
        Inclusive lower bound on AuditFile.created_at.
    date_to : datetime
        Inclusive upper bound on AuditFile.created_at.
    search : str
        Case-insensitive substring match on AuditFile.original_name.
    """
    qs = (
        AuditFile.objects
        .filter(organization=organization)
        .select_related("profile", "profile__folder", "uploaded_by", "organization")
    )

    if not filters:
        return qs

    if filters.get("file_type"):
        qs = qs.filter(file_type=filters["file_type"])

    if filters.get("status"):
        qs = qs.filter(status=filters["status"])

    if filters.get("folder_id"):
        qs = qs.filter(profile__folder_id=filters["folder_id"])

    if filters.get("date_from"):
        qs = qs.filter(created_at__gte=filters["date_from"])

    if filters.get("date_to"):
        qs = qs.filter(created_at__lte=filters["date_to"])

    if filters.get("search"):
        qs = qs.filter(original_name__icontains=filters["search"])

    return qs


def get_folders_for_org(organization, parent_id=None) -> QuerySet:
    """
    Return a Folder QuerySet for the given organisation.

    When `parent_id` is None, only root folders (parent IS NULL) are returned.
    Pass a UUID to retrieve direct children of that folder.
    """
    qs = Folder.objects.filter(organization=organization).select_related(
        "parent", "created_by"
    )
    if parent_id:
        qs = qs.filter(parent_id=parent_id)
    else:
        qs = qs.filter(parent__isnull=True)
    return qs


def get_folder_tree(organization) -> list:
    """
    Return the complete folder hierarchy for an organisation as a nested list
    of dicts.

    Each dict has the keys: id, name, slug, children (list, recursive).
    This performs one DB query per level; acceptable for moderate tree depths.
    For very deep trees consider a CTE/ltree solution.
    """

    def build_tree(parent_id=None) -> list:
        folders = Folder.objects.filter(
            organization=organization, parent_id=parent_id
        ).order_by("name")
        return [
            {
                "id": str(f.id),
                "name": f.name,
                "slug": f.slug,
                "children": build_tree(f.id),
            }
            for f in folders
        ]

    return build_tree()


def get_file_storage_stats(organization) -> dict:
    """
    Return aggregate storage statistics for the given organisation.

    Returns
    -------
    dict
        total_files : int  — number of AuditFile rows
        total_size_bytes : int — sum of file_size across all files
    """
    result = AuditFile.objects.filter(organization=organization).aggregate(
        total_files=Count("id"),
        total_size=Sum("file_size"),
    )
    return {
        "total_files": result["total_files"] or 0,
        "total_size_bytes": result["total_size"] or 0,
    }


def get_file_by_id(file_id, organization) -> AuditFile:
    """
    Retrieve a single AuditFile by primary key, scoped to the organisation.

    Raises
    ------
    AuditFile.DoesNotExist
        If no matching file exists within the organisation.
    """
    return (
        AuditFile.objects
        .select_related("profile", "profile__folder", "uploaded_by", "organization")
        .get(id=file_id, organization=organization)
    )
