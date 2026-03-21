import logging
from apps.rule_engine.rules.base import NormalizedDocument
from apps.rule_engine.normalizers import BaseNormalizer, DocumentNormalizerFactory

logger = logging.getLogger("rule_engine")


class PayrollNormalizer(BaseNormalizer):
    document_type = "payroll"

    def normalize(self, document_id: str, organization_id: str) -> NormalizedDocument:
        from apps.documents.typed_models import PayrollSheet
        try:
            payroll = PayrollSheet.objects.get(id=document_id)
        except PayrollSheet.DoesNotExist:
            logger.warning(f"PayrollSheet {document_id} not found")
            return NormalizedDocument(
                document_id=str(document_id),
                document_type="payroll",
                organization_id=str(organization_id),
            )

        employees = payroll.employees or []
        typed_data = {
            "company_name": payroll.company_name,
            "department": payroll.department,
            "payroll_period_from": str(payroll.payroll_period_from) if payroll.payroll_period_from else None,
            "payroll_period_to": str(payroll.payroll_period_to) if payroll.payroll_period_to else None,
            "payment_date": str(payroll.payment_date) if payroll.payment_date else None,
            "employee_count": payroll.employee_count,
            "total_gross_salary": float(payroll.total_gross_salary) if payroll.total_gross_salary is not None else None,
            "total_allowances": float(payroll.total_allowances) if payroll.total_allowances is not None else None,
            "total_deductions": float(payroll.total_deductions) if payroll.total_deductions is not None else None,
            "total_gosi": float(payroll.total_gosi) if payroll.total_gosi is not None else None,
            "total_net_salary": float(payroll.total_net_salary) if payroll.total_net_salary is not None else None,
            "employees": employees,
            # Flags
            "duplicate_employee_ids": payroll.duplicate_employee_ids or [],
            "ghost_employee_flags": payroll.ghost_employee_flags or [],
            "salary_spike_flags": payroll.salary_spike_flags or [],
            "calculation_errors": payroll.calculation_errors or [],
            "missing_gosi_count": payroll.missing_gosi_count,
        }

        return NormalizedDocument(
            document_id=str(document_id),
            document_type="payroll",
            organization_id=str(organization_id),
            counterparty_name=payroll.company_name,
            total_amount=float(payroll.total_net_salary) if payroll.total_net_salary is not None else None,
            currency=payroll.currency,
            typed_data=typed_data,
            org_context=self._get_org_context(organization_id),
        )


DocumentNormalizerFactory.register("payroll", PayrollNormalizer)
