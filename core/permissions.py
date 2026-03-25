"""Unified permission layer for the split platform/vendor architecture."""

from __future__ import annotations

from functools import wraps

from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from rest_framework import permissions

PLATFORM_ROLES = frozenset(
    {
        "PLATFORM_SUPER_ADMIN",
        "PLATFORM_CONTENT_ADMIN",
        "PLATFORM_MARKETING_ADMIN",
        "PLATFORM_HR_ADMIN",
        "PLATFORM_SUPPORT_ADMIN",
    }
)
ORG_ROLES = frozenset({"ORG_ADMIN", "ORG_AUDITOR", "ORG_USER"})

LEGACY_PLATFORM_ROLE_MAP = {
    "admin": "PLATFORM_SUPER_ADMIN",
    "compliance_officer": "PLATFORM_CONTENT_ADMIN",
    "finance_manager": "PLATFORM_MARKETING_ADMIN",
    "external_auditor": "PLATFORM_SUPPORT_ADMIN",
}
LEGACY_ORG_ADMIN_ROLES = frozenset({"admin"})
LEGACY_ORG_AUDITOR_ROLES = frozenset({"cao", "senior_auditor", "junior_auditor"})


def is_platform_user(user) -> bool:
    return bool(user and user.is_authenticated and (user.is_staff or user.is_superuser))


def is_platform_superadmin(user) -> bool:
    return bool(user and user.is_authenticated and user.is_superuser)


def has_organization_membership(user) -> bool:
    return bool(user and user.is_authenticated and getattr(user, "organization_id", None))


def is_org_member(user) -> bool:
    """Return True only for users allowed into the vendor dashboard.

    Platform staff remain in the platform console unless an explicit
    impersonation flow is introduced.
    """

    return bool(has_organization_membership(user) and not is_platform_user(user))


def is_org_admin(user) -> bool:
    return bool(is_org_member(user) and getattr(user, "role", None) in LEGACY_ORG_ADMIN_ROLES)


def is_org_auditor(user) -> bool:
    return bool(is_org_member(user) and getattr(user, "role", None) in LEGACY_ORG_AUDITOR_ROLES)


def get_effective_platform_role(user) -> str | None:
    if not is_platform_user(user):
        return None
    if is_platform_superadmin(user):
        return "PLATFORM_SUPER_ADMIN"
    return LEGACY_PLATFORM_ROLE_MAP.get(getattr(user, "role", ""), "PLATFORM_SUPPORT_ADMIN")


def get_effective_org_role(user) -> str | None:
    if not is_org_member(user):
        return None
    role = getattr(user, "role", "")
    if role in LEGACY_ORG_ADMIN_ROLES:
        return "ORG_ADMIN"
    if role in LEGACY_ORG_AUDITOR_ROLES:
        return "ORG_AUDITOR"
    return "ORG_USER"


def is_same_organization_object(user, obj) -> bool:
    if not is_org_member(user):
        return False
    obj_org_id = getattr(obj, "organization_id", None)
    if obj_org_id is None and getattr(obj, "organization", None) is not None:
        obj_org_id = getattr(obj.organization, "pk", None)
    return str(obj_org_id) == str(getattr(user, "organization_id", None))


class IsPlatformAdmin(permissions.BasePermission):
    message = "Platform admin access is required."

    def has_permission(self, request, view):
        return is_platform_user(request.user)


class IsPlatformSuperAdmin(permissions.BasePermission):
    message = "Platform super admin access is required."

    def has_permission(self, request, view):
        return is_platform_superadmin(request.user)


class IsOrganizationMember(permissions.BasePermission):
    message = "Organization membership is required."

    def has_permission(self, request, view):
        return is_org_member(request.user)


class IsOrganizationAdmin(permissions.BasePermission):
    message = "Organization admin access is required."

    def has_permission(self, request, view):
        return is_org_admin(request.user)


class IsOrganizationAuditor(permissions.BasePermission):
    message = "Organization auditor access is required."

    def has_permission(self, request, view):
        return is_org_admin(request.user) or is_org_auditor(request.user)


class IsOrganizationScopedObject(permissions.BasePermission):
    message = "The requested object is outside the active organization."

    def has_object_permission(self, request, view, obj):
        return is_same_organization_object(request.user, obj)


def platform_admin_required(view_func=None, *, redirect_url="/login/"):
    def decorator(func):
        @wraps(func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect(f"{redirect_url}?next={request.path}")
            if not is_platform_user(request.user):
                if is_org_member(request.user):
                    return redirect("/dashboard/")
                return HttpResponseForbidden("Platform admin access is required.")
            return func(request, *args, **kwargs)

        return wrapper

    return decorator(view_func) if view_func else decorator


def platform_super_admin_required(view_func=None, *, redirect_url="/login/"):
    def decorator(func):
        @wraps(func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect(f"{redirect_url}?next={request.path}")
            if not is_platform_superadmin(request.user):
                if is_platform_user(request.user):
                    return HttpResponseForbidden("Platform super admin access is required.")
                if is_org_member(request.user):
                    return redirect("/dashboard/")
                return redirect(redirect_url)
            return func(request, *args, **kwargs)

        return wrapper

    return decorator(view_func) if view_func else decorator


def org_member_required(view_func=None, *, redirect_url="/login/"):
    def decorator(func):
        @wraps(func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect(f"{redirect_url}?next={request.path}")
            if not is_org_member(request.user):
                if is_platform_user(request.user):
                    return redirect("/platform-admin/")
                return HttpResponseForbidden("Organization membership is required.")
            return func(request, *args, **kwargs)

        return wrapper

    return decorator(view_func) if view_func else decorator


def org_admin_required(view_func=None, *, redirect_url="/login/"):
    def decorator(func):
        @wraps(func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect(f"{redirect_url}?next={request.path}")
            if not is_org_admin(request.user):
                if is_platform_user(request.user):
                    return redirect("/platform-admin/")
                return HttpResponseForbidden("Organization admin access is required.")
            return func(request, *args, **kwargs)

        return wrapper

    return decorator(view_func) if view_func else decorator


def org_auditor_required(view_func=None, *, redirect_url="/login/"):
    def decorator(func):
        @wraps(func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect(f"{redirect_url}?next={request.path}")
            if not (is_org_admin(request.user) or is_org_auditor(request.user)):
                if is_platform_user(request.user):
                    return redirect("/platform-admin/")
                return HttpResponseForbidden("Organization auditor access is required.")
            return func(request, *args, **kwargs)

        return wrapper

    return decorator(view_func) if view_func else decorator


class PlatformAdminMixin:
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"/login/?next={request.path}")
        if not is_platform_user(request.user):
            if is_org_member(request.user):
                return redirect("/dashboard/")
            return HttpResponseForbidden("Platform admin access is required.")
        return super().dispatch(request, *args, **kwargs)


class PlatformSuperAdminMixin:
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"/login/?next={request.path}")
        if not is_platform_superadmin(request.user):
            return HttpResponseForbidden("Platform super admin access is required.")
        return super().dispatch(request, *args, **kwargs)


class OrgMemberMixin:
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"/login/?next={request.path}")
        if not is_org_member(request.user):
            if is_platform_user(request.user):
                return redirect("/platform-admin/")
            return HttpResponseForbidden("Organization membership is required.")
        return super().dispatch(request, *args, **kwargs)


class OrgAdminMixin:
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"/login/?next={request.path}")
        if not is_org_admin(request.user):
            if is_platform_user(request.user):
                return redirect("/platform-admin/")
            return HttpResponseForbidden("Organization admin access is required.")
        return super().dispatch(request, *args, **kwargs)


class OrgAuditorMixin:
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"/login/?next={request.path}")
        if not (is_org_admin(request.user) or is_org_auditor(request.user)):
            if is_platform_user(request.user):
                return redirect("/platform-admin/")
            return HttpResponseForbidden("Organization auditor access is required.")
        return super().dispatch(request, *args, **kwargs)
