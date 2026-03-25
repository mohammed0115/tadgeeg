import logging

logger = logging.getLogger(__name__)

try:
    from finai_backend.celery import app as celery_app

    @celery_app.task(bind=True, max_retries=3, default_retry_delay=60, name="audit_engine.run_audit_task")
    def run_audit_task(self, job_id: str):
        """
        Celery task — run the full audit pipeline for the given AuditJob UUID.

        Retries up to 3 times with a 60-second delay on transient failures.
        Permanent failures (e.g. job not found) are not retried.
        """
        from apps.audit_engine.exceptions import AuditJobError
        from apps.audit_engine.models import AuditJob
        from apps.audit_engine.services.orchestrator import AuditOrchestrator

        try:
            job = AuditJob.objects.get(id=job_id)
        except AuditJob.DoesNotExist:
            logger.error("run_audit_task: AuditJob %s not found — task will not retry.", job_id)
            return  # Non-retriable; the record doesn't exist

        try:
            job.status = AuditJob.Status.QUEUED
            job.save(update_fields=["status", "updated_at"])
            orchestrator = AuditOrchestrator()
            result = orchestrator.run(job)
            logger.info(
                "run_audit_task: AuditJob %s completed. Result id=%s score=%.2f",
                job_id,
                result.id,
                result.overall_score,
            )
        except AuditJobError as exc:
            # Job already marked FAILED by the orchestrator
            logger.error("run_audit_task: AuditJob %s failed with AuditJobError: %s", job_id, exc)
            raise self.retry(exc=exc)
        except Exception as exc:
            logger.exception(
                "run_audit_task: Unexpected error for AuditJob %s: %s", job_id, exc
            )
            raise self.retry(exc=exc)

except ImportError:
    # Celery is not configured or not installed — provide a synchronous fallback
    logger.warning(
        "audit_engine.tasks: Celery import failed. "
        "run_audit_task will run synchronously."
    )

    def run_audit_task(job_id: str):
        """
        Synchronous fallback for run_audit_task when Celery is unavailable.
        Called directly by the view layer.
        """
        from apps.audit_engine.models import AuditJob
        from apps.audit_engine.services.orchestrator import AuditOrchestrator

        try:
            job = AuditJob.objects.get(id=job_id)
        except AuditJob.DoesNotExist:
            logger.error("run_audit_task (sync): AuditJob %s not found.", job_id)
            return

        orchestrator = AuditOrchestrator()
        orchestrator.run(job)
        logger.info("run_audit_task (sync): AuditJob %s completed.", job_id)
