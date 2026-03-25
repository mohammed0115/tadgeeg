"""Post-login redirect service for split platform and vendor contexts."""

from __future__ import annotations


def get_post_login_redirect(user, next_url: str | None = None) -> str:
    """Return the URL a user should reach after successful authentication."""

    if not getattr(user, "is_email_verified", True):
        if not getattr(user, "email_verified_at", None):
            return "/verify-email/"

    from core.permissions import is_org_member, is_platform_user

    if is_platform_user(user):
        return "/platform-admin/"

    if is_org_member(user):
        if next_url and _is_safe_org_redirect(next_url):
            return next_url
        return "/dashboard/"

    return "/dashboard/"


def _is_safe_org_redirect(url: str) -> bool:
    """Return True if an organization redirect target is internal and scoped."""

    if not url or not url.startswith("/") or url.startswith("//"):
        return False

    blocked_prefixes = ("/platform-admin/", "/admin/", "/django-admin/")
    return not any(url.startswith(prefix) for prefix in blocked_prefixes)


def get_context_label(user) -> dict:
    """Return display metadata for the active user context."""

    from core.permissions import is_org_member, is_platform_user

    if is_platform_user(user):
        return {
            "context": "platform",
            "label": "Get Solution Admin Console",
            "label_ar": "لوحة تحكم المنصة",
            "color": "indigo",
        }

    if is_org_member(user):
        organization = getattr(user, "organization", None)
        org_name = getattr(organization, "name", "Organization Dashboard") if organization else "Organization Dashboard"
        return {
            "context": "vendor",
            "label": org_name,
            "label_ar": getattr(organization, "name_ar", org_name) if organization else org_name,
            "color": "blue",
        }

    return {
        "context": "unknown",
        "label": "Dashboard",
        "label_ar": "لوحة التحكم",
        "color": "slate",
    }
