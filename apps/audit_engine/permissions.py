from rest_framework.permissions import BasePermission

# Roles permitted to create and run audits
AUDIT_ROLES = {"admin", "cao", "senior_auditor", "compliance_officer"}


class CanRunAudit(BasePermission):
    """
    Grants access to users with a role in AUDIT_ROLES or Django staff status.
    Used for write operations (creating / running audits).
    """

    message = "You do not have permission to run audits."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_staff:
            return True
        role = getattr(request.user, "role", "") or ""
        return role in AUDIT_ROLES


class CanViewAudit(BasePermission):
    """
    Any authenticated user may list/retrieve audits, but only within their organisation.
    """

    message = "You do not have permission to view this audit."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        if request.user.is_staff:
            return True
        user_org_id = getattr(request.user, "organization_id", None)
        return user_org_id is not None and user_org_id == obj.organization_id
