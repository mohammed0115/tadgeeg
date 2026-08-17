import logging

from django.shortcuts import get_object_or_404
from rest_framework import mixins, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet, ModelViewSet

from apps.audit_engine.models import AuditJob, AuditResult
from apps.audit_engine.permissions import CanRunAudit, CanViewAudit
from apps.audit_engine.serializers import (
    AuditJobListSerializer,
    AuditJobSerializer,
    AuditResultSerializer,
    RunAuditSerializer,
)
from apps.storage_management.models import AuditFile

logger = logging.getLogger(__name__)


class AuditJobViewSet(ModelViewSet):
    """
    ViewSet for managing AuditJobs.

    Endpoints:
      GET  /jobs/               — list jobs (AuditJobListSerializer)
      GET  /jobs/{id}/          — retrieve detail (AuditJobSerializer + nested result)
      POST /jobs/run/           — create & dispatch a new audit job
      GET  /jobs/{id}/result/   — shortcut to get AuditResult for a job
      POST /jobs/{id}/cancel/   — cancel a PENDING or QUEUED job
    """

    permission_classes = [CanRunAudit]

    def get_queryset(self):
        user = self.request.user
        if user.is_staff:
            return AuditJob.objects.all().select_related("audit_file", "created_by")
        return (
            AuditJob.objects.filter(organization=user.organization)
            .select_related("audit_file", "created_by")
        )

    def get_serializer_class(self):
        if self.action == "list":
            return AuditJobListSerializer
        return AuditJobSerializer

    def create(self, request, *args, **kwargs):
        return Response(
            {"detail": "Use POST /audit/jobs/run/ to create an audit job."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def update(self, request, *args, **kwargs):
        return Response(
            {"detail": "Audit jobs cannot be modified."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def partial_update(self, request, *args, **kwargs):
        return Response(
            {"detail": "Audit jobs cannot be modified."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    @action(detail=False, methods=["post"], url_path="run", permission_classes=[CanRunAudit])
    def run(self, request):
        """
        Create an AuditJob and dispatch it to Celery (or run synchronously
        as a fallback when Celery is unavailable).

        Request body:
          {
            "file_id": "<uuid>",
            "audit_type": "generic_audit"  // optional
          }
        """
        serializer = RunAuditSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        file_id = serializer.validated_data["file_id"]
        audit_type = serializer.validated_data["audit_type"]

        # Scope the file to the caller's organisation. Unscoped, a user could pass
        # another company's file_id and have an AuditJob created against it — and
        # the fallback below would then have filed that job under the caller's own
        # organisation, so the cross-tenant read left no trace on the job record.
        # Staff may legitimately belong to no organisation, and keep global reach.
        caller_org = getattr(request.user, "organization", None)
        if caller_org is not None:
            audit_file = get_object_or_404(AuditFile, id=file_id, organization=caller_org)
        else:
            audit_file = get_object_or_404(AuditFile, id=file_id)

        organisation = caller_org or audit_file.organization

        job = AuditJob.objects.create(
            organization=organisation,
            audit_file=audit_file,
            created_by=request.user,
            audit_type=audit_type,
            status=AuditJob.Status.PENDING,
        )
        logger.info("AuditJob %s created by user %s.", job.id, request.user.id)

        # Dispatch to Celery if available, otherwise run synchronously
        dispatched_async = False
        try:
            from apps.audit_engine.tasks import run_audit_task

            run_audit_task.delay(str(job.id))
            job.status = AuditJob.Status.QUEUED
            job.save(update_fields=["status", "updated_at"])
            dispatched_async = True
            logger.info("AuditJob %s queued via Celery.", job.id)
        except AttributeError:
            # run_audit_task is the sync fallback (no .delay method)
            logger.info(
                "Celery unavailable; running AuditJob %s synchronously.", job.id
            )
            try:
                from apps.audit_engine.tasks import run_audit_task as sync_task

                sync_task(str(job.id))
            except Exception as exc:
                logger.error("Synchronous audit failed for job %s: %s", job.id, exc)
        except Exception as exc:
            logger.error("Failed to dispatch AuditJob %s to Celery: %s", job.id, exc)
            # Fall through — job remains PENDING; operator can re-trigger

        # Refresh from DB to pick up status updates
        job.refresh_from_db()
        response_serializer = AuditJobSerializer(job, context={"request": request})
        return Response(
            {
                "job": response_serializer.data,
                "dispatched_async": dispatched_async,
            },
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["get"], url_path="result", permission_classes=[CanViewAudit])
    def result(self, request, pk=None):
        """Retrieve the AuditResult for a specific job."""
        job = self.get_object()
        try:
            audit_result = job.result
        except AuditResult.DoesNotExist:
            return Response(
                {"detail": "No result available. The audit may still be in progress."},
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = AuditResultSerializer(audit_result, context={"request": request})
        return Response(serializer.data)

    @action(detail=True, methods=["post"], url_path="cancel", permission_classes=[CanRunAudit])
    def cancel(self, request, pk=None):
        """Cancel a job that is still PENDING or QUEUED."""
        job = self.get_object()
        cancellable_statuses = {AuditJob.Status.PENDING, AuditJob.Status.QUEUED}
        if job.status not in cancellable_statuses:
            return Response(
                {
                    "detail": (
                        f"Cannot cancel a job with status '{job.status}'. "
                        f"Only PENDING and QUEUED jobs can be canceled."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        job.status = AuditJob.Status.CANCELED
        job.save(update_fields=["status", "updated_at"])
        logger.info("AuditJob %s canceled by user %s.", job.id, request.user.id)
        return Response(
            {"detail": "Job canceled successfully.", "job_id": str(job.id)},
            status=status.HTTP_200_OK,
        )


class AuditResultViewSet(mixins.RetrieveModelMixin, GenericViewSet):
    """
    Read-only ViewSet for AuditResults.
    Results are scoped to the requesting user's organisation.

    Endpoints:
      GET /results/{id}/  — retrieve an AuditResult by its UUID
    """

    serializer_class = AuditResultSerializer
    permission_classes = [CanViewAudit]

    def get_queryset(self):
        user = self.request.user
        if user.is_staff:
            return AuditResult.objects.all().select_related("audit_job")
        return AuditResult.objects.filter(
            audit_job__organization=user.organization
        ).select_related("audit_job")
