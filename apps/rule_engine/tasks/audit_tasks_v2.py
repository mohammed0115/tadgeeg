"""
Celery tasks for AuditPipeline V2.

Tasks
-----
run_audit_v2_task       Primary V2 task — full 6-stage pipeline.
run_audit_compat_task   Drop-in replacement for V1 run_audit_task; routes via
                        run_audit_compat (respects AUDIT_ENGINE_VERSION setting).
run_bulk_audit_v2_task  Parallel batch audit for a list of documents.

Key improvements over V1 tasks
-------------------------------
  acks_late=True            Task is only ACKed after successful completion.
                            If the worker dies mid-run, the task is requeued.
  reject_on_worker_lost=True  Requeue on ungraceful worker termination.
  Idempotency               The pipeline itself enforces deduplication; Celery
                            task dispatch is therefore safe to retry freely.
"""
import logging

from celery import group, shared_task

logger = logging.getLogger("rule_engine.pipeline")


# ── Primary V2 task ────────────────────────────────────────────────────────────

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    soft_time_limit=180,
    time_limit=240,
    name="rule_engine.run_audit_v2",
    acks_late=True,
    reject_on_worker_lost=True,
)
def run_audit_v2_task(
    self,
    document_id: str,
    document_type: str,
    organization_id: str,
    triggered_by: str = "upload",
    force_rerun: bool = False,
):
    """
    Async V2 pipeline execution.

    Idempotency is enforced at the pipeline level (AuditPipelineV2._find_existing_run),
    so duplicate Celery dispatches safely return the cached run.
    """
    logger.info(
        "[celery_v2] run_audit_v2: doc=%s type=%s org=%s trigger=%s",
        document_id, document_type, organization_id, triggered_by,
    )
    try:
        from apps.rule_engine.pipeline.v2.pipeline import AuditPipelineV2
        audit_run = AuditPipelineV2().run(
            document_id=document_id,
            document_type=document_type,
            organization_id=organization_id,
            triggered_by=triggered_by,
            force_rerun=force_rerun,
        )
        return {
            "audit_run_id": str(audit_run.id),
            "risk_score":   float(audit_run.risk_score or 0),
            "risk_level":   audit_run.risk_level,
            "failed_rules": audit_run.failed_rules,
            "status":       audit_run.status,
        }
    except Exception as exc:
        logger.error("[celery_v2] run_audit_v2 failed for doc=%s: %s", document_id, exc)
        raise self.retry(exc=exc)


# ── Compat task (drop-in for V1) ───────────────────────────────────────────────

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    soft_time_limit=180,
    time_limit=240,
    name="rule_engine.run_audit_compat",
    acks_late=True,
    reject_on_worker_lost=True,
)
def run_audit_compat_task(
    self,
    document_id: str,
    document_type: str,
    organization_id: str,
    triggered_by: str = "upload",
    engine_override: str = None,
):
    """
    Drop-in replacement for the V1 rule_engine.run_audit task.

    Routes to V1 or V2 based on AUDIT_ENGINE_VERSION setting.
    Existing callers only need to change the task name from
    "rule_engine.run_audit" → "rule_engine.run_audit_compat".
    """
    try:
        from apps.rule_engine.pipeline.v2.compat import run_audit_compat
        audit_run = run_audit_compat(
            document_id=document_id,
            document_type=document_type,
            organization_id=organization_id,
            triggered_by=triggered_by,
            engine_override=engine_override,
        )
        return {
            "audit_run_id": str(audit_run.id),
            "risk_score":   float(audit_run.risk_score or 0),
            "risk_level":   audit_run.risk_level,
            "failed_rules": audit_run.failed_rules,
            "status":       audit_run.status,
        }
    except Exception as exc:
        logger.error("[celery_compat] compat task failed for doc=%s: %s", document_id, exc)
        raise self.retry(exc=exc)


# ── Bulk audit task ─────────────────────────────────────────────────────────────

@shared_task(name="rule_engine.run_bulk_audit_v2")
def run_bulk_audit_v2_task(
    documents: list,
    organization_id: str,
    triggered_by: str = "scheduled",
):
    """
    Dispatch a parallel group of V2 audits for multiple documents.

    Parameters
    ----------
    documents     list of {"document_id": str, "document_type": str}
    organization_id  UUID of the owning organisation.
    triggered_by  Audit trigger source (default: "scheduled").

    Returns a Celery GroupResult (async).
    """
    tasks = [
        run_audit_v2_task.s(
            document_id=doc["document_id"],
            document_type=doc["document_type"],
            organization_id=organization_id,
            triggered_by=triggered_by,
        )
        for doc in documents
        if doc.get("document_id") and doc.get("document_type")
    ]
    if not tasks:
        logger.warning("[celery_v2] run_bulk_audit_v2 called with empty document list.")
        return None
    logger.info("[celery_v2] Dispatching bulk audit: %d documents.", len(tasks))
    return group(tasks).apply_async()
