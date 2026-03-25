"""Frontend (template) views for Phase 2 reporting dashboard."""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def dashboard(request):
    return render(request, "phase2/dashboard.html")


@login_required
def reports(request):
    return render(request, "phase2/reports.html")
