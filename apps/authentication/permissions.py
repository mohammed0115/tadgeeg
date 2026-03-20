"""Custom DRF Permission classes"""

from rest_framework.permissions import BasePermission
from .models import User


class IsAdminUser(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.can_manage_users


class IsSameUserOrAdmin(BasePermission):
    def has_object_permission(self, request, view, obj):
        return request.user.is_authenticated and (
            request.user == obj or request.user.can_manage_users
        )


class IsSeniorAuditorOrAbove(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.has_role_capability("approve_invoices")


class IsComplianceOrAbove(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.has_role_capability("review_findings")


class IsOwnOrganization(BasePermission):
    """Only allows access to resources within the user's organization."""

    def has_object_permission(self, request, view, obj):
        if not request.user.is_authenticated:
            return False
        if request.user.can_manage_users:
            return True
        if hasattr(obj, "organization_id"):
            return obj.organization_id == request.user.organization_id
        if hasattr(obj, "organization"):
            return obj.organization == request.user.organization
        return False


class CanViewExecutiveDashboard(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.has_role_capability("view_executive_dashboard")


class RequiresOrganization(BasePermission):
    """
    Blocks authenticated users who have no organization from accessing tenant-scoped data.
    Superusers bypass this check (they operate across all tenants).
    Apply this alongside IsAuthenticated on any view that scopes data by organization.
    """
    message = "Your account is not linked to an organization. Contact your administrator."

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return True  # Let IsAuthenticated handle unauthenticated users
        if getattr(request.user, "is_superuser", False):
            return True  # Superusers are not tenant-scoped
        return bool(getattr(request.user, "organization_id", None))
