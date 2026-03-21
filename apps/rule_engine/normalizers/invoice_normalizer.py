import logging
from apps.rule_engine.rules.base import NormalizedDocument
from apps.rule_engine.normalizers import BaseNormalizer, DocumentNormalizerFactory

logger = logging.getLogger("rule_engine")


class InvoiceNormalizer(BaseNormalizer):
    document_type = "sales_invoice"

    def normalize(self, document_id: str, organization_id: str) -> NormalizedDocument:
        from apps.invoices.models import Invoice
        try:
            inv = Invoice.objects.select_related("organization", "approved_by").get(
                id=document_id,
                organization_id=organization_id,
            )
        except Invoice.DoesNotExist:
            logger.warning(f"Invoice {document_id} not found for org {organization_id}")
            return NormalizedDocument(
                document_id=str(document_id),
                document_type="sales_invoice",
                organization_id=str(organization_id),
            )

        typed_data = {
            # Header
            "invoice_number": inv.invoice_number,
            "invoice_date": str(inv.invoice_date) if inv.invoice_date else None,
            "due_date": str(inv.due_date) if inv.due_date else None,
            # Vendor
            "vendor_name": inv.vendor_name,
            "vendor_vat_number": inv.vendor_vat_number,
            "vendor_cr_number": getattr(inv, "vendor_cr_number", None),
            # Financial
            "subtotal": float(inv.subtotal) if inv.subtotal else None,
            "vat_rate": float(inv.vat_rate) if inv.vat_rate else 15.0,
            "vat_amount": float(inv.vat_amount) if inv.vat_amount else None,
            "discount": float(inv.discount) if inv.discount else 0.0,
            "line_items": inv.line_items or [],
            # ZATCA
            "has_qr_code": inv.has_qr_code,
            "qr_code_valid": inv.qr_code_valid,
            # Document quality
            "is_clear": getattr(inv, "is_clear", True),
            "has_alterations": getattr(inv, "has_alterations", False),
            "is_handwritten": getattr(inv, "is_handwritten", False),
            # Accounting
            "cost_center": inv.cost_center,
            "account_code": inv.account_code,
            "budget_code": getattr(inv, "budget_code", None),
            "department": getattr(inv, "department", None),
            # Risk fields
            "risk_score": float(inv.risk_score) if inv.risk_score else None,
            "is_duplicate": inv.is_duplicate,
            "duplicate_of_id": str(inv.duplicate_of_id) if inv.duplicate_of_id else None,
            # AI
            "ai_summary": inv.ai_summary or "",
            "extracted_data": inv.extracted_data or {},
        }

        return NormalizedDocument(
            document_id=str(inv.id),
            document_type="sales_invoice",
            organization_id=str(organization_id),
            document_number=inv.invoice_number,
            document_date=inv.invoice_date,
            total_amount=float(inv.total_amount) if inv.total_amount else None,
            currency=inv.currency,
            counterparty_name=inv.vendor_name,
            tax_id=inv.vendor_vat_number,
            file_hash=getattr(inv, "file_hash", None),
            status=inv.status,
            approved_by_id=str(inv.approved_by_id) if inv.approved_by_id else None,
            cost_center=inv.cost_center,
            account_code=inv.account_code,
            budget_limit=float(getattr(inv, "budget_limit", 0)) or None,
            ocr_confidence=float(inv.ocr_confidence) if inv.ocr_confidence else None,
            is_handwritten=getattr(inv, "is_handwritten", False),
            typed_data=typed_data,
            org_context=self._get_org_context(organization_id),
        )


# Register with factory
DocumentNormalizerFactory.register("sales_invoice", InvoiceNormalizer)
