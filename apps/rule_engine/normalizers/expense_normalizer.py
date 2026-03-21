import logging
from apps.rule_engine.rules.base import NormalizedDocument
from apps.rule_engine.normalizers import BaseNormalizer, DocumentNormalizerFactory

logger = logging.getLogger("rule_engine")


class ExpenseNormalizer(BaseNormalizer):
    document_type = "expense"

    def normalize(self, document_id: str, organization_id: str) -> NormalizedDocument:
        from apps.documents.typed_models import ExpenseReport
        try:
            exp = ExpenseReport.objects.get(id=document_id)
        except ExpenseReport.DoesNotExist:
            logger.warning(f"ExpenseReport {document_id} not found")
            return NormalizedDocument(
                document_id=str(document_id),
                document_type="expense",
                organization_id=str(organization_id),
            )

        typed_data = {
            "report_number": exp.report_number,
            "employee_name": exp.employee_name,
            "employee_id": exp.employee_id,
            "department": exp.department,
            "report_period_from": str(exp.report_period_from) if exp.report_period_from else None,
            "report_period_to": str(exp.report_period_to) if exp.report_period_to else None,
            "submitted_date": str(exp.submitted_date) if exp.submitted_date else None,
            "purpose": exp.purpose,
            "total_claimed": float(exp.total_claimed) if exp.total_claimed is not None else None,
            "total_approved": float(exp.total_approved) if exp.total_approved is not None else None,
            "total_rejected": float(exp.total_rejected) if exp.total_rejected is not None else None,
            "vat_included": exp.vat_included,
            "expense_lines": exp.expense_lines or [],
            # Flags
            "missing_receipts_count": exp.missing_receipts_count,
            "duplicate_claims": exp.duplicate_claims or [],
            "over_policy_limit_count": exp.over_policy_limit_count,
            "weekend_expense_count": exp.weekend_expense_count,
            "split_transaction_flags": exp.split_transaction_flags or [],
        }

        return NormalizedDocument(
            document_id=str(document_id),
            document_type="expense",
            organization_id=str(organization_id),
            document_number=exp.report_number,
            document_date=exp.submitted_date,
            total_amount=float(exp.total_claimed) if exp.total_claimed is not None else None,
            currency=exp.currency,
            counterparty_name=exp.employee_name,
            typed_data=typed_data,
            org_context=self._get_org_context(organization_id),
        )


DocumentNormalizerFactory.register("expense", ExpenseNormalizer)
