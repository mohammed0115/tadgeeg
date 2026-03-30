import logging
from apps.rule_engine.rules.base import NormalizedDocument
from apps.rule_engine.normalizers import BaseNormalizer, DocumentNormalizerFactory

logger = logging.getLogger("rule_engine")


class PaymentNormalizer(BaseNormalizer):
    document_type = "payment"

    def normalize(self, document_id: str, organization_id: str) -> NormalizedDocument:
        from apps.documents.typed_models import PaymentVoucher
        try:
            pmt = PaymentVoucher.objects.get(id=document_id)
        except PaymentVoucher.DoesNotExist:
            logger.warning(f"PaymentVoucher {document_id} not found")
            return NormalizedDocument(
                document_id=str(document_id),
                document_type="payment",
                organization_id=str(organization_id),
            )

        # Pull AI-extraction fields from the linked base Document if available
        ai_fields = {}
        try:
            base_doc = pmt.document
            ai_fields = {
                "ocr_confidence": getattr(base_doc, "ocr_confidence", None),
                "is_handwritten": getattr(base_doc, "is_handwritten", False),
                "has_alterations": getattr(base_doc, "has_alterations", False),
                "clarity_score": getattr(base_doc, "ocr_confidence", None),
                "content_fingerprint": getattr(base_doc, "content_hash", None),
                "risk_score": None,
                "ai_extracted_fields": list(pmt.validation_details or []),
            }
        except Exception:
            pass

        typed_data = {
            "payment_number": pmt.payment_number,
            "payment_date": str(pmt.payment_date) if pmt.payment_date else None,
            "payment_method": pmt.payment_method,
            "payee_name": pmt.payee_name,
            "payee_vat_number": pmt.payee_vat_number,
            "payee_iban": pmt.payee_iban,
            "amount": float(pmt.amount) if pmt.amount is not None else None,
            "vat_amount": float(pmt.vat_amount) if pmt.vat_amount is not None else None,
            "linked_invoice_number": pmt.linked_invoice_number,
            "linked_invoice_id": str(pmt.linked_invoice_id) if pmt.linked_invoice_id else None,
            "linked_po_number": pmt.linked_po_number,
            "bank_reference": pmt.bank_reference,
            "approval_status": pmt.approval_status,
            "approved_by_id": str(pmt.approved_by_id) if pmt.approved_by_id else None,
            "uploaded_by_id": str(pmt.uploaded_by_id) if pmt.uploaded_by_id else None,
            "cost_center": pmt.cost_center,
            "account_code": pmt.account_code,
            "is_duplicate": pmt.is_duplicate,
            "exceeds_threshold": pmt.exceeds_threshold,
            "is_advance_payment": pmt.is_advance_payment,
            "advance_cleared": pmt.advance_cleared,
            "days_since_invoice": pmt.days_since_invoice,
            "created_at": str(pmt.created_at) if pmt.created_at else None,
            "updated_at": str(pmt.updated_at) if pmt.updated_at else None,
            **ai_fields,
        }

        return NormalizedDocument(
            document_id=str(document_id),
            document_type="payment",
            organization_id=str(organization_id),
            document_number=pmt.payment_number,
            document_date=pmt.payment_date,
            total_amount=float(pmt.total_amount) if pmt.total_amount is not None else None,
            currency=pmt.currency,
            counterparty_name=pmt.payee_name,
            tax_id=pmt.payee_vat_number,
            approved_by_id=str(pmt.approved_by_id) if pmt.approved_by_id else None,
            cost_center=pmt.cost_center,
            account_code=pmt.account_code,
            typed_data=typed_data,
            org_context=self._get_org_context(organization_id),
        )


DocumentNormalizerFactory.register("payment", PaymentNormalizer)
