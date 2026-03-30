"""Sidebar navigation for the Get Solution platform admin console."""

from django.utils.translation import gettext_lazy as _

from navigation.route_names import PlatformAdminRoute


PLATFORM_MENU = [
    {
        "section": "main",
        "section_label": _("Main"),
        "items": [
            {
                "key": "dashboard",
                "label": _("Platform Overview"),
                "route_name": PlatformAdminRoute.DASHBOARD,
                "icon": "layout-dashboard",
            },
            {
                "key": "organizations",
                "label": _("Organizations"),
                "route_name": PlatformAdminRoute.ORGANIZATIONS,
                "icon": "building-2",
            },
        ],
    },
    {
        "section": "content",
        "section_label": _("Content"),
        "items": [
            {
                "key": "cms_pages",
                "label": _("CMS Pages"),
                "route_name": PlatformAdminRoute.CMS,
                "icon": "file-text",
            },
            {
                "key": "homepage",
                "label": _("Homepage"),
                "route_name": PlatformAdminRoute.HOMEPAGE,
                "icon": "home",
            },
            {
                "key": "about",
                "label": _("About Us"),
                "route_name": PlatformAdminRoute.ABOUT,
                "icon": "info",
            },
            {
                "key": "services",
                "label": _("Services"),
                "route_name": PlatformAdminRoute.SERVICES,
                "icon": "layers-3",
            },
            {
                "key": "pricing",
                "label": _("Pricing Plans"),
                "route_name": PlatformAdminRoute.PRICING,
                "icon": "badge-dollar-sign",
            },
            {
                "key": "faq",
                "label": _("FAQ"),
                "route_name": PlatformAdminRoute.FAQ,
                "icon": "help-circle",
            },
            {
                "key": "intro_video",
                "label": _("Intro Video"),
                "route_name": PlatformAdminRoute.INTRO_VIDEO,
                "icon": "play-circle",
            },
        ],
    },
    {
        "section": "growth",
        "section_label": _("Growth"),
        "items": [
            {
                "key": "jobs",
                "label": _("Jobs"),
                "route_name": PlatformAdminRoute.JOBS,
                "icon": "briefcase",
            },
            {
                "key": "leads",
                "label": _("Contact Leads"),
                "route_name": PlatformAdminRoute.LEADS,
                "icon": "inbox",
            },
            {
                "key": "seo",
                "label": _("SEO"),
                "route_name": PlatformAdminRoute.SEO,
                "icon": "search",
            },
            {
                "key": "media",
                "label": _("Media Library"),
                "route_name": PlatformAdminRoute.MEDIA,
                "icon": "images",
            },
        ],
    },
    {
        "section": "system",
        "section_label": _("System"),
        "items": [
            {
                "key": "storage",
                "label": _("Storage Providers"),
                "route_name": PlatformAdminRoute.STORAGE,
                "icon": "hard-drive",
            },
            {
                "key": "settings",
                "label": _("Platform Settings"),
                "route_name": PlatformAdminRoute.SETTINGS,
                "icon": "settings-2",
            },
            {
                "key": "monitoring",
                "label": _("System Monitoring"),
                "route_name": PlatformAdminRoute.MONITORING,
                "icon": "activity",
            },
            {
                "key": "activity_logs",
                "label": _("Activity Logs"),
                "route_name": PlatformAdminRoute.ACTIVITY_LOGS,
                "icon": "scroll-text",
            },
        ],
    },
]
