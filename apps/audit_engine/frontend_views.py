"""Frontend (template) views for audit engine."""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def audit_jobs(request):
    return render(request, "phase2/audits.html")


@login_required
def audit_result(request, job_id):
    return render(request, "phase2/audit_result.html", {"job_id": str(job_id)})
