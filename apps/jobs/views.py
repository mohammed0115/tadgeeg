from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from .exceptions import (
    ApplicationAlreadyExistsError,
    JobClosedError,
    JobNotFoundError,
    JobsError,
)
from .selectors import (
    get_all_applications,
    get_all_jobs,
    get_application_by_id,
    get_application_stats,
    get_applications_for_job,
    get_job_by_id,
    get_published_jobs,
)
from .serializers import (
    ApplicationAssignSerializer,
    ApplicationStatusUpdateSerializer,
    ApplicationSubmitSerializer,
    JobApplicationSerializer,
    JobPostDetailSerializer,
    JobPostListSerializer,
    PublicJobDetailSerializer,
    PublicJobListSerializer,
)
from .services import (
    assign_application,
    close_job,
    create_job,
    delete_application,
    delete_job,
    publish_job,
    submit_application,
    update_application_status,
    update_job,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_admin(user) -> bool:
    """Return True if the user has staff flag or admin role."""
    return user.is_staff or getattr(user, 'role', None) == 'admin'


class _AdminPermission(IsAuthenticated):
    """Combined permission: authenticated + staff/admin role."""

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        return _is_admin(request.user)


# ---------------------------------------------------------------------------
# Admin — Job Posts
# ---------------------------------------------------------------------------

class AdminJobListView(APIView):
    """GET list of all jobs / POST create a new job."""

    permission_classes = [_AdminPermission]

    def get(self, request):
        status_filter = request.query_params.get('status')
        jobs = get_all_jobs(status=status_filter)
        serializer = JobPostListSerializer(jobs, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = JobPostDetailSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        job = create_job(serializer.validated_data, user=request.user)
        return Response(JobPostDetailSerializer(job).data, status=status.HTTP_201_CREATED)


class AdminJobDetailView(APIView):
    """GET / PUT / DELETE a single job post."""

    permission_classes = [_AdminPermission]

    def get(self, request, pk):
        job = get_job_by_id(pk)
        if job is None:
            return Response({'detail': 'Job not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(JobPostDetailSerializer(job).data)

    def put(self, request, pk):
        job = get_job_by_id(pk)
        if job is None:
            return Response({'detail': 'Job not found.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = JobPostDetailSerializer(job, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        try:
            updated = update_job(pk, serializer.validated_data, user=request.user)
        except JobNotFoundError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_404_NOT_FOUND)
        return Response(JobPostDetailSerializer(updated).data)

    def delete(self, request, pk):
        try:
            delete_job(pk, user=request.user)
        except JobNotFoundError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AdminJobPublishView(APIView):
    """POST /<uuid>/publish/ — transition job to PUBLISHED."""

    permission_classes = [_AdminPermission]

    def post(self, request, pk):
        try:
            job = publish_job(pk, user=request.user)
        except JobNotFoundError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_404_NOT_FOUND)
        return Response(JobPostDetailSerializer(job).data)


class AdminJobCloseView(APIView):
    """POST /<uuid>/close/ — transition job to CLOSED."""

    permission_classes = [_AdminPermission]

    def post(self, request, pk):
        try:
            job = close_job(pk, user=request.user)
        except JobNotFoundError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_404_NOT_FOUND)
        return Response(JobPostDetailSerializer(job).data)


# ---------------------------------------------------------------------------
# Admin — Applications
# ---------------------------------------------------------------------------

class AdminApplicationListView(APIView):
    """GET all applications with optional filters."""

    permission_classes = [_AdminPermission]

    def get(self, request):
        job_id = request.query_params.get('job')
        status_filter = request.query_params.get('status')

        if job_id:
            applications = get_applications_for_job(job_id, status=status_filter)
        else:
            applications = get_all_applications(status=status_filter)

        serializer = JobApplicationSerializer(applications, many=True)
        return Response(serializer.data)


class AdminApplicationDetailView(APIView):
    """GET / PUT a single application (update status / notes / assigned_to)."""

    permission_classes = [_AdminPermission]

    def get(self, request, pk):
        application = get_application_by_id(pk)
        if application is None:
            return Response({'detail': 'Application not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(JobApplicationSerializer(application).data)

    def put(self, request, pk):
        application = get_application_by_id(pk)
        if application is None:
            return Response({'detail': 'Application not found.'}, status=status.HTTP_404_NOT_FOUND)

        # Handle status update
        if 'status' in request.data:
            status_serializer = ApplicationStatusUpdateSerializer(data=request.data)
            if not status_serializer.is_valid():
                return Response(status_serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            try:
                application = update_application_status(
                    pk,
                    status=status_serializer.validated_data['status'],
                    notes=status_serializer.validated_data.get('internal_notes', ''),
                    user=request.user,
                )
            except JobsError as exc:
                return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        # Handle assignment
        if 'assigned_to' in request.data:
            assign_serializer = ApplicationAssignSerializer(data={'assignee_id': request.data['assigned_to']})
            if not assign_serializer.is_valid():
                return Response(assign_serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            try:
                application = assign_application(
                    pk,
                    assignee_id=assign_serializer.validated_data['assignee_id'],
                    user=request.user,
                )
            except JobsError as exc:
                return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(JobApplicationSerializer(application).data)


class AdminApplicationDeleteView(APIView):
    """DELETE a single application."""

    permission_classes = [_AdminPermission]

    def delete(self, request, pk):
        try:
            delete_application(pk, user=request.user)
        except JobsError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


class JobStatsView(APIView):
    """GET aggregate stats for job applications."""

    permission_classes = [_AdminPermission]

    def get(self, request):
        stats = get_application_stats()
        return Response(stats)


# ---------------------------------------------------------------------------
# Public — Jobs
# ---------------------------------------------------------------------------

class PublicJobListView(APIView):
    """GET published job listings (public, no auth required)."""

    permission_classes = [AllowAny]

    def get(self, request):
        department = request.query_params.get('department')
        job_type = request.query_params.get('job_type')
        jobs = get_published_jobs(department=department, job_type=job_type)
        serializer = PublicJobListSerializer(jobs, many=True)
        return Response(serializer.data)


class PublicJobDetailView(APIView):
    """GET a single published job (public, no auth required)."""

    permission_classes = [AllowAny]

    def get(self, request, pk):
        job = get_job_by_id(pk)
        if job is None or job.status != 'published':
            return Response({'detail': 'Job not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(PublicJobDetailSerializer(job).data)


class PublicJobApplyView(APIView):
    """POST /<uuid>/apply/ — submit a job application (public, no auth required)."""

    permission_classes = [AllowAny]

    def post(self, request, pk):
        serializer = ApplicationSubmitSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        try:
            application = submit_application(pk, data=serializer.validated_data)
        except JobNotFoundError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except JobClosedError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except ApplicationAlreadyExistsError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(
            {
                'detail': 'Application submitted successfully.',
                'application_id': str(application.pk),
            },
            status=status.HTTP_201_CREATED,
        )
