import logging
from apps.rule_engine.rules.base import NormalizedDocument
from apps.rule_engine.normalizers import BaseNormalizer, DocumentNormalizerFactory

logger = logging.getLogger("rule_engine")


class PurchaseOrderNormalizer(BaseNormalizer):
    document_type = "purchase_order"

    def normalize(self, document_id: str, organization_id: str) -> NormalizedDocument:
        from apps.documents.typed_models import PurchaseOrder
        try:
            po = PurchaseOrder.objects.get(id=document_id)
        except PurchaseOrder.DoesNotExist:
            logger.warning(f"PurchaseOrder {document_id} not found")
            return NormalizedDocument(
                document_id=str(document_id),
                document_type="purchase_order",
                organization_id=str(organization_id),
            )

        typed_data = {
            "po_number": po.po_number,
            "po_date": str(po.po_date) if po.po_date else None,
            "delivery_date": str(po.delivery_date) if po.delivery_date else None,
            "vendor_name": po.vendor_name,
            "vendor_vat_number": po.vendor_vat_number,
            "vendor_cr_number": po.vendor_cr_number,
            "subtotal": float(po.subtotal) if po.subtotal is not None else None,
            "vat_amount": float(po.vat_amount) if po.vat_amount is not None else None,
            "budget_limit": float(po.budget_limit) if po.budget_limit is not None else None,
            "line_items": po.line_items or [],
            "linked_invoice_id": str(po.linked_invoice_id) if po.linked_invoice_id else None,
            "has_price_discrepancy": po.has_price_discrepancy,
            "price_discrepancy_pct": float(po.price_discrepancy_pct) if po.price_discrepancy_pct is not None else None,
            "quantity_mismatch": po.quantity_mismatch,
            "approval_status": po.approval_status,
        }

        return NormalizedDocument(
            document_id=str(document_id),
            document_type="purchase_order",
            organization_id=str(organization_id),
            document_number=po.po_number,
            document_date=po.po_date,
            total_amount=float(po.total_amount) if po.total_amount is not None else None,
            currency=po.currency,
            counterparty_name=po.vendor_name,
            tax_id=po.vendor_vat_number,
            budget_limit=float(po.budget_limit) if po.budget_limit is not None else None,
            typed_data=typed_data,
            org_context=self._get_org_context(organization_id),
        )


DocumentNormalizerFactory.register("purchase_order", PurchaseOrderNormalizer)
