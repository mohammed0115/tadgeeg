"""Platform management views.

Transitional wrapper layer that exposes the internal platform console from a
package name aligned with the target architecture without moving domain logic.
"""

from apps.platform_admin import views as legacy_views


def dashboard(request, *args, **kwargs):
    return legacy_views.dashboard(request, *args, **kwargs)


def organizations(request, *args, **kwargs):
    return legacy_views.organizations(request, *args, **kwargs)


def cms_pages(request, *args, **kwargs):
    return legacy_views.cms_pages(request, *args, **kwargs)


def homepage_editor(request, *args, **kwargs):
    return legacy_views.homepage_editor(request, *args, **kwargs)


def about_editor(request, *args, **kwargs):
    return legacy_views.about_editor(request, *args, **kwargs)


def services_editor(request, *args, **kwargs):
    return legacy_views.services_editor(request, *args, **kwargs)


def pricing_editor(request, *args, **kwargs):
    return legacy_views.pricing_editor(request, *args, **kwargs)


def faq_editor(request, *args, **kwargs):
    return legacy_views.faq_editor(request, *args, **kwargs)


def intro_video_editor(request, *args, **kwargs):
    return legacy_views.intro_video_editor(request, *args, **kwargs)


def jobs_manager(request, *args, **kwargs):
    return legacy_views.jobs_manager(request, *args, **kwargs)


def leads_manager(request, *args, **kwargs):
    return legacy_views.leads_manager(request, *args, **kwargs)


def seo_settings(request, *args, **kwargs):
    return legacy_views.seo_settings(request, *args, **kwargs)


def media_library(request, *args, **kwargs):
    return legacy_views.media_library(request, *args, **kwargs)


def storage_providers(request, *args, **kwargs):
    return legacy_views.storage_providers(request, *args, **kwargs)


def platform_settings(request, *args, **kwargs):
    return legacy_views.platform_settings(request, *args, **kwargs)


def monitoring(request, *args, **kwargs):
    return legacy_views.monitoring(request, *args, **kwargs)


def activity_logs(request, *args, **kwargs):
    return legacy_views.activity_logs(request, *args, **kwargs)
