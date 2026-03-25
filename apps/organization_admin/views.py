"""Organization dashboard views.

Transitional wrapper layer that exposes the tenant dashboard from a package
name aligned with the target architecture.
"""

from apps.vendor_dashboard import views as legacy_views


def dashboard(request, *args, **kwargs):
    return legacy_views.dashboard(request, *args, **kwargs)


def files(request, *args, **kwargs):
    return legacy_views.files(request, *args, **kwargs)


def folders(request, *args, **kwargs):
    return legacy_views.folders(request, *args, **kwargs)


def upload(request, *args, **kwargs):
    return legacy_views.upload(request, *args, **kwargs)


def audits(request, *args, **kwargs):
    return legacy_views.audits(request, *args, **kwargs)


def audit_results(request, *args, **kwargs):
    return legacy_views.audit_results(request, *args, **kwargs)


def reports(request, *args, **kwargs):
    return legacy_views.reports(request, *args, **kwargs)


def team(request, *args, **kwargs):
    return legacy_views.team(request, *args, **kwargs)


def org_settings(request, *args, **kwargs):
    return legacy_views.org_settings(request, *args, **kwargs)


def storage_usage(request, *args, **kwargs):
    return legacy_views.storage_usage(request, *args, **kwargs)


def billing(request, *args, **kwargs):
    return legacy_views.billing(request, *args, **kwargs)


def notifications(request, *args, **kwargs):
    return legacy_views.notifications(request, *args, **kwargs)
