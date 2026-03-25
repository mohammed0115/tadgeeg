"""Vendor dashboard template views."""

from django.shortcuts import render

from core.dashboard_context import build_vendor_context
from core.permissions import org_member_required


@org_member_required
def dashboard(request):
    return render(
        request,
        "vendor_dashboard/dashboard.html",
        build_vendor_context(request, active_key="overview"),
    )


@org_member_required
def files(request):
    return render(
        request,
        "vendor_dashboard/files.html",
        build_vendor_context(request, active_key="files"),
    )


@org_member_required
def folders(request):
    return render(
        request,
        "vendor_dashboard/folders.html",
        build_vendor_context(request, active_key="folders"),
    )


@org_member_required
def upload(request):
    return render(
        request,
        "vendor_dashboard/upload.html",
        build_vendor_context(request, active_key="upload"),
    )


@org_member_required
def audits(request):
    return render(
        request,
        "vendor_dashboard/audits.html",
        build_vendor_context(request, active_key="audits"),
    )


@org_member_required
def audit_results(request):
    return render(
        request,
        "vendor_dashboard/audit_results.html",
        build_vendor_context(request, active_key="audit_results"),
    )


@org_member_required
def reports(request):
    return render(
        request,
        "vendor_dashboard/reports.html",
        build_vendor_context(request, active_key="reports"),
    )


@org_member_required
def team(request):
    return render(
        request,
        "vendor_dashboard/team.html",
        build_vendor_context(request, active_key="team"),
    )


@org_member_required
def org_settings(request):
    return render(
        request,
        "vendor_dashboard/settings.html",
        build_vendor_context(request, active_key="org_settings"),
    )


@org_member_required
def storage_usage(request):
    return render(
        request,
        "vendor_dashboard/storage.html",
        build_vendor_context(request, active_key="storage_usage"),
    )


@org_member_required
def billing(request):
    return render(
        request,
        "vendor_dashboard/billing.html",
        build_vendor_context(request, active_key="billing"),
    )


@org_member_required
def notifications(request):
    return render(
        request,
        "vendor_dashboard/notifications.html",
        build_vendor_context(request, active_key="notifications"),
    )
