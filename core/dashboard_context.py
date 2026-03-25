"""Context builders for the split dashboard layouts."""

from __future__ import annotations

from navigation.platform_menu import PLATFORM_MENU
from navigation.vendor_menu import VENDOR_MENU


def _resolve_menu_position(menu: list[dict], active_key: str) -> tuple[dict | None, dict | None]:
    for section in menu:
        for item in section.get("items", []):
            if item.get("key") == active_key:
                return section, item
    return None, None


def get_org_switcher_options(user) -> list[dict]:
    """Return organization switcher options.

    The current schema supports one organization per user. This helper keeps the
    layout extensible for a future multi-membership model without inventing a
    fake switcher behavior today.
    """

    organization = getattr(user, "organization", None)
    if organization is None:
        return []
    return [
        {
            "id": str(organization.id),
            "name": organization.name,
            "name_ar": organization.name_ar or organization.name,
            "is_current": True,
        }
    ]


def build_platform_context(request, *, active_key: str, **extra) -> dict:
    section, item = _resolve_menu_position(PLATFORM_MENU, active_key)
    breadcrumb_parent = (
        section.get("section_label_ar")
        if section and section.get("section") != "main"
        else "لوحة المنصة"
    )
    breadcrumb_current = item.get("label_ar") if item else "الرئيسية"
    return {
        "platform_menu": PLATFORM_MENU,
        "active_key": active_key,
        "console_context": "platform_admin",
        "console_label": "Get Solution Admin Console",
        "console_label_ar": "لوحة إدارة منصة Get Solution",
        "console_accent": "indigo",
        "breadcrumb_parent": breadcrumb_parent,
        "breadcrumb_current": breadcrumb_current,
        "current_section": section,
        "current_item": item,
        **extra,
    }


def build_vendor_context(request, *, active_key: str, **extra) -> dict:
    organization = getattr(request.user, "organization", None)
    section, item = _resolve_menu_position(VENDOR_MENU, active_key)
    breadcrumb_parent = (
        section.get("section_label_ar")
        if section and section.get("section") != "main"
        else "لوحة المنظمة"
    )
    breadcrumb_current = item.get("label_ar") if item else "الرئيسية"
    return {
        "vendor_menu": VENDOR_MENU,
        "active_key": active_key,
        "console_context": "vendor_dashboard",
        "org": organization,
        "org_name": getattr(organization, "name", "Organization Dashboard") if organization else "Organization Dashboard",
        "org_name_ar": getattr(organization, "name_ar", "") if organization else "",
        "organization_switcher_options": get_org_switcher_options(request.user),
        "console_accent": "sky",
        "breadcrumb_parent": breadcrumb_parent,
        "breadcrumb_current": breadcrumb_current,
        "current_section": section,
        "current_item": item,
        **extra,
    }
