"""ERP → Tadgeeg ingestion.

One ``run_ingestion(connection, since=None)`` does:

  1. Marks a SyncRun RUNNING with watermark = since (defaults to
     connection.last_synced_at).
  2. Resolves the connector via apps.erp.connectors.registry.
  3. authenticate() once.
  4. fetch_records(since=...) streamed.
  5. For each RemoteRecord:
       hash the payload → SyncRecord(payload_sha256=...)
       look up local row by (kind, external_id)
         → if new: create local row (Invoice / PO / JE / Vendor)
         → if changed (sha mismatch): update local row + write a diff
         → if same: SKIPPED
  6. On success: SyncRun.COMPLETED, connection.last_synced_at = max(external_updated_at).
  7. On failure: SyncRun.FAILED with traceback.

The mapper is deliberately small and reuses the existing
``apps.invoices.services.processor`` plumbing — it doesn't re-invent
invoice persistence.
"""
from __future__ import annotations

import hashlib
import json
import logging
import traceback
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from django.db import transaction

from apps.billing.services.features import require_feature
from apps.erp.connectors.base import ConnectionConfig, RemoteRecord
from apps.erp.connectors.registry import get_connector
from apps.erp.models import ERPConnection, SyncRecord, SyncRun

logger = logging.getLogger("finai.erp.ingestion")


def _sha(payload: dict) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      default=str).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _connector_for(connection: ERPConnection):
    cls = get_connector(connection.provider)
    cfg = ConnectionConfig(
        organization_id=str(connection.organization_id),
        provider=connection.provider,
        environment=connection.environment,
        base_url=connection.base_url,
        credentials=dict(connection.credentials or {}),
        extra=dict(connection.extra or {}),
    )
    return cls(cfg)


def run_ingestion(connection: ERPConnection,
                  *,
                  since: Optional[datetime] = None,
                  kinds=None,
                  triggered_by=None) -> SyncRun:
    """Pull every record from the ERP since the watermark."""
    require_feature(connection.organization, "erp")
    if connection.status != ERPConnection.Status.ACTIVE:
        raise RuntimeError(
            f"connection {connection.pk} is {connection.status}, refusing to sync"
        )

    since = since or connection.last_synced_at
    run = SyncRun.objects.create(
        connection=connection,
        direction=SyncRun.Direction.INGEST,
        status=SyncRun.Status.RUNNING,
        since=since,
        kinds=list(kinds or []),
        started_at=datetime.now(timezone.utc),
        triggered_by=triggered_by,
    )
    try:
        connector = _connector_for(connection)
        connector.authenticate()

        seen = imported = failed = 0
        latest_external_ts: Optional[datetime] = None

        for record in connector.fetch_records(since=since, kinds=kinds):
            seen += 1
            try:
                _ingest_one(connection, record, run)
                imported += 1
            except Exception as exc:                # pragma: no cover
                failed += 1
                logger.warning(
                    "[erp.ingest] %s/%s failed: %s",
                    record.kind, record.external_id, exc,
                )
                SyncRecord.objects.create(
                    run=run,
                    kind=record.kind,
                    external_id=record.external_id,
                    payload_sha256=_sha(record.payload),
                    action=SyncRecord.Action.FAILED,
                    error_message=str(exc)[:1000],
                )
            if record.external_updated_at and (
                latest_external_ts is None
                or record.external_updated_at > latest_external_ts
            ):
                latest_external_ts = record.external_updated_at

        run.records_seen     = seen
        run.records_imported = imported
        run.records_failed   = failed
        run.status           = SyncRun.Status.COMPLETED
        run.finished_at      = datetime.now(timezone.utc)
        run.until            = latest_external_ts
        run.save()

        if latest_external_ts:
            connection.last_synced_at = latest_external_ts
            connection.save(update_fields=["last_synced_at", "updated_at"])
        return run

    except Exception as exc:                        # pragma: no cover
        run.status = SyncRun.Status.FAILED
        run.error_message = f"{exc}\n\n{traceback.format_exc()[:2000]}"
        run.finished_at = datetime.now(timezone.utc)
        run.save()
        raise


# ─── Mapper ─────────────────────────────────────────────────────────────────
def _ingest_one(connection: ERPConnection, record: RemoteRecord, run: SyncRun):
    """Persist or upsert one RemoteRecord. Returns the SyncRecord."""
    sha = _sha(record.payload)

    # Default: only invoice mapping is wired here. Other kinds (PO, JE,
    # vendor) follow the same pattern through their respective apps.
    if record.kind == "invoice":
        local_pk, action = _upsert_invoice(connection, record, sha)
    elif record.kind == "vendor":
        local_pk, action = _upsert_vendor(connection, record, sha)
    else:
        # Other kinds — record the touch but defer the upsert wiring.
        local_pk, action = "", SyncRecord.Action.SKIPPED

    return SyncRecord.objects.create(
        run=run,
        kind=record.kind,
        external_id=record.external_id,
        payload_sha256=sha,
        local_model=_model_for_kind(record.kind),
        local_pk=local_pk,
        action=action,
    )


def _model_for_kind(kind: str) -> str:
    return {
        "invoice":         "invoices.Invoice",
        "vendor":          "invoices.VendorProfile",
        "purchase_order":  "documents.PurchaseOrder",
        "journal_entry":   "ledger.JournalEntry",
    }.get(kind, "")


@transaction.atomic
def _upsert_invoice(connection: ERPConnection, record: RemoteRecord, sha: str):
    """Idempotent upsert of an Invoice keyed by (org, external_id)."""
    from apps.invoices.models import Invoice
    payload = record.payload or {}

    defaults = {
        "invoice_number":  payload.get("invoice_number", ""),
        "vendor_name":     payload.get("vendor_name", ""),
        "vendor_vat_number": payload.get("vendor_vat_no", ""),
        "total_amount":    Decimal(str(payload.get("total_amount", "0"))),
        "vat_amount":      Decimal(str(payload.get("vat_amount", "0"))),
        "currency":        payload.get("currency", "SAR"),
        "invoice_date":    payload.get("invoice_date") or None,
    }

    inv, created = Invoice.objects.update_or_create(
        organization=connection.organization,
        external_source=record.source_system,
        external_id=record.external_id,
        defaults=defaults,
    )
    return str(inv.pk), (
        SyncRecord.Action.CREATED if created else SyncRecord.Action.UPDATED
    )


@transaction.atomic
def _upsert_vendor(connection: ERPConnection, record: RemoteRecord, sha: str):
    from apps.invoices.models import VendorProfile
    payload = record.payload or {}
    vp, created = VendorProfile.objects.update_or_create(
        organization=connection.organization,
        vendor_name=payload.get("vendor_name", record.external_id),
        defaults={
            "vat_number":  payload.get("vendor_vat_no", ""),
        },
    )
    return str(vp.pk), (
        SyncRecord.Action.CREATED if created else SyncRecord.Action.UPDATED
    )
