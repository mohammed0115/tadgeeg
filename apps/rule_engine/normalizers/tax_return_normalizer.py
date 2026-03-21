import logging
from apps.rule_engine.rules.base import NormalizedDocument
from apps.rule_engine.normalizers import BaseNormalizer, DocumentNormalizerFactory

logger = logging.getLogger("rule_engine")


class TaxReturnNormalizer(BaseNormalizer):
    document_type = "tax_return"

    def normalize(self, document_id: str, organization_id: str) -> NormalizedDocument:
        from apps.documents.typed_models import VATReturn
        try:
            vat = VATReturn.objects.get(id=document_id)
        except VATReturn.DoesNotExist:
            logger.warning(f"VATReturn {document_id} not found")
            return NormalizedDocument(
                document_id=str(document_id),
                document_type="tax_return",
                organization_id=str(organization_id),
            )

        typed_data = {
            "taxpayer_name": vat.taxpayer_name,
            "vat_number": vat.vat_number,
            "cr_number": vat.cr_number,
            "period_from": str(vat.period_from) if vat.period_from else None,
            "period_to": str(vat.period_to) if vat.period_to else None,
            "filing_date": str(vat.filing_date) if vat.filing_date else None,
            "due_date": str(vat.due_date) if vat.due_date else None,
            "zatca_reference": vat.zatca_reference,
            "filing_status": vat.filing_status,
            # Box values
            "standard_rated_sales": float(vat.standard_rated_sales) if vat.standard_rated_sales is not None else None,
            "zero_rated_sales": float(vat.zero_rated_sales) if vat.zero_rated_sales is not None else None,
            "exempt_sales": float(vat.exempt_sales) if vat.exempt_sales is not None else None,
            "total_sales": float(vat.total_sales) if vat.total_sales is not None else None,
            "output_vat": float(vat.output_vat) if vat.output_vat is not None else None,
            "standard_rated_purchases": float(vat.standard_rated_purchases) if vat.standard_rated_purchases is not None else None,
            "input_vat": float(vat.input_vat) if vat.input_vat is not None else None,
            "net_vat_payable": float(vat.net_vat_payable) if vat.net_vat_payable is not None else None,
            "vat_paid": float(vat.vat_paid) if vat.vat_paid is not None else None,
            # Calculated
            "calculated_output_vat": float(vat.calculated_output_vat) if vat.calculated_output_vat is not None else None,
            "calculated_input_vat": float(vat.calculated_input_vat) if vat.calculated_input_vat is not None else None,
            "calculated_net": float(vat.calculated_net) if vat.calculated_net is not None else None,
            "is_late_filing": vat.is_late_filing,
        }

        return NormalizedDocument(
            document_id=str(document_id),
            document_type="tax_return",
            organization_id=str(organization_id),
            document_number=vat.zatca_reference,
            document_date=vat.filing_date,
            total_amount=float(vat.net_vat_payable) if vat.net_vat_payable is not None else None,
            counterparty_name=vat.taxpayer_name,
            tax_id=vat.vat_number,
            typed_data=typed_data,
            org_context=self._get_org_context(organization_id),
        )


DocumentNormalizerFactory.register("tax_return", TaxReturnNormalizer)
