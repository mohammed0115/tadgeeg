"""
DRF permission classes for the file management app.

Two permissions are provided:
  - CanManageFiles   — any authenticated user; object-level checks enforce org isolation.
  - CanManageFolders — read access for all authenticated users; write access restricted
                       to admin and cao roles (plus Django staff).
"""
from rest_framework.permissions import BasePermission, SAFE_METHODS

ADMIN_ROLES = {"admin", "cao"}
AUDITOR_ROLES = {
    "senior_auditor",
    "junior_auditor",
    "compliance_officer",
    "finance_manager",
    "external_auditor",
}


class CanManageFiles(BasePermission):
    """
    View-level: any authenticated user may access file endpoints.

    Object-level: a user may only interact with files that belong to their
    organisation (or if they are a Django staff / superuser).
    """

    message = "You do not have permission to access this file."

    def has_permission(self, request, view) -> bool:
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj) -> bool:
        if request.user.is_staff:
            return True

        user_org_id = getattr(request.user, "organization_id", None)
        if user_org_id is None:
            return False

        # obj may be an AuditFile or an AuditFileProfile
        if hasattr(obj, "organization_id"):
            return user_org_id == obj.organization_id

        if hasattr(obj, "audit_file"):
            return user_org_id == obj.audit_file.organization_id

        return False


class CanManageFolders(BasePermission):
    """
    View-level: read (GET/HEAD/OPTIONS) is allowed for any authenticated user.
    Write operations (POST/PUT/PATCH/DELETE) are restricted to admin/cao roles.

    Object-level: folder must belong to the user's organisation.
    """

    message = "You do not have permission to manage folders."

    def has_permission(self, request, view) -> bool:
        if not (request.user and request.user.is_authenticated):
            return False

        if request.method in SAFE_METHODS:
            return True

        if request.user.is_staff:
            return True

        role = getattr(request.user, "role", "")
        return role in ADMIN_ROLES

    def has_object_permission(self, request, view, obj) -> bool:
        if request.user.is_staff:
            return True

        user_org_id = getattr(request.user, "organization_id", None)
        if user_org_id is None:
            return False

        return user_org_id == obj.organization_id
