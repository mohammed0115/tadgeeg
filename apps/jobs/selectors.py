from __future__ import annotations

from django.db.models import QuerySet

from .models import JobApplication, JobPost


def get_published_jobs(department: str | None = None, job_type: str | None = None) -> QuerySet:
    """Return published jobs, optionally filtered by department and/or job_type."""
    qs = JobPost.objects.filter(status=JobPost.Status.PUBLISHED)
    if department:
        qs = qs.filter(department__iexact=department)
    if job_type:
        qs = qs.filter(job_type=job_type)
    return qs


def get_all_jobs(status: str | None = None) -> QuerySet:
    """Return all jobs for admin view, optionally filtered by status."""
    qs = JobPost.objects.all()
    if status:
        qs = qs.filter(status=status)
    return qs


def get_job_by_id(job_id) -> JobPost | None:
    """Return a single JobPost by PK, or None if not found."""
    try:
        return JobPost.objects.get(pk=job_id)
    except JobPost.DoesNotExist:
        return None


def get_applications_for_job(job_id, status: str | None = None) -> QuerySet:
    """Return all applications for a given job, optionally filtered by status."""
    qs = JobApplication.objects.filter(job_id=job_id).select_related('job', 'assigned_to')
    if status:
        qs = qs.filter(status=status)
    return qs


def get_all_applications(status: str | None = None) -> QuerySet:
    """Return all applications across all jobs, optionally filtered by status."""
    qs = JobApplication.objects.all().select_related('job', 'assigned_to')
    if status:
        qs = qs.filter(status=status)
    return qs


def get_application_by_id(app_id) -> JobApplication | None:
    """Return a single JobApplication by PK, or None if not found."""
    try:
        return JobApplication.objects.select_related('job', 'assigned_to').get(pk=app_id)
    except JobApplication.DoesNotExist:
        return None


def get_application_stats() -> dict:
    """Return aggregate counts for all application statuses."""
    from django.db.models import Count

    status_counts = dict(
        JobApplication.objects.values_list('status').annotate(count=Count('id')).values_list('status', 'count')
    )
    return {
        'total': JobApplication.objects.count(),
        'pending': status_counts.get(JobApplication.Status.PENDING, 0),
        'reviewing': status_counts.get(JobApplication.Status.REVIEWING, 0),
        'shortlisted': status_counts.get(JobApplication.Status.SHORTLISTED, 0),
        'interview': status_counts.get(JobApplication.Status.INTERVIEW, 0),
        'hired': status_counts.get(JobApplication.Status.HIRED, 0),
        'rejected': status_counts.get(JobApplication.Status.REJECTED, 0),
    }
