"""Frontend (template) views for activity logs."""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def activity(request):
    return render(request, "phase2/activity.html")
