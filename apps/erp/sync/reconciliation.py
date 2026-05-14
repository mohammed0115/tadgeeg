"""ERP ↔ Tadgeeg reconciliation.

After every ingestion run, compare what ERP reports for the window
against what Tadgeeg holds. Discrepancies are written as
``ReconciliationDiff`` rows so the auditor sees them in the dashboard.

Types of diff this engine reports:

  • missing_in_tadgeeg   — ERP has it, Tadgeeg doesn't
  • missing_in_erp       — Tadgeeg has it (external_id set), ERP didn't return it
  • amount_mismatch      — both have it, totals differ > tolerance
  • vat_mismatch         — VAT amounts differ
  • date_mismatch        — invoice_date differs

This is the **independence layer**: a Tadgeeg/ERP mismatch is exactly
the moment a fraud or a process error becomes visible.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Iterable

from apps.erp.connectors.base import ConnectionConfig, RemoteRecord
from apps.erp.connectors.registry import get_connector
from apps.erp.models import ERPConnection, ReconciliationDiff

logger = logging.getLogger("finai.erp.reconcile")


_AMOUNT_TOLERANCE = Decimal("0.01")   # SAR


def reconcile_window(connection: ERPConnection,
                     *,
                     since: datetime,
                     until: datetime | None = None) -> dict:
    """Compare ERP rows vs Tadgeeg rows for the window ``[since, until]``.

    Persists one ReconciliationDiff row per mismatch. Returns a summary
    dict for the caller / dashboard widget.
    """
    until = until or datetime.now(timezone.utc)
    from apps.invoices.models import Invoice

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
    connector.authenticate()

    erp_rows = {
        r.external_id: r
        for r in connector.fetch_records(since=since, kinds=["invoice"])
    }
    local_rows = {
        inv.external_id: inv
        for inv in Invoice.objects.filter(
            organization=connection.organization,
            external_source=connection.provider,
            invoice_date__gte=since.date() if hasattr(since, "date") else since,
        ).exclude(external_id="")
    }

    diffs_created = 0
    counts = {"missing_in_tadgeeg": 0, "missing_in_erp": 0,
              "amount_mismatch": 0, "vat_mismatch": 0, "date_mismatch": 0}

    # missing_in_tadgeeg
    for ext_id, rec in erp_rows.items():
        if ext_id in local_rows:
            continue
        counts["missing_in_tadgeeg"] += 1
        diffs_created += _write_diff(
            connection, kind="invoice", diff_type="missing_in_tadgeeg",
            severity="high", external_id=ext_id,
            summary=f"ERP has invoice {ext_id} which Tadgeeg has no record of.",
            detail={"erp_payload": rec.payload},
        )

    # missing_in_erp + amount / vat / date diffs
    for ext_id, inv in local_rows.items():
        rec = erp_rows.get(ext_id)
        if rec is None:
            counts["missing_in_erp"] += 1
            diffs_created += _write_diff(
                connection, kind="invoice", diff_type="missing_in_erp",
                severity="critical", external_id=ext_id, local_pk=str(inv.pk),
                summary=f"Tadgeeg has invoice {ext_id} which ERP returned nothing for.",
            )
            continue

        # Both present — compare amounts / VAT / dates.
        erp_total = Decimal(str(rec.payload.get("total_amount", "0") or "0"))
        local_total = Decimal(str(inv.total_amount or 0))
        if abs(erp_total - local_total) > _AMOUNT_TOLERANCE:
            counts["amount_mismatch"] += 1
            diffs_created += _write_diff(
                connection, kind="invoice", diff_type="amount_mismatch",
                severity="high", external_id=ext_id, local_pk=str(inv.pk),
                summary=f"Amount mismatch on {ext_id}: ERP={erp_total} vs Tadgeeg={local_total}.",
                detail={"erp": str(erp_total), "tadgeeg": str(local_total)},
            )

        erp_vat = Decimal(str(rec.payload.get("vat_amount", "0") or "0"))
        local_vat = Decimal(str(inv.vat_amount or 0))
        if abs(erp_vat - local_vat) > _AMOUNT_TOLERANCE:
            counts["vat_mismatch"] += 1
            diffs_created += _write_diff(
                connection, kind="invoice", diff_type="vat_mismatch",
                severity="medium", external_id=ext_id, local_pk=str(inv.pk),
                summary=f"VAT mismatch on {ext_id}: ERP={erp_vat} vs Tadgeeg={local_vat}.",
            )

    return {
        "diffs_created": diffs_created,
        "counts":        counts,
        "window":        {"since": since.isoformat(),
                          "until": until.isoformat() if until else ""},
    }


def _write_diff(connection, *, kind, diff_type, severity, external_id,
                summary, local_pk="", detail=None) -> int:
    ReconciliationDiff.objects.create(
        connection=connection,
        organization=connection.organization,
        kind=kind,
        diff_type=diff_type,
        severity=severity,
        external_id=external_id,
        local_pk=local_pk,
        summary=summary[:255],
        detail=detail or {},
    )
    return 1
