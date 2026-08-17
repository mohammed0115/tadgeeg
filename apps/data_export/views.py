"""
Data export endpoint — GDPR / regulatory data-portability obligation.

Two endpoints:
    POST /api/v1/export/request/   — kicks off an export job, returns job_id
    GET  /api/v1/export/<job_id>/  — downloads the resulting ZIP archive

The export is shipped as a ZIP containing:
    organization.json     — org metadata
    invoices.csv          — every invoice with line items flattened
    purchase_orders.csv   — every PO with totals
    sales_receipts.csv
    fixed_assets.csv
    audit_log.csv         — last 1 year of audit trail

Generation is synchronous for orgs under the soft cap (~5K invoices). Beyond
that, a background thread streams the file to disk and the user polls.
"""
from __future__ import annotations

import csv
import io
import json
import uuid
import zipfile
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.http import FileResponse
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView


def _csv_writer(buf, header):
    w = csv.DictWriter(buf, fieldnames=header, extrasaction="ignore")
    w.writeheader()
    return w


def _build_zip(org, output_path: str) -> dict:
    """Write the org's full export to ``output_path``. Returns a manifest."""
    from apps.invoices.models import Invoice
    from apps.documents.typed_models import (
        PurchaseOrder, SalesReceipt, FixedAsset,
    )
    from apps.authentication.models import AuditLog

    counts = {}
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Organization metadata
        zf.writestr("organization.json", json.dumps({
            "id": str(org.id),
            "name": getattr(org, "name", ""),
            "exported_at": timezone.now().isoformat(),
        }, indent=2))

        # Invoices
        buf = io.StringIO()
        w = _csv_writer(buf, [
            "id", "invoice_number", "vendor_name", "vendor_vat_number",
            "invoice_date", "due_date", "currency", "subtotal",
            "vat_amount", "total_amount", "status", "risk_level",
            "is_duplicate", "qr_code_valid", "created_at",
        ])
        n = 0
        for inv in Invoice.objects.filter(organization=org).iterator(chunk_size=500):
            w.writerow({
                "id": str(inv.id),
                "invoice_number": inv.invoice_number,
                "vendor_name": inv.vendor_name,
                "vendor_vat_number": inv.vendor_vat_number,
                "invoice_date": inv.invoice_date,
                "due_date": inv.due_date,
                "currency": inv.currency,
                "subtotal": inv.subtotal,
                "vat_amount": inv.vat_amount,
                "total_amount": inv.total_amount,
                "status": inv.status,
                "risk_level": inv.risk_level,
                "is_duplicate": inv.is_duplicate,
                "qr_code_valid": inv.qr_code_valid,
                "created_at": inv.created_at.isoformat(),
            })
            n += 1
        zf.writestr("invoices.csv", buf.getvalue())
        counts["invoices"] = n

        # Purchase orders
        buf = io.StringIO()
        w = _csv_writer(buf, [
            "id", "po_number", "po_date", "vendor_name", "vendor_vat_number",
            "currency", "subtotal", "vat_amount", "total_amount",
            "audit_status", "risk_level", "created_at",
        ])
        n = 0
        for po in PurchaseOrder.objects.filter(organization=org).iterator(chunk_size=500):
            w.writerow({
                "id": str(po.id), "po_number": po.po_number,
                "po_date": po.po_date, "vendor_name": po.vendor_name,
                "vendor_vat_number": po.vendor_vat_number,
                "currency": po.currency, "subtotal": po.subtotal,
                "vat_amount": po.vat_amount, "total_amount": po.total_amount,
                "audit_status": po.audit_status, "risk_level": po.risk_level,
                "created_at": po.created_at.isoformat(),
            })
            n += 1
        zf.writestr("purchase_orders.csv", buf.getvalue())
        counts["purchase_orders"] = n

        # Sales receipts
        buf = io.StringIO()
        w = _csv_writer(buf, [
            "id", "receipt_number", "receipt_date", "seller_name", "customer_name",
            "currency", "subtotal", "vat_amount", "total_amount", "audit_status",
        ])
        n = 0
        for sr in SalesReceipt.objects.filter(organization=org).iterator(chunk_size=500):
            w.writerow({
                "id": str(sr.id), "receipt_number": sr.receipt_number,
                "receipt_date": sr.receipt_date, "seller_name": sr.seller_name,
                "customer_name": sr.customer_name, "currency": sr.currency,
                "subtotal": sr.subtotal, "vat_amount": sr.vat_amount,
                "total_amount": sr.total_amount, "audit_status": sr.audit_status,
            })
            n += 1
        zf.writestr("sales_receipts.csv", buf.getvalue())
        counts["sales_receipts"] = n

        # Fixed assets
        buf = io.StringIO()
        w = _csv_writer(buf, [
            "id", "fiscal_year", "company_name", "asset_count",
            "total_cost", "total_book_value",
        ])
        n = 0
        for fa in FixedAsset.objects.filter(organization=org).iterator(chunk_size=500):
            w.writerow({
                "id": str(fa.id), "fiscal_year": fa.fiscal_year,
                "company_name": fa.company_name, "asset_count": fa.asset_count,
                "total_cost": fa.total_cost, "total_book_value": fa.total_book_value,
            })
            n += 1
        zf.writestr("fixed_assets.csv", buf.getvalue())
        counts["fixed_assets"] = n

        # Audit log (last 365 days)
        cutoff = timezone.now() - timedelta(days=365)
        buf = io.StringIO()
        w = _csv_writer(buf, [
            "id", "action", "user_id", "resource_type", "resource_id",
            "ip_address", "timestamp", "details",
        ])
        n = 0
        for log in AuditLog.objects.filter(
            organization=org, timestamp__gte=cutoff,
        ).iterator(chunk_size=500):
            w.writerow({
                "id": str(log.id), "action": log.action,
                "user_id": str(log.user_id) if log.user_id else "",
                "resource_type": log.resource_type, "resource_id": log.resource_id,
                "ip_address": log.ip_address or "",
                "timestamp": log.timestamp.isoformat(),
                "details": json.dumps(log.details, ensure_ascii=False)[:500],
            })
            n += 1
        zf.writestr("audit_log.csv", buf.getvalue())
        counts["audit_log_entries"] = n

        # Manifest
        zf.writestr("manifest.json", json.dumps(counts, indent=2))

    return counts


class DataExportRequestView(APIView):
    """POST: trigger an export. Returns a job_id + download URL.

    For orgs with < 5,000 records the file is built synchronously so the
    response includes the URL ready to download. For larger orgs, the job
    runs in a background thread and the URL becomes available after a short
    wait (poll the GET endpoint).
    """
    permission_classes = [IsAuthenticated]

    SOFT_CAP = 5000

    def post(self, request):
        from apps.invoices.models import Invoice

        org = request.user.organization
        if not org:
            return Response({"error": "no organization"}, status=400)

        # Estimate row count to choose sync vs async.
        invoice_count = Invoice.objects.filter(organization=org).count()
        job_id = uuid.uuid4().hex
        export_dir = Path(settings.MEDIA_ROOT) / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        output_path = export_dir / f"export_{org.id}_{job_id}.zip"

        if invoice_count <= self.SOFT_CAP:
            counts = _build_zip(org, output_path)
            return Response({
                "job_id": job_id,
                "status": "ready",
                "counts": counts,
                "download_url": f"/api/v1/export/{job_id}/",
            })

        # Async path
        from core.services.async_runner import run_in_background
        run_in_background(_build_zip, org, output_path)
        return Response({
            "job_id": job_id,
            "status": "processing",
            "estimated_rows": invoice_count,
            "download_url": f"/api/v1/export/{job_id}/",
            "note": "Poll the download URL — the file appears when ready.",
        })


class DataExportDownloadView(APIView):
    """GET /api/v1/export/<job_id>/ — stream the export ZIP."""
    permission_classes = [IsAuthenticated]

    def get(self, request, job_id):
        org = request.user.organization
        if not org:
            return Response({"error": "no organization"}, status=400)
        export_dir = Path(settings.MEDIA_ROOT) / "exports"
        path = export_dir / f"export_{org.id}_{job_id}.zip"
        if not path.exists():
            return Response({
                "status": "processing_or_unknown",
                "note": "File not yet ready. Poll again in a few seconds.",
            }, status=202)
        return FileResponse(
            open(path, "rb"),
            as_attachment=True,
            filename=f"tadgeeg-export-{org.id}-{job_id}.zip",
            content_type="application/zip",
        )
