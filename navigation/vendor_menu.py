"""Sidebar navigation for the organization dashboard."""

from django.utils.translation import gettext_lazy as _

from navigation.route_names import VendorDashboardRoute


VENDOR_MENU = [
    {
        "section": "main",
        "section_label": _("Main"),
        "items": [
            {
                "key": "overview",
                "label": _("Organization Overview"),
                "route_name": VendorDashboardRoute.DASHBOARD,
                "icon": "layout-dashboard",
            },
        ],
    },
    {
        "section": "files",
        "section_label": _("Files"),
        "items": [
            {
                "key": "files",
                "label": _("My Files"),
                "route_name": VendorDashboardRoute.FILES,
                "icon": "files",
            },
            {
                "key": "folders",
                "label": _("Folders"),
                "route_name": VendorDashboardRoute.FOLDERS,
                "icon": "folder-tree",
            },
            {
                "key": "upload",
                "label": _("Upload Center"),
                "route_name": VendorDashboardRoute.UPLOAD,
                "icon": "upload-cloud",
            },
        ],
    },
    {
        "section": "audit",
        "section_label": _("Audit"),
        "items": [
            {
                "key": "audits",
                "label": _("Audit Jobs"),
                "route_name": VendorDashboardRoute.AUDITS,
                "icon": "shield-check",
            },
            {
                "key": "audit_results",
                "label": _("Audit Results"),
                "route_name": VendorDashboardRoute.AUDIT_RESULTS,
                "icon": "shield-alert",
            },
            {
                "key": "reports",
                "label": _("Reports"),
                "route_name": VendorDashboardRoute.REPORTS,
                "icon": "bar-chart-3",
            },
        ],
    },
    {
        "section": "organization",
        "section_label": _("Organization"),
        "items": [
            {
                "key": "team",
                "label": _("Team Members"),
                "route_name": VendorDashboardRoute.TEAM,
                "icon": "users",
            },
            {
                "key": "org_settings",
                "label": _("Organization Settings"),
                "route_name": VendorDashboardRoute.SETTINGS,
                "icon": "settings",
            },
            {
                "key": "storage_usage",
                "label": _("Storage Usage"),
                "route_name": VendorDashboardRoute.STORAGE,
                "icon": "hard-drive",
            },
            {
                "key": "billing",
                "label": _("Billing"),
                "route_name": VendorDashboardRoute.BILLING,
                "icon": "credit-card",
            },
            {
                "key": "notifications",
                "label": _("Notifications"),
                "route_name": VendorDashboardRoute.NOTIFICATIONS,
                "icon": "bell",
            },
        ],
    },
]
