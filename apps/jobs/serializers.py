from rest_framework import serializers

from .models import JobApplication, JobPost


class JobPostListSerializer(serializers.ModelSerializer):
    application_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = JobPost
        fields = [
            'id',
            'title',
            'department',
            'location',
            'job_type',
            'experience_level',
            'status',
            'published_at',
            'application_count',
        ]


class JobPostDetailSerializer(serializers.ModelSerializer):
    application_count = serializers.IntegerField(read_only=True)
    created_by_email = serializers.EmailField(source='created_by.email', read_only=True, default=None)

    class Meta:
        model = JobPost
        fields = [
            'id',
            'title',
            'title_ar',
            'department',
            'location',
            'job_type',
            'experience_level',
            'description',
            'description_ar',
            'requirements',
            'requirements_ar',
            'benefits',
            'benefits_ar',
            'salary_min',
            'salary_max',
            'salary_currency',
            'show_salary',
            'status',
            'published_at',
            'closes_at',
            'created_by_email',
            'application_count',
            'created_at',
            'updated_at',
        ]


class JobApplicationSerializer(serializers.ModelSerializer):
    job_title = serializers.CharField(source='job.title', read_only=True)
    assigned_to_email = serializers.EmailField(source='assigned_to.email', read_only=True, default=None)

    class Meta:
        model = JobApplication
        fields = [
            'id',
            'job',
            'job_title',
            'full_name',
            'email',
            'phone',
            'linkedin_url',
            'portfolio_url',
            'resume_url',
            'cover_letter',
            'years_of_experience',
            'current_company',
            'notice_period_days',
            'expected_salary',
            'status',
            'internal_notes',
            'assigned_to',
            'assigned_to_email',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'job', 'job_title', 'assigned_to_email', 'created_at', 'updated_at']


class PublicJobListSerializer(serializers.ModelSerializer):
    """Public-facing list serializer. Hides salary data when show_salary=False."""

    salary_min = serializers.SerializerMethodField()
    salary_max = serializers.SerializerMethodField()
    salary_currency = serializers.SerializerMethodField()

    class Meta:
        model = JobPost
        fields = [
            'id',
            'title',
            'title_ar',
            'department',
            'location',
            'job_type',
            'experience_level',
            'published_at',
            'closes_at',
            'salary_min',
            'salary_max',
            'salary_currency',
        ]

    def get_salary_min(self, obj):
        return obj.salary_min if obj.show_salary else None

    def get_salary_max(self, obj):
        return obj.salary_max if obj.show_salary else None

    def get_salary_currency(self, obj):
        return obj.salary_currency if obj.show_salary else None


class PublicJobDetailSerializer(serializers.ModelSerializer):
    """Public-facing detail serializer. Hides salary data when show_salary=False."""

    salary_min = serializers.SerializerMethodField()
    salary_max = serializers.SerializerMethodField()
    salary_currency = serializers.SerializerMethodField()

    class Meta:
        model = JobPost
        fields = [
            'id',
            'title',
            'title_ar',
            'department',
            'location',
            'job_type',
            'experience_level',
            'description',
            'description_ar',
            'requirements',
            'requirements_ar',
            'benefits',
            'benefits_ar',
            'published_at',
            'closes_at',
            'salary_min',
            'salary_max',
            'salary_currency',
        ]

    def get_salary_min(self, obj):
        return obj.salary_min if obj.show_salary else None

    def get_salary_max(self, obj):
        return obj.salary_max if obj.show_salary else None

    def get_salary_currency(self, obj):
        return obj.salary_currency if obj.show_salary else None


class ApplicationSubmitSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=200)
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=30, required=False, allow_blank=True, default='')
    linkedin_url = serializers.URLField(required=False, allow_blank=True, default='')
    portfolio_url = serializers.URLField(required=False, allow_blank=True, default='')
    resume_url = serializers.URLField(max_length=1000, required=False, allow_blank=True, default='')
    cover_letter = serializers.CharField(required=False, allow_blank=True, default='')
    years_of_experience = serializers.IntegerField(min_value=0, max_value=60, required=False, allow_null=True, default=None)
    current_company = serializers.CharField(max_length=200, required=False, allow_blank=True, default='')
    notice_period_days = serializers.IntegerField(min_value=0, required=False, allow_null=True, default=None)
    expected_salary = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True, default=None)


class ApplicationStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=JobApplication.Status.choices)
    internal_notes = serializers.CharField(required=False, allow_blank=True, default='')


class ApplicationAssignSerializer(serializers.Serializer):
    assignee_id = serializers.UUIDField()
