from django.contrib import admin

from .models import JobApplication, JobPost


@admin.register(JobPost)
class JobPostAdmin(admin.ModelAdmin):
    list_display = ['title', 'department', 'status', 'application_count', 'created_at']
    list_filter = ['status', 'job_type', 'experience_level', 'department']
    search_fields = ['title', 'title_ar', 'department', 'location']
    readonly_fields = ['id', 'created_at', 'updated_at', 'published_at', 'application_count']
    ordering = ['-created_at']

    fieldsets = (
        ('Basic Info', {
            'fields': ('id', 'title', 'title_ar', 'department', 'location', 'job_type', 'experience_level'),
        }),
        ('Content', {
            'fields': ('description', 'description_ar', 'requirements', 'requirements_ar', 'benefits', 'benefits_ar'),
        }),
        ('Salary', {
            'fields': ('salary_min', 'salary_max', 'salary_currency', 'show_salary'),
        }),
        ('Status & Dates', {
            'fields': ('status', 'published_at', 'closes_at', 'created_at', 'updated_at'),
        }),
        ('Meta', {
            'fields': ('created_by', 'application_count'),
        }),
    )


@admin.register(JobApplication)
class JobApplicationAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'email', 'job', 'status', 'assigned_to', 'created_at']
    list_filter = ['status', 'job']
    search_fields = ['full_name', 'email', 'current_company']
    readonly_fields = ['id', 'created_at', 'updated_at']
    ordering = ['-created_at']

    fieldsets = (
        ('Applicant', {
            'fields': ('id', 'full_name', 'email', 'phone', 'linkedin_url', 'portfolio_url', 'resume_url'),
        }),
        ('Application', {
            'fields': ('job', 'cover_letter', 'years_of_experience', 'current_company', 'notice_period_days', 'expected_salary'),
        }),
        ('Review', {
            'fields': ('status', 'internal_notes', 'assigned_to'),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
        }),
    )
