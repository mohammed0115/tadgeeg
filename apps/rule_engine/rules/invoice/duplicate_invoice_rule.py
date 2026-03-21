"""DUP-01, DUP-02, DUP-03: Duplicate invoice detection"""
import logging
from apps.rule_engine.rules.base import AuditRuleBase, NormalizedDocument, RuleResult, EvidenceItem

logger = logging.getLogger("rule_engine")


class DuplicateDocumentNumberRule(AuditRuleBase):
    rule_code = "DUP-01"
    rule_name_en = "Duplicate Document Number"
    rule_name_ar = "تكرار رقم المستند"
    default_severity = "high"
    rule_type = "validation"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return bool(doc.document_number)

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        try:
            from apps.invoices.models import Invoice
            dup = Invoice.objects.filter(
                organization_id=doc.organization_id,
                invoice_number=doc.document_number,
            ).exclude(id=doc.document_id).first()

            if dup:
                return self._fail(
                    f"Document number '{doc.document_number}' already exists.",
                    f"رقم المستند '{doc.document_number}' موجود مسبقًا.",
                    evidence=[EvidenceItem(
                        evidence_type="comparison",
                        field_name="document_number",
                        field_name_ar="رقم المستند",
                        expected_value="Unique",
                        actual_value=doc.document_number,
                        description=f"Duplicate found: document {dup.id}",
                        description_ar=f"تكرار موجود: المستند {dup.id}",
                    )]
                )
            return self._pass(
                f"Document number '{doc.document_number}' is unique.",
                f"رقم المستند '{doc.document_number}' فريد.",
            )
        except Exception as e:
            return self._error(e)


class AmountAnomalyRule(AuditRuleBase):
    rule_code = "ANO-01"
    rule_name_en = "Amount Unusually High"
    rule_name_ar = "مبلغ مرتفع بشكل غير معتاد"
    default_severity = "medium"
    rule_type = "anomaly"

    DEFAULT_MULTIPLIER = 3.0
    DEFAULT_ABSOLUTE_THRESHOLD = 500000.0  # SAR 500k

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return doc.total_amount is not None and doc.total_amount > 0

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        try:
            amount = float(doc.total_amount)
            multiplier = float(self.get_config("anomaly_multiplier", self.DEFAULT_MULTIPLIER))
            abs_threshold = float(self.get_config("absolute_threshold", self.DEFAULT_ABSOLUTE_THRESHOLD))

            # Check absolute threshold
            if amount > abs_threshold:
                return self._warning(
                    f"Amount {amount:,.2f} {doc.currency or 'SAR'} exceeds high-value threshold.",
                    f"المبلغ {amount:,.2f} {doc.currency or 'ريال'} يتجاوز الحد العالي للقيمة.",
                    evidence=[EvidenceItem(
                        evidence_type="statistical",
                        field_name="total_amount",
                        field_name_ar="المبلغ الإجمالي",
                        expected_value=f"< {abs_threshold:,.2f}",
                        actual_value=amount,
                        description=f"Amount {amount:,.2f} exceeds threshold {abs_threshold:,.2f}.",
                        description_ar=f"المبلغ {amount:,.2f} يتجاوز الحد {abs_threshold:,.2f}.",
                    )]
                )

            # Compare to vendor/counterparty average
            if doc.document_type == "sales_invoice" and doc.counterparty_name:
                from apps.invoices.models import Invoice
                from django.db.models import Avg
                stats = Invoice.objects.filter(
                    organization_id=doc.organization_id,
                    vendor_name=doc.counterparty_name,
                ).exclude(id=doc.document_id).aggregate(avg=Avg("total_amount"))
                avg = stats.get("avg")
                if avg and float(avg) > 0 and amount > float(avg) * multiplier:
                    return self._warning(
                        f"Amount {amount:,.2f} is {amount/float(avg):.1f}× the vendor average ({float(avg):,.2f}).",
                        f"المبلغ {amount:,.2f} يعادل {amount/float(avg):.1f} مرة متوسط هذا المورد ({float(avg):,.2f}).",
                        evidence=[EvidenceItem(
                            evidence_type="statistical",
                            field_name="total_amount",
                            field_name_ar="المبلغ الإجمالي",
                            expected_value=f"< {float(avg) * multiplier:,.2f}",
                            actual_value=amount,
                            description=f"Amount {amount:,.2f} exceeds {multiplier}× vendor avg {float(avg):,.2f}.",
                            description_ar=f"المبلغ {amount:,.2f} يتجاوز {multiplier} أضعاف متوسط المورد {float(avg):,.2f}.",
                        )]
                    )

            return self._pass(
                f"Amount {amount:,.2f} {doc.currency or 'SAR'} is within normal range.",
                f"المبلغ {amount:,.2f} {doc.currency or 'ريال'} ضمن النطاق الطبيعي.",
            )
        except Exception as e:
            return self._error(e)
