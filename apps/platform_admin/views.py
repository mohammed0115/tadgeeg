"""Platform admin console template views."""

from django.shortcuts import redirect, render

from core.dashboard_context import build_platform_context
from core.permissions import platform_admin_required


@platform_admin_required
def dashboard(request):
    # Server-render the shared customer metrics from the SAME source the CRM
    # dashboard uses (apps.platform_admin.selectors.get_dashboard_summary →
    # canonical Organization / subscription / payment models), so the overview
    # can never show "Organizations = 0" while CRM shows the real count. The
    # Alpine layer may still enhance other (content) stats client-side.
    from apps.platform_admin import selectors
    ctx = build_platform_context(request, active_key="dashboard")
    ctx["summary"] = selectors.get_dashboard_summary()
    return render(request, "platform_admin/dashboard.html", ctx)


@platform_admin_required
def organizations(request):
    """Customer records live in ONE canonical place: the server-rendered CRM
    customer directory (apps.authentication.Organization). The old page filled
    its table client-side via /api/v1/auth/organizations/, so it could show an
    empty "0 organizations" table whenever JS or the API failed — even though
    data existed. We now redirect to the CRM directory so the org/customer list
    is always server-rendered from real data and there is a single source of
    truth. Permissions: this view requires a platform user; the CRM directory
    then enforces CRM-read (so non-CRM staff still get 403 there)."""
    return redirect("platform_admin:crm:customers")


@platform_admin_required
def cms_pages(request):
    return render(
        request,
        "platform_admin/cms/pages.html",
        build_platform_context(request, active_key="cms_pages"),
    )


@platform_admin_required
def homepage_editor(request):
    return render(
        request,
        "platform_admin/cms/homepage.html",
        build_platform_context(request, active_key="homepage"),
    )


@platform_admin_required
def about_editor(request):
    return render(
        request,
        "platform_admin/cms/about.html",
        build_platform_context(request, active_key="about"),
    )


@platform_admin_required
def services_editor(request):
    return render(
        request,
        "platform_admin/cms/services.html",
        build_platform_context(request, active_key="services"),
    )


@platform_admin_required
def pricing_editor(request):
    return render(
        request,
        "platform_admin/cms/pricing.html",
        build_platform_context(request, active_key="pricing"),
    )


@platform_admin_required
def faq_editor(request):
    return render(
        request,
        "platform_admin/cms/faq.html",
        build_platform_context(request, active_key="faq"),
    )


@platform_admin_required
def intro_video_editor(request):
    return render(
        request,
        "platform_admin/cms/intro_video.html",
        build_platform_context(request, active_key="intro_video"),
    )


@platform_admin_required
def jobs_manager(request):
    return render(
        request,
        "platform_admin/jobs.html",
        build_platform_context(request, active_key="jobs"),
    )


@platform_admin_required
def leads_manager(request):
    return render(
        request,
        "platform_admin/leads.html",
        build_platform_context(request, active_key="leads"),
    )


@platform_admin_required
def seo_settings(request):
    return render(
        request,
        "platform_admin/seo.html",
        build_platform_context(request, active_key="seo"),
    )


@platform_admin_required
def media_library(request):
    return render(
        request,
        "platform_admin/media.html",
        build_platform_context(request, active_key="media"),
    )


@platform_admin_required
def storage_providers(request):
    return render(
        request,
        "platform_admin/storage.html",
        build_platform_context(request, active_key="storage"),
    )


@platform_admin_required
def platform_settings(request):
    return render(
        request,
        "platform_admin/settings.html",
        build_platform_context(request, active_key="settings"),
    )


@platform_admin_required
def monitoring(request):
    return render(
        request,
        "platform_admin/monitoring.html",
        build_platform_context(request, active_key="monitoring"),
    )


@platform_admin_required
def activity_logs(request):
    return render(
        request,
        "platform_admin/activity_logs.html",
        build_platform_context(request, active_key="activity_logs"),
    )
