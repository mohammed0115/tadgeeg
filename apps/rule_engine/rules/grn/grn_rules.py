"""
GRN-M01 – GRN-M10 — Goods Receipt Note audit rules.
"""
from decimal import Decimal
from apps.rule_engine.rules.base import AuditRuleBase, NormalizedDocument, RuleResult, EvidenceItem


class GRNNumberPresentRule(AuditRuleBase):
    """GRN-M01 — GRN must have a unique document number."""
    rule_code = "GRN-M01"
    rule_name_en = "GRN Number Missing"
    rule_name_ar = "رقم إشعار الاستلام مفقود"
    default_severity = "high"
    rule_type = "validation"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return True

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        grn_num = doc.document_number or doc.get("grn_number") or ""
        if not str(grn_num).strip():
            return self._fail(
                "GRN number is missing. Every goods receipt must have a unique identifier.",
                "رقم إشعار الاستلام مفقود. يجب أن يكون لكل استلام معرّف فريد.",
                evidence=[EvidenceItem(
                    evidence_type="field_value",
                    field_name="grn_number",
                    field_name_ar="رقم إشعار الاستلام",
                    expected_value="Non-empty GRN number",
                    actual_value=None,
                    description="GRN number field is absent or empty.",
                    description_ar="حقل رقم إشعار الاستلام غائب أو فارغ.",
                )]
            )
        return self._pass(f"GRN number present: '{grn_num}'.", f"رقم إشعار الاستلام موجود: '{grn_num}'.")


class GRNDatePresentRule(AuditRuleBase):
    """GRN-M02 — GRN must have a receipt date."""
    rule_code = "GRN-M02"
    rule_name_en = "GRN Date Missing"
    rule_name_ar = "تاريخ إشعار الاستلام مفقود"
    default_severity = "high"
    rule_type = "validation"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return True

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        grn_date = doc.document_date or doc.get("grn_date")
        if not grn_date:
            return self._fail(
                "GRN date is missing. Receipt date is mandatory for audit trail.",
                "تاريخ إشعار الاستلام مفقود. تاريخ الاستلام إلزامي لسجل التدقيق.",
                evidence=[EvidenceItem(
                    evidence_type="field_value",
                    field_name="grn_date",
                    field_name_ar="تاريخ الاستلام",
                    expected_value="Valid date",
                    actual_value=None,
                    description="GRN date field is absent.",
                    description_ar="حقل تاريخ الاستلام غائب.",
                )]
            )
        return self._pass(f"GRN date present: '{grn_date}'.", f"تاريخ الاستلام موجود: '{grn_date}'.")


class GRNLinkedToPORule(AuditRuleBase):
    """GRN-M03 — GRN must be linked to a Purchase Order."""
    rule_code = "GRN-M03"
    rule_name_en = "GRN Not Linked to Purchase Order"
    rule_name_ar = "إشعار الاستلام غير مرتبط بأمر شراء"
    default_severity = "high"
    rule_type = "compliance"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return True

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        po_number = doc.get("po_number") or doc.get("po_id") or ""
        if not str(po_number).strip():
            return self._fail(
                "GRN is not linked to any Purchase Order. "
                "Unauthorized goods receipts create procurement fraud risk.",
                "إشعار الاستلام غير مرتبط بأي أمر شراء. "
                "استلام البضاعة بدون أمر شراء يُشكّل خطر احتيال في المشتريات.",
                evidence=[EvidenceItem(
                    evidence_type="field_value",
                    field_name="po_number",
                    field_name_ar="رقم أمر الشراء",
                    expected_value="Valid PO number",
                    actual_value=None,
                    description="No PO number or PO ID linked to this GRN.",
                    description_ar="لا يوجد رقم أمر شراء أو معرّف أمر شراء مرتبط بهذا الإشعار.",
                )]
            )
        return self._pass(
            f"GRN linked to PO '{po_number}'.",
            f"إشعار الاستلام مرتبط بأمر الشراء '{po_number}'.",
        )


class GRNQuantityMatchRule(AuditRuleBase):
    """GRN-M04 — Received quantity must match ordered quantity within tolerance."""
    rule_code = "GRN-M04"
    rule_name_en = "GRN Quantity vs PO Quantity Mismatch"
    rule_name_ar = "عدم تطابق كميات الاستلام مع أمر الشراء"
    default_severity = "critical"
    rule_type = "reconciliation"

    DEFAULT_TOLERANCE_PCT = Decimal("10.0")

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return (doc.get("total_ordered_qty") is not None and
                doc.get("total_received_qty") is not None)

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        tolerance_pct = self.safe_decimal(self.get_config("tolerance_pct", "10.0"))
        ordered = self.safe_decimal(doc.get("total_ordered_qty", 0))
        received = self.safe_decimal(doc.get("total_received_qty", 0))

        if ordered == 0:
            return self._skipped("Ordered quantity is zero — cannot compute variance.")

        variance_pct = abs(received - ordered) / ordered * 100
        evidence = [EvidenceItem(
            evidence_type="calculation",
            field_name="total_received_qty",
            field_name_ar="الكمية المستلمة",
            expected_value=float(ordered),
            actual_value=float(received),
            description=f"Ordered: {ordered}, Received: {received}, Variance: {variance_pct:.1f}%",
            description_ar=f"الكمية المطلوبة: {ordered}، المستلمة: {received}، الفارق: {variance_pct:.1f}%",
        )]

        if variance_pct > tolerance_pct:
            return self._fail(
                f"Quantity variance of {variance_pct:.1f}% exceeds tolerance ({tolerance_pct}%). "
                f"Ordered: {ordered}, Received: {received}.",
                f"فارق الكمية {variance_pct:.1f}% يتجاوز حد التفاوت ({tolerance_pct}%). "
                f"المطلوب: {ordered}، المستلم: {received}.",
                evidence=evidence,
            )
        return self._pass(
            f"Quantities match within tolerance. Ordered: {ordered}, Received: {received} ({variance_pct:.1f}% variance).",
            f"الكميات متطابقة ضمن حد التفاوت. المطلوب: {ordered}، المستلم: {received} (فارق {variance_pct:.1f}%).",
        )


class GRNRejectionRateRule(AuditRuleBase):
    """GRN-M05 — Goods rejection rate must not exceed policy threshold."""
    rule_code = "GRN-M05"
    rule_name_en = "High Goods Rejection Rate"
    rule_name_ar = "معدل رفض البضاعة مرتفع"
    default_severity = "high"
    rule_type = "anomaly"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return doc.get("rejection_rate_pct") is not None or (
            doc.get("total_rejected_qty") is not None and
            doc.get("total_ordered_qty") is not None
        )

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        warn_threshold = float(self.get_config("warn_threshold_pct", "20.0"))
        fail_threshold = float(self.get_config("fail_threshold_pct", "50.0"))

        rejection_pct = doc.get("rejection_rate_pct")
        if rejection_pct is None:
            ordered = self.safe_decimal(doc.get("total_ordered_qty", 0))
            rejected = self.safe_decimal(doc.get("total_rejected_qty", 0))
            rejection_pct = float(rejected / ordered * 100) if ordered else 0.0

        evidence = [EvidenceItem(
            evidence_type="statistical",
            field_name="rejection_rate_pct",
            field_name_ar="نسبة رفض البضاعة",
            expected_value=f"< {warn_threshold}%",
            actual_value=f"{rejection_pct:.1f}%",
            description=f"Rejection rate: {rejection_pct:.1f}%",
            description_ar=f"نسبة الرفض: {rejection_pct:.1f}%",
        )]

        if rejection_pct >= fail_threshold:
            return self._fail(
                f"Rejection rate {rejection_pct:.1f}% exceeds critical threshold ({fail_threshold}%). "
                "Indicates severe quality failure or supplier fraud.",
                f"نسبة الرفض {rejection_pct:.1f}% تتجاوز الحد الحرج ({fail_threshold}%). "
                "قد يدل على فشل جودة حاد أو احتيال من المورد.",
                evidence=evidence,
            )
        if rejection_pct >= warn_threshold:
            return self._warning(
                f"Rejection rate {rejection_pct:.1f}% exceeds warning threshold ({warn_threshold}%).",
                f"نسبة الرفض {rejection_pct:.1f}% تتجاوز حد التحذير ({warn_threshold}%).",
                evidence=evidence,
            )
        return self._pass(
            f"Rejection rate {rejection_pct:.1f}% is within acceptable limits.",
            f"نسبة الرفض {rejection_pct:.1f}% ضمن الحدود المقبولة.",
        )


class GRNPriceDeviationRule(AuditRuleBase):
    """GRN-M06 — Unit prices in GRN must match the linked PO prices."""
    rule_code = "GRN-M06"
    rule_name_en = "GRN Price Deviation from PO"
    rule_name_ar = "انحراف أسعار إشعار الاستلام عن أمر الشراء"
    default_severity = "high"
    rule_type = "reconciliation"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return doc.get("has_price_deviation") is not None or bool(doc.get("line_items"))

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        tolerance_pct = self.safe_decimal(self.get_config("tolerance_pct", "5.0"))

        # Use pre-computed flag as fast path
        if doc.get("has_price_deviation"):
            return self._fail(
                "Price deviation detected between GRN and the linked Purchase Order.",
                "تم اكتشاف انحراف في الأسعار بين إشعار الاستلام وأمر الشراء المرتبط.",
                evidence=[EvidenceItem(
                    evidence_type="comparison",
                    field_name="has_price_deviation",
                    field_name_ar="انحراف الأسعار",
                    expected_value=False,
                    actual_value=True,
                    description="Pre-computed price deviation flag is set.",
                    description_ar="علامة انحراف الأسعار المحسوبة مسبقاً مُعيَّنة.",
                )]
            )

        # Check line items for individual price deviations
        items = doc.get("line_items") or []
        deviations = []
        for item in items:
            po_price = self.safe_decimal(item.get("po_unit_price") or item.get("expected_unit_price") or 0)
            grn_price = self.safe_decimal(item.get("unit_price") or 0)
            if po_price > 0 and grn_price > 0:
                pct = abs(grn_price - po_price) / po_price * 100
                if pct > tolerance_pct:
                    deviations.append(f"{item.get('description', 'Item')}: {pct:.1f}%")

        if deviations:
            return self._fail(
                f"Price deviation on {len(deviations)} line item(s): {', '.join(deviations[:3])}",
                f"انحراف أسعار في {len(deviations)} بند: {', '.join(deviations[:3])}",
                evidence=[EvidenceItem(
                    evidence_type="comparison",
                    field_name="line_items",
                    field_name_ar="بنود الاستلام",
                    expected_value=f"Price variance ≤ {tolerance_pct}%",
                    actual_value=str(deviations[:3]),
                    description=f"{len(deviations)} items exceed price tolerance.",
                    description_ar=f"{len(deviations)} بند يتجاوز حد التفاوت السعري.",
                )]
            )
        return self._pass(
            "GRN prices are within acceptable range of PO prices.",
            "أسعار إشعار الاستلام ضمن النطاق المقبول لأسعار أمر الشراء.",
        )


class GRNDeliveryOverdueRule(AuditRuleBase):
    """GRN-M07 — Flags GRNs where delivery is overdue beyond the contracted date."""
    rule_code = "GRN-M07"
    rule_name_en = "GRN Delivery Overdue"
    rule_name_ar = "تأخر تسليم البضاعة عن الموعد المحدد"
    default_severity = "medium"
    rule_type = "compliance"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return doc.get("delivery_overdue") is not None or doc.get("delivery_date") is not None

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        if doc.get("delivery_overdue"):
            delivery_date = doc.get("delivery_date", "N/A")
            grn_date = doc.get("grn_date") or doc.document_date
            return self._warning(
                f"Delivery is overdue. Expected delivery: {delivery_date}, "
                f"actual receipt: {grn_date}.",
                f"تأخر التسليم. التسليم المتوقع: {delivery_date}، "
                f"الاستلام الفعلي: {grn_date}.",
                evidence=[EvidenceItem(
                    evidence_type="comparison",
                    field_name="delivery_date",
                    field_name_ar="تاريخ التسليم",
                    expected_value=str(delivery_date),
                    actual_value=str(grn_date),
                    description="GRN received after contracted delivery date.",
                    description_ar="تم استلام البضاعة بعد تاريخ التسليم المتفق عليه.",
                )]
            )
        return self._pass(
            "Delivery received within contracted timeframe.",
            "تم استلام البضاعة ضمن الإطار الزمني المتفق عليه.",
        )


class GRNQualityInspectionRule(AuditRuleBase):
    """GRN-M08 — Quality inspection must be performed and documented."""
    rule_code = "GRN-M08"
    rule_name_en = "GRN Quality Inspection Not Performed"
    rule_name_ar = "لم يتم إجراء فحص جودة البضاعة"
    default_severity = "medium"
    rule_type = "compliance"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return True

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        inspection_done = doc.get("quality_inspection_done", False)
        inspector = doc.get("inspector_name") or ""
        total_amount = doc.total_amount or 0
        min_amount = float(self.get_config("min_amount_for_inspection", "10000"))

        if float(total_amount) < min_amount:
            return self._not_applicable(
                f"Quality inspection not required for amounts below {min_amount:,.0f}.",
                f"فحص الجودة غير مطلوب للمبالغ أقل من {min_amount:,.0f}.",
            )

        if not inspection_done:
            return self._warning(
                "Quality inspection was not recorded for this goods receipt.",
                "لم يتم تسجيل فحص الجودة لهذا الاستلام.",
                evidence=[EvidenceItem(
                    evidence_type="field_value",
                    field_name="quality_inspection_done",
                    field_name_ar="فحص الجودة",
                    expected_value=True,
                    actual_value=False,
                    description="No quality inspection record found.",
                    description_ar="لم يتم العثور على سجل فحص جودة.",
                )]
            )
        return self._pass(
            f"Quality inspection completed by '{inspector or 'inspector'}'.",
            f"تم إجراء فحص الجودة بواسطة '{inspector or 'المفتش'}'.",
        )


class GRNInvoiceAmountMatchRule(AuditRuleBase):
    """GRN-M09 — GRN total amount must match the linked invoice amount."""
    rule_code = "GRN-M09"
    rule_name_en = "GRN Amount vs Invoice Amount Mismatch"
    rule_name_ar = "عدم تطابق مبلغ إشعار الاستلام مع الفاتورة"
    default_severity = "critical"
    rule_type = "reconciliation"

    DEFAULT_TOLERANCE_PCT = Decimal("5.0")

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return (doc.total_amount is not None and
                doc.get("invoice_amount") is not None)

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        tolerance_pct = self.safe_decimal(self.get_config("tolerance_pct", "5.0"))
        grn_amount = self.safe_decimal(doc.total_amount or 0)
        inv_amount = self.safe_decimal(doc.get("invoice_amount") or 0)

        if inv_amount == 0:
            return self._skipped("Invoice amount is zero — cannot compare.")

        variance_pct = abs(grn_amount - inv_amount) / inv_amount * 100
        evidence = [EvidenceItem(
            evidence_type="comparison",
            field_name="total_amount",
            field_name_ar="مبلغ الاستلام",
            expected_value=float(inv_amount),
            actual_value=float(grn_amount),
            description=f"GRN amount: {grn_amount}, Invoice amount: {inv_amount}, Variance: {variance_pct:.2f}%",
            description_ar=f"مبلغ الاستلام: {grn_amount}، مبلغ الفاتورة: {inv_amount}، الفارق: {variance_pct:.2f}%",
        )]

        if variance_pct > tolerance_pct:
            return self._fail(
                f"GRN amount ({grn_amount}) differs from invoice amount ({inv_amount}) "
                f"by {variance_pct:.2f}% — exceeds {tolerance_pct}% tolerance.",
                f"مبلغ الاستلام ({grn_amount}) يختلف عن مبلغ الفاتورة ({inv_amount}) "
                f"بنسبة {variance_pct:.2f}% — يتجاوز حد التفاوت {tolerance_pct}%.",
                evidence=evidence,
            )
        return self._pass(
            f"GRN and invoice amounts reconcile within tolerance ({variance_pct:.2f}%).",
            f"مبلغا الاستلام والفاتورة متطابقان ضمن حد التفاوت ({variance_pct:.2f}%).",
        )


class GRNApproverPresentRule(AuditRuleBase):
    """GRN-M10 — GRN must be approved by an authorized receiver."""
    rule_code = "GRN-M10"
    rule_name_en = "GRN Missing Authorized Approver"
    rule_name_ar = "إشعار الاستلام يفتقر إلى موافق مخوَّل"
    default_severity = "high"
    rule_type = "compliance"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return True

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        approval_status = doc.get("approval_status") or ""
        approved_by = doc.get("approved_by_id") or doc.get("received_by") or ""

        if approval_status.lower() == "pending" and not approved_by:
            return self._fail(
                "GRN has not been approved by an authorized receiver. "
                "All goods receipts require sign-off to confirm delivery.",
                "إشعار الاستلام لم يتم اعتماده من قِبل مستلم مخوَّل. "
                "يتطلب كل استلام توقيع تأكيد.",
                evidence=[EvidenceItem(
                    evidence_type="field_value",
                    field_name="approval_status",
                    field_name_ar="حالة الاعتماد",
                    expected_value="approved",
                    actual_value=approval_status or "pending",
                    description="GRN approval is pending with no approver set.",
                    description_ar="الموافقة على إشعار الاستلام معلقة ولا يوجد معتمد.",
                )]
            )
        if not approved_by and approval_status.lower() != "approved":
            return self._warning(
                "No authorized receiver recorded on this GRN.",
                "لم يتم تسجيل مستلم مخوَّل في إشعار الاستلام.",
            )
        return self._pass(
            f"GRN approved — status: '{approval_status}'.",
            f"إشعار الاستلام معتمد — الحالة: '{approval_status}'.",
        )
