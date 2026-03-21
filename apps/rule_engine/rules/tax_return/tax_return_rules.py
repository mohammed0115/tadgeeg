"""TAX-M01, TAX-M02, TAX-M03, TAX-M08: Tax return audit rules"""
from decimal import Decimal
from apps.rule_engine.rules.base import AuditRuleBase, NormalizedDocument, RuleResult, EvidenceItem


class NetVATArithmeticRule(AuditRuleBase):
    rule_code = "TAX-M01"
    rule_name_en = "Net VAT Arithmetic Error"
    rule_name_ar = "خطأ في حساب صافي الضريبة المضافة"
    default_severity = "critical"
    rule_type = "validation"

    TOLERANCE = Decimal("1.00")

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return (doc.get("output_vat") is not None and
                doc.get("input_vat") is not None and
                doc.get("net_vat_payable") is not None)

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        output_vat = self.safe_decimal(doc.get("output_vat"))
        input_vat = self.safe_decimal(doc.get("input_vat"))
        net_declared = self.safe_decimal(doc.get("net_vat_payable"))

        calculated_net = output_vat - input_vat
        discrepancy = abs(calculated_net - net_declared)

        evidence = [EvidenceItem(
            evidence_type="calculation",
            field_name="net_vat_payable",
            field_name_ar="صافي الضريبة المستحقة",
            expected_value=float(calculated_net),
            actual_value=float(net_declared),
            description=f"Output VAT({output_vat}) - Input VAT({input_vat}) = {calculated_net}, declared {net_declared}",
            description_ar=f"ضريبة المخرجات({output_vat}) - ضريبة المدخلات({input_vat}) = {calculated_net}، المُعلن {net_declared}",
        )]

        if discrepancy > self.TOLERANCE:
            return self._fail(
                f"Net VAT arithmetic error: discrepancy of {discrepancy} SAR.",
                f"خطأ في حساب صافي الضريبة: الفارق {discrepancy} ريال.",
                evidence=evidence,
            )
        return self._pass(
            "Net VAT calculation is correct: Output VAT - Input VAT = Net VAT.",
            "حساب صافي الضريبة صحيح: ضريبة المخرجات - ضريبة المدخلات = الصافي.",
        )


class LateFilingRule(AuditRuleBase):
    rule_code = "TAX-M02"
    rule_name_en = "Late Filing Detection"
    rule_name_ar = "اكتشاف التأخر في تقديم الإقرار"
    default_severity = "high"
    rule_type = "compliance"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return doc.get("filing_date") is not None and doc.get("due_date") is not None

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        try:
            from datetime import datetime, date

            def parse_date(d):
                if isinstance(d, date):
                    return d
                return datetime.fromisoformat(str(d)).date()

            filing = parse_date(doc.get("filing_date"))
            due = parse_date(doc.get("due_date"))
            is_late = doc.get("is_late_filing", filing > due)

            if is_late:
                days_late = (filing - due).days if filing > due else 0
                return self._fail(
                    f"VAT return was filed {days_late} days late (filed: {filing}, due: {due}).",
                    f"تم تقديم الإقرار الضريبي متأخرًا بـ {days_late} يومًا (التقديم: {filing}، الموعد: {due}).",
                    evidence=[EvidenceItem(
                        evidence_type="comparison",
                        field_name="filing_date",
                        field_name_ar="تاريخ التقديم",
                        expected_value=str(due),
                        actual_value=str(filing),
                        description=f"Filed {days_late} days late.",
                        description_ar=f"تأخير {days_late} يوم.",
                    )]
                )
            return self._pass(
                f"VAT return filed on time (filed: {filing}, due: {due}).",
                f"تم تقديم الإقرار في الوقت المحدد (التقديم: {filing}، الموعد: {due}).",
            )
        except Exception as e:
            return self._error(e)


class ZATCAReferenceRule(AuditRuleBase):
    rule_code = "TAX-M08"
    rule_name_en = "No ZATCA Reference Number"
    rule_name_ar = "غياب رقم المرجعي من الزكاة والضريبة"
    default_severity = "high"
    rule_type = "compliance"

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        filing_status = doc.get("filing_status", "")
        zatca_ref = doc.get("zatca_reference", "")

        accepted_statuses = {"accepted", "ACCEPTED", "submitted", "SUBMITTED"}
        if filing_status not in accepted_statuses:
            return self._not_applicable(
                f"Filing status is '{filing_status}' — ZATCA reference check only applies to accepted returns."
            )

        if not zatca_ref or not str(zatca_ref).strip():
            return self._fail(
                "Accepted VAT return is missing a ZATCA reference number.",
                "الإقرار الضريبي المقبول لا يحتوي على رقم مرجعي من الزكاة والضريبة.",
                evidence=[EvidenceItem(
                    evidence_type="field_value",
                    field_name="zatca_reference",
                    field_name_ar="الرقم المرجعي للزكاة",
                    expected_value="Non-empty ZATCA reference",
                    actual_value=None,
                    description="ZATCA reference number is missing for accepted filing.",
                    description_ar="رقم المرجعي للزكاة مفقود في الإقرار المقبول.",
                )]
            )
        return self._pass(
            f"ZATCA reference '{zatca_ref}' is present.",
            f"الرقم المرجعي للزكاة '{zatca_ref}' موجود.",
        )
