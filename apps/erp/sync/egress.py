"""Tadgeeg → ERP egress.

When Tadgeeg approves / rejects / flags an invoice, the decision is
pushed back to the source ERP so the workflow there closes the loop.

Failed pushes are queued for retry (Celery beat picks them up).
"""
from __future__ import annotations

import logging
import traceback
from datetime import datetime, timezone
from typing import Optional

from apps.erp.connectors.base import ConnectionConfig, PushDecision
from apps.erp.connectors.registry import get_connector
from apps.erp.models import ERPConnection, SyncRun

logger = logging.getLogger("finai.erp.egress")


def push_invoice_decision(connection: ERPConnection,
                          *,
                          invoice,
                          decided_by,
                          decision: str = "approved",
                          reason: str = "") -> SyncRun:
    """Push a decision for one invoice. Returns the SyncRun row."""
    if connection.status != ERPConnection.Status.ACTIVE:
        raise RuntimeError(
            f"connection {connection.pk} is {connection.status}, refusing egress"
        )
    run = SyncRun.objects.create(
        connection=connection,
        direction=SyncRun.Direction.EGRESS,
        status=SyncRun.Status.RUNNING,
        started_at=datetime.now(timezone.utc),
        kinds=["invoice"],
        triggered_by=decided_by,
    )
    try:
        cls = get_connector(connection.provider)
        cfg = ConnectionConfig(
            organization_id=str(connection.organization_id),
            provider=connection.provider,
            environment=connection.environment,
            base_url=connection.base_url,
            credentials=dict(connection.credentials or {}),
            extra=dict(connection.extra or {}),
        )
        connector = cls(cfg)
        if not connector.supports_egress:
            run.status = SyncRun.Status.FAILED
            run.error_message = f"{connection.provider} does not support egress"
            run.finished_at = datetime.now(timezone.utc)
            run.save()
            return run

        connector.authenticate()
        decision_obj = PushDecision(
            invoice_external_id=getattr(invoice, "external_id", "") or str(invoice.pk),
            decision=decision,
            risk_score=int(getattr(invoice, "risk_score", 0) or 0),
            audit_findings=[],
            decided_by=str(getattr(decided_by, "pk", "")),
            decided_at=datetime.now(timezone.utc),
            reason=reason,
        )
        result = connector.push_decision(decision_obj)

        run.records_seen     = 1
        run.records_imported = 1 if result.success else 0
        run.records_failed   = 0 if result.success else 1
        run.status = (
            SyncRun.Status.COMPLETED if result.success else SyncRun.Status.FAILED
        )
        run.error_message = "" if result.success else result.message
        run.finished_at = datetime.now(timezone.utc)
        run.save()
        return run
    except Exception as exc:                         # pragma: no cover
        run.status = SyncRun.Status.FAILED
        run.error_message = f"{exc}\n\n{traceback.format_exc()[:2000]}"
        run.finished_at = datetime.now(timezone.utc)
        run.save()
        raise
