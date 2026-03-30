import logging
from apps.rule_engine.rules.base import NormalizedDocument
from apps.rule_engine.normalizers import BaseNormalizer, DocumentNormalizerFactory

logger = logging.getLogger("rule_engine")


class GRNNormalizer(BaseNormalizer):
    document_type = "grn"

    def normalize(self, document_id: str, organization_id: str) -> NormalizedDocument:
        from apps.documents.typed_models import GoodsReceiptNote
        try:
            grn = GoodsReceiptNote.objects.get(id=document_id)
        except GoodsReceiptNote.DoesNotExist:
            logger.warning(f"GoodsReceiptNote {document_id} not found")
            return NormalizedDocument(
                document_id=str(document_id),
                document_type="grn",
                organization_id=str(organization_id),
            )

        # Pull AI-extraction fields from the linked base Document if available
        ai_fields = {}
        try:
            base_doc = grn.document
            ai_fields = {
                "ocr_confidence": getattr(base_doc, "ocr_confidence", None),
                "is_handwritten": getattr(base_doc, "is_handwritten", False),
                "has_alterations": getattr(base_doc, "has_alterations", False),
                "clarity_score": getattr(base_doc, "ocr_confidence", None),
                "content_fingerprint": getattr(base_doc, "content_hash", None),
                "risk_score": None,
                "ai_extracted_fields": list(grn.validation_details or []),
            }
        except Exception:
            pass

        typed_data = {
            "grn_number": grn.grn_number,
            "grn_date": str(grn.grn_date) if grn.grn_date else None,
            "po_number": grn.po_number,
            "po_id": str(grn.po_id) if grn.po_id else None,
            "invoice_number": grn.invoice_number,
            "vendor_name": grn.vendor_name,
            "vendor_vat_number": grn.vendor_vat_number,
            "department": grn.department,
            "received_by": grn.received_by,
            "warehouse_location": grn.warehouse_location,
            "total_ordered_qty": float(grn.total_ordered_qty),
            "total_received_qty": float(grn.total_received_qty),
            "total_rejected_qty": float(grn.total_rejected_qty),
            "invoice_amount": float(grn.invoice_amount) if grn.invoice_amount is not None else None,
            "line_items": grn.line_items or [],
            "quantity_variance_pct": grn.quantity_variance_pct,
            "has_quantity_mismatch": grn.has_quantity_mismatch,
            "has_price_deviation": grn.has_price_deviation,
            "rejection_rate_pct": grn.rejection_rate_pct,
            "delivery_date": str(grn.delivery_date) if grn.delivery_date else None,
            "delivery_overdue": grn.delivery_overdue,
            "quality_inspection_done": grn.quality_inspection_done,
            "inspector_name": grn.inspector_name,
            "approval_status": grn.approval_status,
            "approved_by_id": str(grn.approved_by_id) if grn.approved_by_id else None,
            "uploaded_by_id": str(grn.uploaded_by_id) if grn.uploaded_by_id else None,
            "created_at": str(grn.created_at) if grn.created_at else None,
            "updated_at": str(grn.updated_at) if grn.updated_at else None,
            **ai_fields,
        }

        return NormalizedDocument(
            document_id=str(document_id),
            document_type="grn",
            organization_id=str(organization_id),
            document_number=grn.grn_number,
            document_date=grn.grn_date,
            total_amount=float(grn.total_amount) if grn.total_amount is not None else None,
            currency=grn.currency,
            counterparty_name=grn.vendor_name,
            tax_id=grn.vendor_vat_number,
            approved_by_id=str(grn.approved_by_id) if grn.approved_by_id else None,
            typed_data=typed_data,
            org_context=self._get_org_context(organization_id),
        )


DocumentNormalizerFactory.register("grn", GRNNormalizer)
