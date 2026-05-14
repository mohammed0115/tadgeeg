"""ERP integration layer.

Closes the BIG4 audit's #1 finding: Tadgeeg was billing itself as an
"Enterprise Financial Audit Platform" but had **no actual ERP
integration code**. This package is the foundation.

Layout:
    connectors/     — provider-specific adapters (SAP, Oracle, Odoo, ...)
    sync/           — direction-agnostic transport + watermark + reconcile
    models.py       — ERPConnection, SyncRun, SyncRecord, ReconciliationDiff

Public entry points:
    from apps.erp.sync.ingestion import run_ingestion(connection)
    from apps.erp.sync.egress    import push_decision(connection, invoice)
    from apps.erp.sync.reconciliation import reconcile(connection, window)

Every connector below ``connectors/`` is a small adapter that maps the
provider's quirks (SAP IDoc, Oracle Fusion REST, Odoo XML-RPC, etc.)
into the shared `RemoteRecord` shape consumed by ``sync.ingestion``.
"""
