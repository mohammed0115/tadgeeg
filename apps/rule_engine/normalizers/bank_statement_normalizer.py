import logging
from apps.rule_engine.rules.base import NormalizedDocument
from apps.rule_engine.normalizers import BaseNormalizer, DocumentNormalizerFactory

logger = logging.getLogger("rule_engine")


class BankStatementNormalizer(BaseNormalizer):
    document_type = "bank_statement"

    def normalize(self, document_id: str, organization_id: str) -> NormalizedDocument:
        from apps.documents.typed_models import BankStatement
        try:
            stmt = BankStatement.objects.get(id=document_id)
        except BankStatement.DoesNotExist:
            logger.warning(f"BankStatement {document_id} not found")
            return NormalizedDocument(
                document_id=str(document_id),
                document_type="bank_statement",
                organization_id=str(organization_id),
            )

        transactions = stmt.transactions or []
        typed_data = {
            "bank_name": stmt.bank_name,
            "account_number": stmt.account_number,
            "account_name": stmt.account_name,
            "iban": stmt.iban,
            "opening_balance": float(stmt.opening_balance) if stmt.opening_balance is not None else None,
            "closing_balance": float(stmt.closing_balance) if stmt.closing_balance is not None else None,
            "total_credits": float(stmt.total_credits) if stmt.total_credits is not None else None,
            "total_debits": float(stmt.total_debits) if stmt.total_debits is not None else None,
            "calculated_closing": float(stmt.calculated_closing) if stmt.calculated_closing is not None else None,
            "balance_matches": stmt.balance_matches,
            "transaction_count": stmt.transaction_count,
            "transactions": transactions,
            # Anomaly flags
            "large_tx_count": stmt.large_tx_count,
            "round_amount_count": stmt.round_amount_count,
            "benford_deviation": float(stmt.benford_deviation) if stmt.benford_deviation is not None else None,
            "duplicate_tx_count": stmt.duplicate_tx_count,
            "weekend_tx_count": stmt.weekend_tx_count,
            "late_night_tx_count": stmt.late_night_tx_count,
        }

        return NormalizedDocument(
            document_id=str(document_id),
            document_type="bank_statement",
            organization_id=str(organization_id),
            document_number=stmt.account_number,
            total_amount=float(stmt.closing_balance) if stmt.closing_balance is not None else None,
            currency=stmt.currency,
            counterparty_name=stmt.bank_name,
            typed_data=typed_data,
            org_context=self._get_org_context(organization_id),
        )


DocumentNormalizerFactory.register("bank_statement", BankStatementNormalizer)
