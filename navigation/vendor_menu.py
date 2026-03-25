"""Sidebar navigation for the organization dashboard."""

from navigation.route_names import VendorDashboardRoute


VENDOR_MENU = [
    {
        "section": "main",
        "section_label": "Main",
        "section_label_ar": "الرئيسية",
        "section_ar": "الرئيسية",
        "items": [
            {
                "key": "overview",
                "label": "Organization Overview",
                "label_ar": "الرئيسية",
                "route_name": VendorDashboardRoute.DASHBOARD,
                "icon": "layout-dashboard",
            },
        ],
    },
    {
        "section": "files",
        "section_label": "Files",
        "section_label_ar": "الملفات",
        "section_ar": "الملفات",
        "items": [
            {
                "key": "files",
                "label": "My Files",
                "label_ar": "ملفاتي",
                "route_name": VendorDashboardRoute.FILES,
                "icon": "files",
            },
            {
                "key": "folders",
                "label": "Folders",
                "label_ar": "المجلدات",
                "route_name": VendorDashboardRoute.FOLDERS,
                "icon": "folder-tree",
            },
            {
                "key": "upload",
                "label": "Upload Center",
                "label_ar": "رفع الملفات",
                "route_name": VendorDashboardRoute.UPLOAD,
                "icon": "upload-cloud",
            },
        ],
    },
    {
        "section": "audit",
        "section_label": "Audit",
        "section_label_ar": "التدقيق والتقارير",
        "section_ar": "التدقيق والتقارير",
        "items": [
            {
                "key": "audits",
                "label": "Audit Jobs",
                "label_ar": "مهام التدقيق",
                "route_name": VendorDashboardRoute.AUDITS,
                "icon": "shield-check",
            },
            {
                "key": "audit_results",
                "label": "Audit Results",
                "label_ar": "نتائج التدقيق",
                "route_name": VendorDashboardRoute.AUDIT_RESULTS,
                "icon": "shield-alert",
            },
            {
                "key": "reports",
                "label": "Reports",
                "label_ar": "التقارير",
                "route_name": VendorDashboardRoute.REPORTS,
                "icon": "bar-chart-3",
            },
        ],
    },
    {
        "section": "organization",
        "section_label": "Organization",
        "section_label_ar": "المنظمة",
        "section_ar": "المنظمة",
        "items": [
            {
                "key": "team",
                "label": "Team Members",
                "label_ar": "فريق العمل",
                "route_name": VendorDashboardRoute.TEAM,
                "icon": "users",
            },
            {
                "key": "org_settings",
                "label": "Organization Settings",
                "label_ar": "إعدادات المنظمة",
                "route_name": VendorDashboardRoute.SETTINGS,
                "icon": "settings",
            },
            {
                "key": "storage_usage",
                "label": "Storage Usage",
                "label_ar": "استخدام التخزين",
                "route_name": VendorDashboardRoute.STORAGE,
                "icon": "hard-drive",
            },
            {
                "key": "billing",
                "label": "Billing",
                "label_ar": "الباقة / الفوترة",
                "route_name": VendorDashboardRoute.BILLING,
                "icon": "credit-card",
            },
            {
                "key": "notifications",
                "label": "Notifications",
                "label_ar": "الإشعارات",
                "route_name": VendorDashboardRoute.NOTIFICATIONS,
                "icon": "bell",
            },
        ],
    },
]
