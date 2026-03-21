"""CDR-01: Invoice–PO Amount Mismatch"""
from decimal import Decimal
from apps.rule_engine.rules.base import AuditRuleBase, NormalizedDocument, RuleResult, EvidenceItem

class InvoicePOMatchRule(AuditRuleBase):
    rule_code = "CDR-01"
    rule_name_en = "Invoice–PO Amount Mismatch"
    rule_name_ar = "تعارض مبلغ الفاتورة مع أمر الشراء"
    default_severity = "critical"
    rule_type = "reconciliation"

    TOLERANCE_PCT = 5.0

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        from apps.rule_engine.models import CrossDocumentLink
        return CrossDocumentLink.objects.filter(
            organization_id=doc.organization_id,
            link_type="po_to_invoice",
            target_document_id=doc.document_id,
        ).exists()

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        try:
            from apps.rule_engine.models import CrossDocumentLink
            tolerance_pct = float(self.get_config("amount_tolerance_pct", self.TOLERANCE_PCT))

            links = CrossDocumentLink.objects.filter(
                organization_id=doc.organization_id,
                link_type="po_to_invoice",
                target_document_id=doc.document_id,
            )

            inv_amount = float(doc.total_amount or 0)
            failures = []
            evidence = []

            for link in links:
                po_amount = float(link.match_details.get("po_amount", 0) or 0)
                if po_amount == 0:
                    continue

                discrepancy_pct = abs(inv_amount - po_amount) / max(po_amount, 1) * 100

                evidence.append(EvidenceItem(
                    evidence_type="cross_document",
                    field_name="total_amount",
                    field_name_ar="المبلغ الإجمالي",
                    expected_value=po_amount,
                    actual_value=inv_amount,
                    description=f"PO amount: {po_amount:,.2f}, Invoice amount: {inv_amount:,.2f}, Discrepancy: {discrepancy_pct:.1f}%",
                    description_ar=f"مبلغ الأمر: {po_amount:,.2f}، مبلغ الفاتورة: {inv_amount:,.2f}، الفارق: {discrepancy_pct:.1f}%",
                    linked_document_type="purchase_order",
                    linked_document_id=str(link.source_document_id),
                ))

                if discrepancy_pct > tolerance_pct:
                    failures.append(f"PO {link.source_document_id}: {discrepancy_pct:.1f}% discrepancy")

            if failures:
                return self._fail(
                    f"Invoice–PO amount mismatch: {'; '.join(failures)}",
                    f"تعارض مبلغ الفاتورة مع أمر الشراء: الفارق يتجاوز {tolerance_pct}%.",
                    evidence=evidence,
                )
            return self._pass(
                "Invoice amount matches linked PO within tolerance.",
                "مبلغ الفاتورة يتطابق مع أمر الشراء ضمن حد التفاوت.",
                evidence=evidence,
            )
        except Exception as e:
            return self._error(e)


class PayrollBankReconciliationRule(AuditRuleBase):
    rule_code = "CDR-03"
    rule_name_en = "Payroll–Bank Transfer Reconciliation"
    rule_name_ar = "تسوية إجمالي الرواتب مع التحويل البنكي"
    default_severity = "critical"
    rule_type = "reconciliation"

    TOLERANCE = Decimal("1.00")

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        from apps.rule_engine.models import CrossDocumentLink
        return CrossDocumentLink.objects.filter(
            organization_id=doc.organization_id,
            link_type="payroll_to_bank",
            source_document_id=doc.document_id,
        ).exists()

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        try:
            from apps.rule_engine.models import CrossDocumentLink
            tolerance = self.safe_decimal(self.get_config("tolerance", "1.00"))

            links = CrossDocumentLink.objects.filter(
                organization_id=doc.organization_id,
                link_type="payroll_to_bank",
                source_document_id=doc.document_id,
            )

            payroll_total = self.safe_decimal(doc.get("total_net_salary", 0))
            evidence = []
            failures = []

            for link in links:
                bank_amount = self.safe_decimal(link.match_details.get("bank_transfer_amount", 0))
                discrepancy = abs(payroll_total - bank_amount)

                evidence.append(EvidenceItem(
                    evidence_type="cross_document",
                    field_name="total_net_salary",
                    field_name_ar="إجمالي صافي الرواتب",
                    expected_value=float(bank_amount),
                    actual_value=float(payroll_total),
                    description=f"Payroll total: {payroll_total}, Bank transfer: {bank_amount}, Discrepancy: {discrepancy}",
                    description_ar=f"إجمالي الرواتب: {payroll_total}، التحويل البنكي: {bank_amount}، الفارق: {discrepancy}",
                    linked_document_type="bank_statement",
                    linked_document_id=str(link.target_document_id),
                ))

                if discrepancy > tolerance:
                    failures.append(f"Discrepancy: {discrepancy}")

            if failures:
                return self._fail(
                    f"Payroll total does not match bank transfer: {'; '.join(failures)}",
                    f"إجمالي الرواتب لا يتطابق مع التحويل البنكي: {'; '.join(failures)}",
                    evidence=evidence,
                )
            return self._pass(
                "Payroll total matches bank transfer amount.",
                "إجمالي الرواتب يطابق مبلغ التحويل البنكي.",
                evidence=evidence,
            )
        except Exception as e:
            return self._error(e)
