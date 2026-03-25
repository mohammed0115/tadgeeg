"""
DRF permission classes for storage management.
"""
from rest_framework.permissions import BasePermission


class IsOrgAdminOrSuperAdmin(BasePermission):
    """
    Allow access only to staff users or users with admin/org_admin roles.
    Safe methods (GET, HEAD, OPTIONS) are allowed for authenticated users.
    Mutating methods require admin privileges.
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True
        return request.user.is_staff or getattr(request.user, "role", "") in (
            "admin",
            "org_admin",
        )


class IsOrgMember(BasePermission):
    """
    Allow access to any authenticated user (organisation membership is
    enforced at the queryset level in each view).
    """

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)


class BelongsToSameOrg(BasePermission):
    """
    Object-level permission — ensures the object belongs to the same
    organisation as the requesting user. Staff bypass this check.
    """

    def has_object_permission(self, request, view, obj):
        if request.user.is_staff:
            return True
        user_org = getattr(request.user, "organization_id", None)
        # Support direct organization_id or nested organization FK
        obj_org = getattr(obj, "organization_id", None)
        if obj_org is None:
            nested = getattr(obj, "organization", None)
            obj_org = getattr(nested, "id", None)
        return user_org is not None and user_org == obj_org
