"""
Django template views for storage management dashboard pages.
These views render HTML — they are NOT DRF endpoints.
All data is loaded client-side via the API using apiFetch().
"""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def providers(request):
    """Storage providers list page."""
    return render(request, "storage_management/providers.html")


@login_required
def provider_form(request, pk=None):
    """Create / edit a storage provider and its config."""
    return render(
        request,
        "storage_management/provider_form.html",
        {"provider_id": str(pk) if pk else ""},
    )


@login_required
def org_policies(request):
    """Per-organisation storage routing policy management page."""
    return render(request, "storage_management/org_policies.html")


@login_required
def file_policies(request):
    """Per-organisation file validation policy management page."""
    return render(request, "storage_management/file_policies.html")


@login_required
def file_monitor(request):
    """File monitor — browse, search and manage uploaded files."""
    return render(request, "storage_management/file_monitor.html")
