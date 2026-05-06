"""HTTP API for the Procurement workflow — Phase 7.3.

Endpoints:

    GET    /api/v1/procurement/requisitions/         list PRs (org-scoped)
    POST   /api/v1/procurement/requisitions/         create draft PR
    GET    /api/v1/procurement/requisitions/<id>/    PR detail
    POST   /api/v1/procurement/requisitions/<id>/submit/   submit for approval
    POST   /api/v1/procurement/requisitions/<id>/approve/  approve (role-gated)
    POST   /api/v1/procurement/requisitions/<id>/reject/   reject with reason
    POST   /api/v1/procurement/requisitions/<id>/convert-to-po/   issue PO
    GET    /api/v1/procurement/threeway/             list 3-way match rows
    POST   /api/v1/procurement/threeway/run/         re-evaluate a PO
"""

from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.procurement import services as proc
from apps.procurement.models import (
    PRApproval, PurchaseRequisition, ThreeWayMatchResult,
)


def _serialise_pr(pr: PurchaseRequisition) -> dict:
    return {
        "id":           str(pr.id),
        "pr_number":    pr.pr_number,
        "title":        pr.title,
        "description":  pr.description,
        "status":       pr.status,
        "currency":     pr.currency,
        "total_amount": float(pr.total_amount),
        "vendor_name":  pr.vendor_name,
        "department":   pr.department,
        "cost_center":  pr.cost_center,
        "needed_by":    pr.needed_by.isoformat() if pr.needed_by else None,
        "submitted_at": pr.submitted_at.isoformat() if pr.submitted_at else None,
        "approved_at":  pr.approved_at.isoformat() if pr.approved_at else None,
        "approved_by":  pr.approved_by.email if pr.approved_by_id else None,
        "rejected_at":  pr.rejected_at.isoformat() if pr.rejected_at else None,
        "rejection_reason": pr.rejection_reason,
        "purchase_order_id": str(pr.purchase_order_id) if pr.purchase_order_id else None,
        "lines": [
            {
                "line_number":  li.line_number,
                "description":  li.description,
                "quantity":     float(li.quantity),
                "unit_price":   float(li.unit_price),
                "line_total":   float(li.line_total),
                "account_code": li.account_code,
            } for li in pr.lines.order_by("line_number")
        ],
        "approvals": [
            {
                "decided_at":    ap.decided_at.isoformat(),
                "decided_by":    ap.decided_by.email if ap.decided_by_id else None,
                "decision":      ap.decision,
                "notes":         ap.notes,
                "threshold_role": ap.threshold_role,
            } for ap in pr.approvals.all()
        ],
    }


def _serialise_match(m: ThreeWayMatchResult) -> dict:
    return {
        "id":             str(m.id),
        "purchase_order": str(m.purchase_order_id),
        "goods_receipt":  str(m.goods_receipt_id) if m.goods_receipt_id else None,
        "invoice":        str(m.invoice_id) if m.invoice_id else None,
        "status":         m.status,
        "score":          m.score,
        "differences":    m.differences,
        "computed_at":    m.computed_at.isoformat(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Requisitions
# ─────────────────────────────────────────────────────────────────────────────

class RequisitionListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        org = getattr(request.user, "organization", None)
        if not org:
            return Response({"results": []})
        qs = PurchaseRequisition.objects.filter(organization=org).prefetch_related(
            "lines", "approvals",
        )
        if status := request.GET.get("status"):
            qs = qs.filter(status=status)
        return Response({
            "results": [_serialise_pr(pr) for pr in qs[:200]],
        })

    def post(self, request):
        org = getattr(request.user, "organization", None)
        if not org:
            return Response({"error": "user has no organization"}, status=400)
        data = request.data
        try:
            pr = proc.create_requisition(
                organization=org,
                requested_by=request.user,
                title=str(data.get("title") or "")[:200],
                description=str(data.get("description") or ""),
                department=str(data.get("department") or ""),
                cost_center=str(data.get("cost_center") or ""),
                vendor_name=str(data.get("vendor_name") or ""),
                currency=str(data.get("currency") or "SAR"),
                needed_by=data.get("needed_by") or None,
                lines=data.get("lines") or [],
            )
        except (ValueError, TypeError) as exc:
            return Response({"error": str(exc)}, status=400)
        return Response(_serialise_pr(pr), status=201)


class RequisitionDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def _load(self, request, pr_id):
        org = getattr(request.user, "organization", None)
        if not org:
            return None
        return PurchaseRequisition.objects.filter(
            organization=org, id=pr_id,
        ).prefetch_related("lines", "approvals").first()

    def get(self, request, pr_id):
        pr = self._load(request, pr_id)
        if not pr:
            return Response({"error": "not found"}, status=404)
        return Response(_serialise_pr(pr))


class _RequisitionAction(APIView):
    """Base for submit/approve/reject/convert actions."""
    permission_classes = [IsAuthenticated]

    def _load(self, request, pr_id):
        org = getattr(request.user, "organization", None)
        if not org:
            return None
        return PurchaseRequisition.objects.filter(
            organization=org, id=pr_id,
        ).first()


class RequisitionSubmitView(_RequisitionAction):
    def post(self, request, pr_id):
        pr = self._load(request, pr_id)
        if not pr:
            return Response({"error": "not found"}, status=404)
        try:
            proc.submit_for_approval(pr, user=request.user)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        return Response(_serialise_pr(pr))


class RequisitionApproveView(_RequisitionAction):
    def post(self, request, pr_id):
        pr = self._load(request, pr_id)
        if not pr:
            return Response({"error": "not found"}, status=404)
        try:
            proc.approve_requisition(
                pr, user=request.user,
                notes=str(request.data.get("notes") or ""),
            )
        except PermissionError as exc:
            return Response({"error": str(exc)}, status=403)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        return Response(_serialise_pr(pr))


class RequisitionRejectView(_RequisitionAction):
    def post(self, request, pr_id):
        pr = self._load(request, pr_id)
        if not pr:
            return Response({"error": "not found"}, status=404)
        reason = str(request.data.get("reason") or "").strip()
        if not reason:
            return Response({"error": "reason is required"}, status=400)
        try:
            proc.reject_requisition(pr, user=request.user, reason=reason)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        return Response(_serialise_pr(pr))


class RequisitionConvertView(_RequisitionAction):
    def post(self, request, pr_id):
        pr = self._load(request, pr_id)
        if not pr:
            return Response({"error": "not found"}, status=404)
        try:
            po = proc.convert_to_po(pr, user=request.user)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        pr.refresh_from_db()
        return Response({
            "purchase_order_id": str(po.id),
            "po_number": po.po_number,
            "requisition": _serialise_pr(pr),
        })


# ─────────────────────────────────────────────────────────────────────────────
# Three-way match
# ─────────────────────────────────────────────────────────────────────────────

class ThreeWayListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        org = getattr(request.user, "organization", None)
        if not org:
            return Response({"results": []})
        qs = ThreeWayMatchResult.objects.filter(organization=org)
        if status := request.GET.get("status"):
            qs = qs.filter(status=status)
        return Response({
            "results": [_serialise_match(m) for m in qs[:200]],
        })


class ThreeWayRunView(APIView):
    """Re-run a 3-way match for a given PO id (and optional GRN/Invoice)."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        org = getattr(request.user, "organization", None)
        if not org:
            return Response({"error": "user has no organization"}, status=400)

        from apps.documents.typed_models import GoodsReceiptNote, PurchaseOrder
        from apps.invoices.models import Invoice

        po_id = request.data.get("purchase_order_id")
        if not po_id:
            return Response({"error": "purchase_order_id required"}, status=400)
        po = PurchaseOrder.objects.filter(organization=org, id=po_id).first()
        if not po:
            return Response({"error": "purchase order not found"}, status=404)

        grn = None
        if grn_id := request.data.get("goods_receipt_id"):
            grn = GoodsReceiptNote.objects.filter(organization=org, id=grn_id).first()

        invoice = None
        if inv_id := request.data.get("invoice_id"):
            invoice = Invoice.objects.filter(organization=org, id=inv_id).first()

        match = proc.match_three_way(po, grn=grn, invoice=invoice)
        return Response(_serialise_match(match), status=201)
