import logging
from apps.rule_engine.rules.base import NormalizedDocument
from apps.rule_engine.normalizers import BaseNormalizer, DocumentNormalizerFactory

logger = logging.getLogger("rule_engine")


class SalesReceiptNormalizer(BaseNormalizer):
    document_type = "sales_receipt"

    def normalize(self, document_id: str, organization_id: str) -> NormalizedDocument:
        from apps.documents.typed_models import SalesReceipt
        try:
            receipt = SalesReceipt.objects.get(id=document_id)
        except SalesReceipt.DoesNotExist:
            logger.warning(f"SalesReceipt {document_id} not found")
            return NormalizedDocument(
                document_id=str(document_id),
                document_type="sales_receipt",
                organization_id=str(organization_id),
            )

        typed_data = {
            "receipt_number": receipt.receipt_number,
            "receipt_date": str(receipt.receipt_date) if receipt.receipt_date else None,
            "receipt_type": receipt.receipt_type,
            "seller_name": receipt.seller_name,
            "seller_vat_number": receipt.seller_vat_number,
            "customer_name": receipt.customer_name,
            "customer_vat_number": receipt.customer_vat_number,
            "subtotal": float(receipt.subtotal) if receipt.subtotal is not None else None,
            "vat_rate": float(receipt.vat_rate) if receipt.vat_rate is not None else 15.0,
            "vat_amount": float(receipt.vat_amount) if receipt.vat_amount is not None else None,
            "line_items": receipt.line_items or [],
            "has_qr_code": receipt.has_qr_code,
            "qr_code_valid": receipt.qr_code_valid,
            "qr_code_data": receipt.qr_code_data or {},
            "zatca_uuid": receipt.zatca_uuid,
            "is_duplicate": receipt.is_duplicate,
            "file_hash": receipt.file_hash,
        }

        return NormalizedDocument(
            document_id=str(document_id),
            document_type="sales_receipt",
            organization_id=str(organization_id),
            document_number=receipt.receipt_number,
            document_date=receipt.receipt_date,
            total_amount=float(receipt.total_amount) if receipt.total_amount is not None else None,
            currency=receipt.currency,
            counterparty_name=receipt.seller_name,
            tax_id=receipt.seller_vat_number,
            file_hash=receipt.file_hash,
            typed_data=typed_data,
            org_context=self._get_org_context(organization_id),
        )


DocumentNormalizerFactory.register("sales_receipt", SalesReceiptNormalizer)
