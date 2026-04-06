import logging

logger = logging.getLogger(__name__)

AuditJob = None
LegacyAuditOrchestratorAdapter = None


def _get_audit_job_model():
    global AuditJob
    if AuditJob is None:
        from apps.audit_engine.models import AuditJob as AuditJobModel

        AuditJob = AuditJobModel
    return AuditJob


def _get_orchestrator_adapter():
    global LegacyAuditOrchestratorAdapter
    if LegacyAuditOrchestratorAdapter is None:
        from apps.rule_engine.services.compatibility.legacy_audit_adapter import (
            LegacyAuditOrchestratorAdapter as LegacyAdapter,
        )

        LegacyAuditOrchestratorAdapter = LegacyAdapter
    return LegacyAuditOrchestratorAdapter


def _run_audit_job(job_id: str, retry_handler=None):
    """Execute an audit job through the rule-engine compatibility adapter."""
    from apps.audit_engine.exceptions import AuditJobError

    audit_job_model = _get_audit_job_model()

    try:
        job = audit_job_model.objects.get(id=job_id)
    except audit_job_model.DoesNotExist:
        logger.error("run_audit_task: AuditJob %s not found — task will not retry.", job_id)
        return None

    try:
        status_enum = getattr(audit_job_model, "Status", None)
        if status_enum is not None and hasattr(status_enum, "QUEUED"):
            job.status = status_enum.QUEUED
        else:
            job.status = "queued"
        job.save(update_fields=["status", "updated_at"])

        orchestrator = _get_orchestrator_adapter()()
        result = orchestrator.run(job)

        result_id = getattr(result, "id", None)
        overall_score = getattr(result, "overall_score", None)
        if overall_score is not None:
            logger.info(
                "run_audit_task: AuditJob %s completed. Result id=%s score=%.2f",
                job_id,
                result_id,
                overall_score,
            )
        else:
            logger.info("run_audit_task: AuditJob %s completed. Result id=%s", job_id, result_id)
        return result
    except AuditJobError as exc:
        logger.error("run_audit_task: AuditJob %s failed with AuditJobError: %s", job_id, exc)
        if retry_handler is not None:
            raise retry_handler(exc=exc)
        raise
    except Exception as exc:
        logger.exception("run_audit_task: Unexpected error for AuditJob %s: %s", job_id, exc)
        if retry_handler is not None:
            raise retry_handler(exc=exc)
        raise


try:
    from finai_backend.celery import app as celery_app

    @celery_app.task(bind=True, max_retries=3, default_retry_delay=60, name="audit_engine.run_audit_task")
    def run_audit_task(self, job_id: str):
        """Celery task wrapper for the compatibility-backed audit runner."""
        return _run_audit_job(job_id, retry_handler=self.retry)

except ImportError:
    logger.warning(
        "audit_engine.tasks: Celery import failed. "
        "run_audit_task will run synchronously."
    )

    def run_audit_task(job_id: str):
        """Synchronous fallback for run_audit_task when Celery is unavailable."""
        return _run_audit_job(job_id)
