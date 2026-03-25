"""Sidebar navigation for the Get Solution platform admin console."""

from navigation.route_names import PlatformAdminRoute


PLATFORM_MENU = [
    {
        "section": "main",
        "section_label": "Main",
        "section_label_ar": "الرئيسية",
        "section_ar": "الرئيسية",
        "items": [
            {
                "key": "dashboard",
                "label": "Platform Overview",
                "label_ar": "الرئيسية",
                "route_name": PlatformAdminRoute.DASHBOARD,
                "icon": "layout-dashboard",
            },
            {
                "key": "organizations",
                "label": "Organizations",
                "label_ar": "المنظمات",
                "route_name": PlatformAdminRoute.ORGANIZATIONS,
                "icon": "building-2",
            },
        ],
    },
    {
        "section": "content",
        "section_label": "Content",
        "section_label_ar": "إدارة المحتوى",
        "section_ar": "إدارة المحتوى",
        "items": [
            {
                "key": "cms_pages",
                "label": "CMS Pages",
                "label_ar": "إدارة المحتوى",
                "route_name": PlatformAdminRoute.CMS,
                "icon": "file-text",
            },
            {
                "key": "homepage",
                "label": "Homepage",
                "label_ar": "الصفحة الرئيسية",
                "route_name": PlatformAdminRoute.HOMEPAGE,
                "icon": "home",
            },
            {
                "key": "about",
                "label": "About Us",
                "label_ar": "من نحن",
                "route_name": PlatformAdminRoute.ABOUT,
                "icon": "info",
            },
            {
                "key": "services",
                "label": "Services",
                "label_ar": "الخدمات",
                "route_name": PlatformAdminRoute.SERVICES,
                "icon": "layers-3",
            },
            {
                "key": "pricing",
                "label": "Pricing Plans",
                "label_ar": "الأسعار",
                "route_name": PlatformAdminRoute.PRICING,
                "icon": "badge-dollar-sign",
            },
            {
                "key": "faq",
                "label": "FAQ",
                "label_ar": "الأسئلة الشائعة",
                "route_name": PlatformAdminRoute.FAQ,
                "icon": "help-circle",
            },
            {
                "key": "intro_video",
                "label": "Intro Video",
                "label_ar": "الفيديو التعريفي",
                "route_name": PlatformAdminRoute.INTRO_VIDEO,
                "icon": "play-circle",
            },
        ],
    },
    {
        "section": "growth",
        "section_label": "Growth",
        "section_label_ar": "النمو والتشغيل",
        "section_ar": "النمو والتشغيل",
        "items": [
            {
                "key": "jobs",
                "label": "Jobs",
                "label_ar": "الوظائف",
                "route_name": PlatformAdminRoute.JOBS,
                "icon": "briefcase",
            },
            {
                "key": "leads",
                "label": "Contact Leads",
                "label_ar": "طلبات التواصل",
                "route_name": PlatformAdminRoute.LEADS,
                "icon": "inbox",
            },
            {
                "key": "seo",
                "label": "SEO",
                "label_ar": "SEO",
                "route_name": PlatformAdminRoute.SEO,
                "icon": "search",
            },
            {
                "key": "media",
                "label": "Media Library",
                "label_ar": "مكتبة الوسائط",
                "route_name": PlatformAdminRoute.MEDIA,
                "icon": "images",
            },
        ],
    },
    {
        "section": "system",
        "section_label": "System",
        "section_label_ar": "النظام",
        "section_ar": "النظام",
        "items": [
            {
                "key": "storage",
                "label": "Storage Providers",
                "label_ar": "مزودي التخزين",
                "route_name": PlatformAdminRoute.STORAGE,
                "icon": "hard-drive",
            },
            {
                "key": "settings",
                "label": "Platform Settings",
                "label_ar": "إعدادات المنصة",
                "route_name": PlatformAdminRoute.SETTINGS,
                "icon": "settings-2",
            },
            {
                "key": "monitoring",
                "label": "System Monitoring",
                "label_ar": "مراقبة النظام",
                "route_name": PlatformAdminRoute.MONITORING,
                "icon": "activity",
            },
            {
                "key": "activity_logs",
                "label": "Activity Logs",
                "label_ar": "سجل النشاط",
                "route_name": PlatformAdminRoute.ACTIVITY_LOGS,
                "icon": "scroll-text",
            },
        ],
    },
]
