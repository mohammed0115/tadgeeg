from __future__ import annotations

from django.utils import timezone

from apps.activity_logs.service import ActivityLogService

from .exceptions import (
    ApplicationAlreadyExistsError,
    JobClosedError,
    JobNotFoundError,
)
from .models import JobApplication, JobPost
from .selectors import get_application_by_id, get_job_by_id


def create_job(data: dict, user) -> JobPost:
    """Create a new JobPost. Logs the creation action."""
    job = JobPost.objects.create(
        title=data.get('title', ''),
        title_ar=data.get('title_ar', ''),
        department=data.get('department', ''),
        location=data.get('location', 'Riyadh, Saudi Arabia'),
        job_type=data.get('job_type', JobPost.JobType.FULL_TIME),
        experience_level=data.get('experience_level', JobPost.ExperienceLevel.MID),
        description=data.get('description', ''),
        description_ar=data.get('description_ar', ''),
        requirements=data.get('requirements', []),
        requirements_ar=data.get('requirements_ar', []),
        benefits=data.get('benefits', []),
        benefits_ar=data.get('benefits_ar', []),
        salary_min=data.get('salary_min'),
        salary_max=data.get('salary_max'),
        salary_currency=data.get('salary_currency', 'SAR'),
        show_salary=data.get('show_salary', False),
        status=data.get('status', JobPost.Status.DRAFT),
        closes_at=data.get('closes_at'),
        created_by=user,
    )
    ActivityLogService.log(
        action='job_created',
        user=user,
        organization=getattr(user, 'organization', None),
        entity_type='JobPost',
        entity_id=str(job.pk),
        description=f"Job post '{job.title}' created.",
    )
    return job


def update_job(job_id, data: dict, user) -> JobPost:
    """Update an existing JobPost. Raises JobNotFoundError if not found."""
    job = get_job_by_id(job_id)
    if job is None:
        raise JobNotFoundError(f"Job {job_id} not found.")

    updatable_fields = [
        'title', 'title_ar', 'department', 'location', 'job_type', 'experience_level',
        'description', 'description_ar', 'requirements', 'requirements_ar',
        'benefits', 'benefits_ar', 'salary_min', 'salary_max', 'salary_currency',
        'show_salary', 'status', 'closes_at',
    ]
    changed = []
    for field in updatable_fields:
        if field in data:
            setattr(job, field, data[field])
            changed.append(field)
    job.save(update_fields=changed + ['updated_at'])

    ActivityLogService.log(
        action='job_updated',
        user=user,
        organization=getattr(user, 'organization', None),
        entity_type='JobPost',
        entity_id=str(job.pk),
        description=f"Job post '{job.title}' updated. Fields changed: {', '.join(changed)}.",
    )
    return job


def publish_job(job_id, user) -> JobPost:
    """Transition a JobPost to PUBLISHED status. Sets published_at timestamp."""
    job = get_job_by_id(job_id)
    if job is None:
        raise JobNotFoundError(f"Job {job_id} not found.")

    job.status = JobPost.Status.PUBLISHED
    job.published_at = timezone.now()
    job.save(update_fields=['status', 'published_at', 'updated_at'])

    ActivityLogService.log(
        action='job_published',
        user=user,
        organization=getattr(user, 'organization', None),
        entity_type='JobPost',
        entity_id=str(job.pk),
        description=f"Job post '{job.title}' published.",
    )
    return job


def close_job(job_id, user) -> JobPost:
    """Transition a JobPost to CLOSED status."""
    job = get_job_by_id(job_id)
    if job is None:
        raise JobNotFoundError(f"Job {job_id} not found.")

    job.status = JobPost.Status.CLOSED
    job.save(update_fields=['status', 'updated_at'])

    ActivityLogService.log(
        action='job_closed',
        user=user,
        organization=getattr(user, 'organization', None),
        entity_type='JobPost',
        entity_id=str(job.pk),
        description=f"Job post '{job.title}' closed.",
    )
    return job


def delete_job(job_id, user) -> None:
    """Delete a JobPost and all its applications."""
    job = get_job_by_id(job_id)
    if job is None:
        raise JobNotFoundError(f"Job {job_id} not found.")

    title = job.title
    ActivityLogService.log(
        action='job_deleted',
        user=user,
        organization=getattr(user, 'organization', None),
        entity_type='JobPost',
        entity_id=str(job.pk),
        description=f"Job post '{title}' deleted.",
    )
    job.delete()


def submit_application(job_id, data: dict) -> JobApplication:
    """Public submission: create a JobApplication. No user context required."""
    job = get_job_by_id(job_id)
    if job is None:
        raise JobNotFoundError(f"Job {job_id} not found.")

    if job.status != JobPost.Status.PUBLISHED:
        raise JobClosedError(f"Job '{job.title}' is not accepting applications.")

    email = data.get('email', '').strip().lower()
    if JobApplication.objects.filter(job=job, email=email).exists():
        raise ApplicationAlreadyExistsError(
            f"An application from {email} for this job already exists."
        )

    application = JobApplication.objects.create(
        job=job,
        full_name=data.get('full_name', ''),
        email=email,
        phone=data.get('phone', ''),
        linkedin_url=data.get('linkedin_url', ''),
        portfolio_url=data.get('portfolio_url', ''),
        resume_url=data.get('resume_url', ''),
        cover_letter=data.get('cover_letter', ''),
        years_of_experience=data.get('years_of_experience'),
        current_company=data.get('current_company', ''),
        notice_period_days=data.get('notice_period_days'),
        expected_salary=data.get('expected_salary'),
        status=JobApplication.Status.PENDING,
    )
    return application


def update_application_status(app_id, status: str, notes: str, user) -> JobApplication:
    """Update the status and/or internal notes of an application."""
    application = get_application_by_id(app_id)
    if application is None:
        from .exceptions import JobsError
        raise JobsError(f"Application {app_id} not found.")

    application.status = status
    if notes:
        application.internal_notes = notes
    application.save(update_fields=['status', 'internal_notes', 'updated_at'])

    ActivityLogService.log(
        action='application_status_updated',
        user=user,
        organization=getattr(user, 'organization', None),
        entity_type='JobApplication',
        entity_id=str(application.pk),
        description=f"Application from '{application.full_name}' for '{application.job.title}' moved to '{status}'.",
    )
    return application


def assign_application(app_id, assignee_id, user) -> JobApplication:
    """Assign a JobApplication to an internal user."""
    from django.contrib.auth import get_user_model

    application = get_application_by_id(app_id)
    if application is None:
        from .exceptions import JobsError
        raise JobsError(f"Application {app_id} not found.")

    UserModel = get_user_model()
    try:
        assignee = UserModel.objects.get(pk=assignee_id)
    except UserModel.DoesNotExist:
        from .exceptions import JobsError
        raise JobsError(f"User {assignee_id} not found.")

    application.assigned_to = assignee
    application.save(update_fields=['assigned_to', 'updated_at'])

    ActivityLogService.log(
        action='application_assigned',
        user=user,
        organization=getattr(user, 'organization', None),
        entity_type='JobApplication',
        entity_id=str(application.pk),
        description=f"Application from '{application.full_name}' assigned to '{assignee.full_name}'.",
    )
    return application


def delete_application(app_id, user) -> None:
    """Delete a JobApplication."""
    application = get_application_by_id(app_id)
    if application is None:
        from .exceptions import JobsError
        raise JobsError(f"Application {app_id} not found.")

    applicant_name = application.full_name
    job_title = application.job.title
    ActivityLogService.log(
        action='application_deleted',
        user=user,
        organization=getattr(user, 'organization', None),
        entity_type='JobApplication',
        entity_id=str(application.pk),
        description=f"Application from '{applicant_name}' for '{job_title}' deleted.",
    )
    application.delete()
