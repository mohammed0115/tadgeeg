"""
run_audit_compat — Migration bridge between AuditPipeline V1 and V2.

Controls which pipeline version executes via the AUDIT_ENGINE_VERSION
Django setting. No code changes are needed to switch versions — only a
settings change (or environment variable) is required.

Settings
--------
  AUDIT_ENGINE_VERSION = "v2"     # Default — run V2 pipeline
  AUDIT_ENGINE_VERSION = "v1"     # Fall back to original AuditPipeline
  AUDIT_ENGINE_VERSION = "shadow" # V2 primary + V1 in background for comparison

Usage (drop-in replacement for any existing audit trigger)
----------------------------------------------------------
    from apps.rule_engine.pipeline.v2.compat import run_audit_compat

    audit_run = run_audit_compat(
        document_id="...",
        document_type="sales_invoice",
        organization_id="...",
        triggered_by="upload",
    )

Per-call override (A/B testing, debugging)
------------------------------------------
    audit_run = run_audit_compat(
        document_id="...",
        document_type="sales_invoice",
        organization_id="...",
        engine_override="v1",   # ignore AUDIT_ENGINE_VERSION just for this call
    )
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("rule_engine.pipeline")

__all__ = ["run_audit_compat"]


def run_audit_compat(
    document_id: str,
    document_type: str,
    organization_id: str,
    triggered_by: str = "upload",
    force_rerun: bool = False,
    engine_override: Optional[str] = None,
):
    """
    Route an audit execution to the appropriate pipeline version.

    Parameters
    ----------
    engine_override : "v1" | "v2" | "shadow" — overrides AUDIT_ENGINE_VERSION
                      for this single call. Useful for A/B testing or rollback.
    """
    from django.conf import settings

    version = engine_override or getattr(settings, "AUDIT_ENGINE_VERSION", "v2")

    logger.info(
        "[compat] run_audit_compat doc=%s type=%s engine=%s",
        document_id, document_type, version,
    )

    if version == "v1":
        return _run_v1(document_id, document_type, organization_id, triggered_by)

    if version == "shadow":
        # Primary: V2 — result returned to the caller
        result = _run_v2(
            document_id, document_type, organization_id,
            triggered_by, force_rerun,
        )
        # Background: V1 — comparison only, fire-and-forget via Celery
        try:
            from apps.rule_engine.tasks.audit_tasks import run_shadow_audit_task
            run_shadow_audit_task.delay(document_id, document_type, organization_id)
        except Exception as exc:
            logger.warning("[compat] Shadow V1 task dispatch failed (non-fatal): %s", exc)
        return result

    # Default: "v2"
    return _run_v2(document_id, document_type, organization_id, triggered_by, force_rerun)


# ── Internal runners ───────────────────────────────────────────────────────────

def _run_v2(
    document_id: str,
    document_type: str,
    organization_id: str,
    triggered_by: str,
    force_rerun: bool = False,
):
    from apps.rule_engine.pipeline.v2.pipeline import AuditPipelineV2
    return AuditPipelineV2().run(
        document_id=document_id,
        document_type=document_type,
        organization_id=organization_id,
        triggered_by=triggered_by,
        force_rerun=force_rerun,
    )


def _run_v1(
    document_id: str,
    document_type: str,
    organization_id: str,
    triggered_by: str,
):
    from apps.rule_engine.executors.audit_pipeline import AuditPipeline
    return AuditPipeline().run(
        document_id=document_id,
        document_type=document_type,
        organization_id=organization_id,
        triggered_by=triggered_by,
    )
