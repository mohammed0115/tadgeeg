"""Namespace-level access control for split dashboard routes."""

from __future__ import annotations

from django.http import HttpResponseForbidden
from django.shortcuts import redirect

from core.permissions import is_org_member, is_platform_user


class NamespaceAccessControlMiddleware:
    """Guard dashboard namespaces by path prefix."""

    PLATFORM_PREFIXES = ("/platform-admin/", "/api/platform-admin/")
    VENDOR_PREFIXES = ("/dashboard/", "/api/dashboard/", "/api/org/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path

        if path.startswith(self.PLATFORM_PREFIXES):
            response = self._guard_platform(request)
            if response is not None:
                return response

        if path.startswith(self.VENDOR_PREFIXES):
            response = self._guard_vendor(request)
            if response is not None:
                return response

        return self.get_response(request)

    def _guard_platform(self, request):
        user = getattr(request, "user", None)
        if not getattr(user, "is_authenticated", False):
            return redirect(f"/login/?next={request.path}")
        if is_platform_user(user):
            return None
        if is_org_member(user):
            return redirect("/dashboard/")
        if request.path.startswith("/api/"):
            return HttpResponseForbidden("Platform admin access is required.")
        return redirect("/login/")

    def _guard_vendor(self, request):
        user = getattr(request, "user", None)
        if not getattr(user, "is_authenticated", False):
            return redirect(f"/login/?next={request.path}")
        if is_org_member(user):
            return None
        if is_platform_user(user):
            return redirect("/platform-admin/")
        if request.path.startswith("/api/"):
            return HttpResponseForbidden("Organization membership is required.")
        return redirect("/login/")
