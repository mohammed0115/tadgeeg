"""Custom DRF Permission classes"""

from rest_framework.permissions import BasePermission
from .models import User


class IsAdminUser(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == User.Role.ADMIN


class IsSameUserOrAdmin(BasePermission):
    def has_object_permission(self, request, view, obj):
        return request.user.is_authenticated and (
            request.user == obj or request.user.role == User.Role.ADMIN
        )


class IsSeniorAuditorOrAbove(BasePermission):
    ALLOWED_ROLES = [
        User.Role.ADMIN,
        User.Role.CHIEF_AUDIT_OFFICER,
        User.Role.SENIOR_AUDITOR,
    ]

    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role in self.ALLOWED_ROLES


class IsComplianceOrAbove(BasePermission):
    ALLOWED_ROLES = [
        User.Role.ADMIN,
        User.Role.CHIEF_AUDIT_OFFICER,
        User.Role.SENIOR_AUDITOR,
        User.Role.COMPLIANCE_OFFICER,
    ]

    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role in self.ALLOWED_ROLES


class IsOwnOrganization(BasePermission):
    """Only allows access to resources within the user's organization."""

    def has_object_permission(self, request, view, obj):
        if request.user.role == User.Role.ADMIN:
            return True
        if hasattr(obj, "organization_id"):
            return obj.organization_id == request.user.organization_id
        if hasattr(obj, "organization"):
            return obj.organization == request.user.organization
        return False
