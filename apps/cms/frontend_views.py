"""Frontend (template) views for CMS admin dashboard."""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def cms_dashboard(request):
    return render(request, "cms_admin/dashboard.html")


@login_required
def cms_homepage(request):
    return render(request, "cms_admin/homepage.html")


@login_required
def cms_about(request):
    return render(request, "cms_admin/about.html")


@login_required
def cms_pages(request):
    return render(request, "cms_admin/pages.html")


@login_required
def cms_services(request):
    return render(request, "cms_admin/services_editor.html")


@login_required
def cms_pricing(request):
    return render(request, "cms_admin/pricing.html")


@login_required
def cms_faq(request):
    return render(request, "cms_admin/faq.html")


@login_required
def cms_jobs(request):
    return render(request, "cms_admin/jobs.html")


@login_required
def cms_leads(request):
    return render(request, "cms_admin/leads.html")


@login_required
def cms_media(request):
    return render(request, "cms_admin/media.html")


@login_required
def cms_seo(request):
    return render(request, "cms_admin/seo.html")


@login_required
def cms_settings(request):
    return render(request, "cms_admin/settings.html")
