"""
Celery tasks for asynchronous audit execution.
"""
import logging
from celery import shared_task

logger = logging.getLogger("rule_engine")


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    soft_time_limit=120,
    time_limit=180,
    name="rule_engine.run_audit",
)
def run_audit_task(self, document_id: str, document_type: str, organization_id: str, triggered_by: str = "upload"):
    """
    Asynchronously execute audit pipeline for a document.
    Auto-retries on transient failures (up to 3 times).
    """
    logger.info(f"[Celery] Starting audit: doc={document_id}, type={document_type}, org={organization_id}")
    try:
        from apps.rule_engine.executors.audit_pipeline import AuditPipeline
        pipeline = AuditPipeline()
        audit_run = pipeline.run(
            document_id=document_id,
            document_type=document_type,
            organization_id=organization_id,
            triggered_by=triggered_by,
        )
        logger.info(f"[Celery] Audit complete: run_id={audit_run.id}, risk={audit_run.risk_score}")
        return {
            "audit_run_id": str(audit_run.id),
            "risk_score": float(audit_run.risk_score or 0),
            "risk_level": audit_run.risk_level,
            "failed_rules": audit_run.failed_rules,
        }
    except Exception as exc:
        logger.error(f"[Celery] Audit failed for {document_id}: {exc}")
        raise self.retry(exc=exc)


@shared_task(name="rule_engine.run_shadow_audit")
def run_shadow_audit_task(document_id: str, document_type: str, organization_id: str):
    """
    Shadow audit: runs new engine alongside old engine for comparison.
    Results are stored but not surfaced in UI.
    """
    try:
        from apps.rule_engine.executors.audit_pipeline import AuditPipeline
        pipeline = AuditPipeline()
        audit_run = pipeline.run(
            document_id=document_id,
            document_type=document_type,
            organization_id=organization_id,
            triggered_by="shadow",
        )
        return {"shadow_run_id": str(audit_run.id), "status": "completed"}
    except Exception as e:
        logger.warning(f"[Shadow] Audit failed for {document_id}: {e}")
        return {"status": "failed", "error": str(e)}
