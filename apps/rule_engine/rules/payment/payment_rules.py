"""
PMT-M01 – PMT-M10 — Payment Voucher audit rules.
"""
import re
from decimal import Decimal
from apps.rule_engine.rules.base import AuditRuleBase, NormalizedDocument, RuleResult, EvidenceItem


class PaymentNumberPresentRule(AuditRuleBase):
    """PMT-M01 — Payment voucher must have a unique payment number."""
    rule_code = "PMT-M01"
    rule_name_en = "Payment Number Missing"
    rule_name_ar = "رقم سند الصرف مفقود"
    default_severity = "high"
    rule_type = "validation"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return True

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        pmt_num = doc.document_number or doc.get("payment_number") or ""
        if not str(pmt_num).strip():
            return self._fail(
                "Payment number is missing. Every payment voucher requires a unique identifier.",
                "رقم سند الصرف مفقود. يتطلب كل سند صرف معرّفاً فريداً.",
                evidence=[EvidenceItem(
                    evidence_type="field_value",
                    field_name="payment_number",
                    field_name_ar="رقم سند الصرف",
                    expected_value="Non-empty payment number",
                    actual_value=None,
                    description="Payment number field is absent.",
                    description_ar="حقل رقم سند الصرف غائب.",
                )]
            )
        return self._pass(f"Payment number present: '{pmt_num}'.", f"رقم سند الصرف موجود: '{pmt_num}'.")


class PaymentDatePresentRule(AuditRuleBase):
    """PMT-M02 — Payment must have a valid payment date."""
    rule_code = "PMT-M02"
    rule_name_en = "Payment Date Missing"
    rule_name_ar = "تاريخ الدفع مفقود"
    default_severity = "high"
    rule_type = "validation"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return True

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        pmt_date = doc.document_date or doc.get("payment_date")
        if not pmt_date:
            return self._fail(
                "Payment date is missing. Payment date is mandatory for financial audit trail.",
                "تاريخ الدفع مفقود. تاريخ الدفع إلزامي لسجل التدقيق المالي.",
                evidence=[EvidenceItem(
                    evidence_type="field_value",
                    field_name="payment_date",
                    field_name_ar="تاريخ الدفع",
                    expected_value="Valid date",
                    actual_value=None,
                    description="Payment date field is absent.",
                    description_ar="حقل تاريخ الدفع غائب.",
                )]
            )
        return self._pass(f"Payment date present: '{pmt_date}'.", f"تاريخ الدفع موجود: '{pmt_date}'.")


class PaymentLinkedToInvoiceRule(AuditRuleBase):
    """PMT-M03 — Payment must reference a source invoice or purchase order."""
    rule_code = "PMT-M03"
    rule_name_en = "Payment Not Linked to Invoice or PO"
    rule_name_ar = "سند الصرف غير مرتبط بفاتورة أو أمر شراء"
    default_severity = "high"
    rule_type = "compliance"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return True

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        linked_inv = doc.get("linked_invoice_number") or doc.get("linked_invoice_id") or ""
        linked_po = doc.get("linked_po_number") or ""

        if not str(linked_inv).strip() and not str(linked_po).strip():
            return self._fail(
                "Payment is not linked to any invoice or purchase order. "
                "Unlinked payments cannot be verified against authorised obligations.",
                "سند الصرف غير مرتبط بأي فاتورة أو أمر شراء. "
                "لا يمكن التحقق من المدفوعات غير المرتبطة.",
                evidence=[EvidenceItem(
                    evidence_type="field_value",
                    field_name="linked_invoice_number",
                    field_name_ar="رقم الفاتورة المرتبطة",
                    expected_value="Invoice or PO reference",
                    actual_value=None,
                    description="No invoice or PO reference found on payment.",
                    description_ar="لم يتم العثور على مرجع فاتورة أو أمر شراء.",
                )]
            )
        ref = linked_inv or linked_po
        return self._pass(
            f"Payment linked to reference '{ref}'.",
            f"سند الصرف مرتبط بالمرجع '{ref}'.",
        )


class DuplicatePaymentRule(AuditRuleBase):
    """PMT-M04 — Detects duplicate payments to the same payee for the same amount."""
    rule_code = "PMT-M04"
    rule_name_en = "Duplicate Payment Detected"
    rule_name_ar = "دفعة مكررة"
    default_severity = "critical"
    rule_type = "anomaly"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return True

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        # Use pre-computed flag first
        if doc.get("is_duplicate"):
            return self._fail(
                "This payment is flagged as a duplicate of a previously processed payment "
                "(same payee, amount, and period).",
                "هذا السند مُصنَّف كمكرر لدفعة سبق معالجتها "
                "(نفس المستفيد والمبلغ والفترة).",
                evidence=[EvidenceItem(
                    evidence_type="reference",
                    field_name="is_duplicate",
                    field_name_ar="دفعة مكررة",
                    expected_value=False,
                    actual_value=True,
                    description="is_duplicate flag set by pre-processing pipeline.",
                    description_ar="علامة التكرار مُعيَّنة من خط معالجة البيانات.",
                )]
            )

        # Live DB check
        try:
            from apps.documents.typed_models import PaymentVoucher
            from datetime import timedelta, datetime, date as date_type

            payee = doc.counterparty_name or doc.get("payee_name") or ""
            amount = self.safe_decimal(doc.total_amount or 0)
            pmt_date_raw = doc.document_date or doc.get("payment_date")
            org_id = doc.organization_id

            if not payee or not amount or not pmt_date_raw:
                return self._skipped("Insufficient data for duplicate payment check.")

            try:
                pmt_date = pmt_date_raw if isinstance(pmt_date_raw, date_type) else datetime.fromisoformat(str(pmt_date_raw)).date()
            except (ValueError, TypeError):
                return self._skipped("Cannot parse payment date for duplicate check.")

            window_start = pmt_date - timedelta(days=30)
            duplicates = PaymentVoucher.objects.filter(
                organization_id=org_id,
                payee_name__iexact=payee,
                total_amount=amount,
                payment_date__gte=window_start,
                payment_date__lte=pmt_date,
            ).exclude(id=doc.document_id)

            if duplicates.exists():
                dup = duplicates.first()
                return self._fail(
                    f"Duplicate payment detected: same payee '{payee}', "
                    f"same amount {amount}, within 30-day window. "
                    f"Duplicate reference: {dup.payment_number}.",
                    f"تم اكتشاف دفعة مكررة: نفس المستفيد '{payee}'، "
                    f"نفس المبلغ {amount}، ضمن نافذة 30 يوم. "
                    f"مرجع المكرر: {dup.payment_number}.",
                    evidence=[EvidenceItem(
                        evidence_type="cross_document",
                        field_name="payment_number",
                        field_name_ar="رقم سند الصرف",
                        expected_value="Unique payment",
                        actual_value=dup.payment_number,
                        description=f"Duplicate found: {dup.payment_number} on {dup.payment_date}",
                        description_ar=f"مكرر موجود: {dup.payment_number} بتاريخ {dup.payment_date}",
                        linked_document_type="payment",
                        linked_document_id=str(dup.id),
                    )]
                )
        except Exception as e:
            return self._error(e)

        return self._pass("No duplicate payment detected.", "لا توجد دفعة مكررة.")


class PaymentApprovalRule(AuditRuleBase):
    """PMT-M05 — Payment must be approved before processing."""
    rule_code = "PMT-M05"
    rule_name_en = "Payment Missing Approval"
    rule_name_ar = "سند الصرف بدون موافقة"
    default_severity = "critical"
    rule_type = "compliance"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return True

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        approval_status = doc.get("approval_status") or ""
        approved_by = doc.approved_by_id or doc.get("approved_by_id") or ""

        if approval_status.lower() in ("pending", "draft") or not approved_by:
            return self._fail(
                "Payment has not been approved by an authorized signatory. "
                "All payments require documented approval before disbursement.",
                "لم تتم الموافقة على سند الصرف من قِبل مفوَّض. "
                "تتطلب جميع المدفوعات موافقة موثَّقة قبل الصرف.",
                evidence=[EvidenceItem(
                    evidence_type="field_value",
                    field_name="approval_status",
                    field_name_ar="حالة الموافقة",
                    expected_value="approved",
                    actual_value=approval_status or "pending",
                    description="Payment approval is missing or pending.",
                    description_ar="موافقة سند الصرف مفقودة أو معلقة.",
                )]
            )
        return self._pass(
            f"Payment approved — status: '{approval_status}'.",
            f"سند الصرف معتمد — الحالة: '{approval_status}'.",
        )


class PaymentExceedsThresholdRule(AuditRuleBase):
    """PMT-M06 — High-value payments must have additional authorization."""
    rule_code = "PMT-M06"
    rule_name_en = "High-Value Payment Without Dual Authorization"
    rule_name_ar = "دفعة ذات قيمة عالية بدون تفويض مزدوج"
    default_severity = "high"
    rule_type = "compliance"

    DEFAULT_THRESHOLD = 50000.0

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return doc.total_amount is not None

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        threshold = float(self.get_config("high_value_threshold", self.DEFAULT_THRESHOLD))
        amount = float(doc.total_amount or 0)

        # Use pre-computed flag
        if doc.get("exceeds_threshold") or amount > threshold:
            approval_status = doc.get("approval_status") or ""
            if approval_status.lower() != "approved":
                return self._fail(
                    f"Payment amount {amount:,.2f} exceeds threshold {threshold:,.0f} "
                    "and has not been fully approved.",
                    f"مبلغ الدفعة {amount:,.2f} يتجاوز الحد {threshold:,.0f} "
                    "ولم تتم الموافقة عليها بالكامل.",
                    evidence=[EvidenceItem(
                        evidence_type="field_value",
                        field_name="total_amount",
                        field_name_ar="مبلغ الدفعة",
                        expected_value=f"Approved when > {threshold:,.0f}",
                        actual_value=amount,
                        description=f"Amount {amount:,.2f} exceeds threshold {threshold:,.0f}.",
                        description_ar=f"المبلغ {amount:,.2f} يتجاوز الحد {threshold:,.0f}.",
                    )]
                )
            return self._warning(
                f"High-value payment ({amount:,.2f}) approved — verify dual authorization in policy.",
                f"دفعة ذات قيمة عالية ({amount:,.2f}) معتمدة — تحقق من التفويض المزدوج وفق السياسة.",
            )
        return self._pass(
            f"Payment amount {amount:,.2f} is within standard threshold {threshold:,.0f}.",
            f"مبلغ الدفعة {amount:,.2f} ضمن الحد المعياري {threshold:,.0f}.",
        )


class PaymentIBANFormatRule(AuditRuleBase):
    """PMT-M07 — Payee IBAN must conform to Saudi IBAN format."""
    rule_code = "PMT-M07"
    rule_name_en = "Payee IBAN Format Invalid"
    rule_name_ar = "صيغة IBAN المستفيد غير صحيحة"
    default_severity = "high"
    rule_type = "compliance"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return bool(doc.get("payee_iban"))

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        iban = str(doc.get("payee_iban", "")).strip().replace(" ", "")
        is_valid = (
            len(iban) == 24 and
            iban[:2].upper() == "SA" and
            iban[2:4].isdigit() and
            iban[4:].isalnum()
        )
        if not is_valid:
            return self._fail(
                f"Payee IBAN '{iban}' does not match Saudi IBAN format (SA + 22 alphanumeric chars).",
                f"IBAN المستفيد '{iban}' لا يتوافق مع صيغة الآيبان السعودي (SA + 22 حرفاً).",
                evidence=[EvidenceItem(
                    evidence_type="field_value",
                    field_name="payee_iban",
                    field_name_ar="IBAN المستفيد",
                    expected_value="SA + 22 alphanumeric (24 total)",
                    actual_value=iban,
                    description=f"IBAN format invalid. Length: {len(iban)}.",
                    description_ar=f"صيغة IBAN غير صحيحة. الطول: {len(iban)}.",
                )]
            )
        return self._pass(f"Payee IBAN '{iban}' is valid.", f"IBAN المستفيد '{iban}' صحيح.")


class AdvancePaymentClearanceRule(AuditRuleBase):
    """PMT-M08 — Advance payments must be cleared within the policy period."""
    rule_code = "PMT-M08"
    rule_name_en = "Advance Payment Not Cleared"
    rule_name_ar = "الدفعة المقدمة لم يتم تسويتها"
    default_severity = "high"
    rule_type = "compliance"

    DEFAULT_CLEARANCE_DAYS = 90

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return doc.get("is_advance_payment") is not None

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        if not doc.get("is_advance_payment"):
            return self._not_applicable(
                "This is not an advance payment.",
                "هذه ليست دفعة مقدمة.",
            )

        clearance_days = int(self.get_config("clearance_days", self.DEFAULT_CLEARANCE_DAYS))
        advance_cleared = doc.get("advance_cleared", False)
        days_since = doc.get("days_since_invoice", 0) or 0

        if not advance_cleared and days_since > clearance_days:
            return self._fail(
                f"Advance payment has not been cleared after {days_since} days "
                f"(policy limit: {clearance_days} days).",
                f"الدفعة المقدمة لم يتم تسويتها بعد {days_since} يوماً "
                f"(الحد المسموح: {clearance_days} يوماً).",
                evidence=[EvidenceItem(
                    evidence_type="comparison",
                    field_name="advance_cleared",
                    field_name_ar="تسوية الدفعة المقدمة",
                    expected_value=f"Cleared within {clearance_days} days",
                    actual_value=f"Uncleared after {days_since} days",
                    description=f"Advance payment outstanding for {days_since} days.",
                    description_ar=f"الدفعة المقدمة متأخرة منذ {days_since} يوماً.",
                )]
            )
        if not advance_cleared:
            return self._warning(
                f"Advance payment not yet cleared ({days_since}/{clearance_days} days).",
                f"الدفعة المقدمة لم تُسوَّ بعد ({days_since}/{clearance_days} يوماً).",
            )
        return self._pass(
            "Advance payment has been cleared.",
            "تمت تسوية الدفعة المقدمة.",
        )


class LatePaymentRule(AuditRuleBase):
    """PMT-M09 — Payments significantly overdue may indicate cash flow or control issues."""
    rule_code = "PMT-M09"
    rule_name_en = "Late Payment Detected"
    rule_name_ar = "تأخر في سداد الدفعة"
    default_severity = "medium"
    rule_type = "compliance"

    WARN_DAYS = 30
    FAIL_DAYS = 90

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return doc.get("days_since_invoice") is not None

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        warn_days = int(self.get_config("warn_days", self.WARN_DAYS))
        fail_days = int(self.get_config("fail_days", self.FAIL_DAYS))
        days = int(doc.get("days_since_invoice") or 0)

        evidence = [EvidenceItem(
            evidence_type="comparison",
            field_name="days_since_invoice",
            field_name_ar="الأيام منذ الفاتورة",
            expected_value=f"≤ {warn_days} days",
            actual_value=f"{days} days",
            description=f"Payment made {days} days after invoice date.",
            description_ar=f"تم الدفع بعد {days} يوماً من تاريخ الفاتورة.",
        )]

        if days > fail_days:
            return self._fail(
                f"Payment is {days} days overdue (critical threshold: {fail_days} days). "
                "Severe late payment — investigate cash flow controls.",
                f"الدفعة متأخرة {days} يوماً (الحد الحرج: {fail_days} يوماً). "
                "تأخر حاد — تحقق من ضوابط التدفق النقدي.",
                evidence=evidence,
            )
        if days > warn_days:
            return self._warning(
                f"Payment is {days} days overdue (warning threshold: {warn_days} days).",
                f"الدفعة متأخرة {days} يوماً (حد التحذير: {warn_days} يوماً).",
                evidence=evidence,
            )
        return self._pass(
            f"Payment made within acceptable timeframe ({days} days).",
            f"تم الدفع ضمن الإطار الزمني المقبول ({days} يوماً).",
        )


class PaymentAmountMatchRule(AuditRuleBase):
    """PMT-M10 — Payment amount must match the linked invoice amount within tolerance."""
    rule_code = "PMT-M10"
    rule_name_en = "Payment Amount Does Not Match Invoice"
    rule_name_ar = "مبلغ الدفعة لا يطابق الفاتورة"
    default_severity = "critical"
    rule_type = "reconciliation"

    DEFAULT_TOLERANCE_PCT = Decimal("2.0")

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return (doc.total_amount is not None and
                (doc.get("linked_invoice_id") or doc.get("linked_invoice_number")))

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        tolerance_pct = self.safe_decimal(self.get_config("tolerance_pct", "2.0"))
        pmt_amount = self.safe_decimal(doc.total_amount or 0)

        try:
            from apps.invoices.models import Invoice
            linked_id = doc.get("linked_invoice_id")
            linked_num = doc.get("linked_invoice_number")

            inv = None
            if linked_id:
                inv = Invoice.objects.filter(id=linked_id).first()
            if not inv and linked_num:
                inv = Invoice.objects.filter(
                    organization_id=doc.organization_id,
                    invoice_number=linked_num,
                ).first()

            if not inv:
                return self._skipped("Linked invoice not found in system.")

            inv_amount = self.safe_decimal(inv.total_amount or 0)
            if inv_amount == 0:
                return self._skipped("Invoice amount is zero — cannot compare.")

            variance_pct = abs(pmt_amount - inv_amount) / inv_amount * 100
            evidence = [EvidenceItem(
                evidence_type="comparison",
                field_name="total_amount",
                field_name_ar="مبلغ الدفعة",
                expected_value=float(inv_amount),
                actual_value=float(pmt_amount),
                description=f"Payment: {pmt_amount}, Invoice: {inv_amount}, Variance: {variance_pct:.2f}%",
                description_ar=f"الدفعة: {pmt_amount}، الفاتورة: {inv_amount}، الفارق: {variance_pct:.2f}%",
                linked_document_type="sales_invoice",
                linked_document_id=str(inv.id),
            )]

            if variance_pct > tolerance_pct:
                return self._fail(
                    f"Payment amount ({pmt_amount}) differs from invoice ({inv_amount}) "
                    f"by {variance_pct:.2f}%.",
                    f"مبلغ الدفعة ({pmt_amount}) يختلف عن الفاتورة ({inv_amount}) "
                    f"بنسبة {variance_pct:.2f}%.",
                    evidence=evidence,
                )
            return self._pass(
                f"Payment matches invoice within tolerance ({variance_pct:.2f}%).",
                f"الدفعة تطابق الفاتورة ضمن حد التفاوت ({variance_pct:.2f}%).",
            )
        except Exception as e:
            return self._error(e)
