"""Platform admin console template views."""

from django.shortcuts import redirect, render
from django.utils.translation import gettext_lazy as _

from core.dashboard_context import build_platform_context
from core.feature_flags import jobs_enabled
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
    """Recruitment console — disabled while apps.jobs is quarantined.

    ``templates/platform_admin/jobs.html`` is deliberately left on disk (and
    still renders correctly once the module is registered), but it is NOT
    rendered here: apps.jobs is absent from INSTALLED_APPS, so every API call
    that page makes 404s. Serving it would give staff a screen that loads and
    then silently fails on every action. We render an explicit unavailable
    state instead. See docs/adr/0003-quarantine-apps-jobs.md.
    """
    if jobs_enabled():                                  # pragma: no cover
        # Reached only once apps.jobs is registered again.
        return render(
            request,
            "platform_admin/jobs.html",
            build_platform_context(request, active_key="jobs"),
        )
    context = build_platform_context(request, active_key="jobs")
    context.update(
        feature_title=_("Jobs & Careers"),
        feature_reason=_(
            "The recruitment module is not installed on this deployment, so job "
            "listings and applications cannot be loaded or edited."
        ),
    )
    return render(request, "platform_admin/feature_unavailable.html", context)


@platform_admin_required
def partner_applications(request):
    """Partner application review console (Phase 3A STEP 0).

    A UI over the endpoints Phase 2B already shipped and tested. Server-renders
    only the choice lists; every read and every transition goes through
    /api/platform-admin/partner-applications/*, which is staff-only and audits
    each transition.
    """
    from apps.authentication.models import Organization
    from apps.partners.models import ApplicationStatus, PartnerTier, PartnerType

    context = build_platform_context(request, active_key="partner_applications")
    context.update(
        country_choices=Organization.Country.choices,
        type_choices=PartnerType.choices,
        tier_choices=PartnerTier.choices,
        status_choices=ApplicationStatus.choices,
    )
    return render(request, "platform_admin/partner_applications.html", context)


@platform_admin_required
def partners_manager(request):
    """Partner administration console (Phase 2A).

    Server-renders only the choice lists; the table and every mutation go
    through /api/platform-admin/partners/*, which is staff-only and audits
    publish/hide.
    """
    from apps.partners.models import PartnerStatus, PartnerTier, PartnerType

    context = build_platform_context(request, active_key="partners")
    context.update(
        type_choices=PartnerType.choices,
        tier_choices=PartnerTier.choices,
        status_choices=PartnerStatus.choices,
    )
    return render(request, "platform_admin/partners.html", context)


@platform_admin_required
def trial_users(request):
    """Trial Users Dashboard shell (§B / §L.5).

    Server-renders only the choice lists and the purchasable-plan list; every
    metric is fetched from /api/platform-admin/trial-users/* so aggregation
    stays in SQL and this view does no counting.

    Choice labels are passed as JSON for the Alpine layer because the API
    returns raw enum values — sending labels per row would bloat every
    response and duplicate the translation.
    """
    import json

    from apps.authentication.models import Organization
    from apps.billing.services.plan_service import list_purchasable_plans
    from apps.leads.models import TrialLeadProfile

    country_choices = Organization.Country.choices
    client_type_choices = TrialLeadProfile.PrimaryBenefit.choices

    context = build_platform_context(request, active_key="trial_users")
    context.update(
        country_choices=country_choices,
        client_type_choices=client_type_choices,
        country_labels_json=json.dumps({k: str(v) for k, v in country_choices}),
        client_type_labels_json=json.dumps({k: str(v) for k, v in client_type_choices}),
        purchasable_plans=list(list_purchasable_plans()),
    )
    return render(request, "platform_admin/trial_users.html", context)


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
