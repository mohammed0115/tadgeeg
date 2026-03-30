"""
VAT-03 / INV-M01 – INV-M06 — Invoice mandatory field and integrity rules.
"""
from decimal import Decimal
from apps.rule_engine.rules.base import AuditRuleBase, NormalizedDocument, RuleResult, EvidenceItem


class VATReverseChargeRule(AuditRuleBase):
    """VAT-03 — Reverse-charge mechanism: buyer-charged VAT for imported services."""
    rule_code = "VAT-03"
    rule_name_en = "Reverse Charge Mechanism Validation"
    rule_name_ar = "التحقق من آلية الاحتساب العكسي للضريبة"
    default_severity = "high"
    rule_type = "compliance"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return doc.get("reverse_charge_applicable") is not None

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        reverse_applicable = doc.get("reverse_charge_applicable", False)
        buyer_vat_charged = doc.get("buyer_charged_vat", False)
        supplier_vat_charged = doc.get("vat_amount", 0)

        if not reverse_applicable:
            return self._not_applicable(
                "Reverse charge mechanism does not apply to this document.",
                "آلية الاحتساب العكسي لا تنطبق على هذا المستند.",
            )

        if not buyer_vat_charged:
            return self._fail(
                "Reverse charge applies but buyer-charged VAT flag is not set. "
                "For imported services, the buyer must self-account for VAT.",
                "آلية الاحتساب العكسي مطلوبة لكن لم يتم احتساب الضريبة على المشتري. "
                "في حالة الخدمات المستوردة يجب على المشتري احتساب الضريبة ذاتياً.",
                evidence=[EvidenceItem(
                    evidence_type="field_value",
                    field_name="buyer_charged_vat",
                    field_name_ar="الضريبة المحتسبة على المشتري",
                    expected_value=True,
                    actual_value=False,
                    description="Reverse charge transaction requires buyer to self-account for VAT.",
                    description_ar="معاملة الاحتساب العكسي تستلزم احتساب الضريبة من قِبل المشتري.",
                )]
            )
        return self._pass(
            "Reverse charge VAT correctly applied — buyer is self-accounting for VAT.",
            "تم تطبيق آلية الاحتساب العكسي بشكل صحيح — المشتري يحتسب الضريبة ذاتياً.",
        )


class InvoiceVendorNameRule(AuditRuleBase):
    """INV-M01 — Vendor name must be present and non-empty."""
    rule_code = "INV-M01"
    rule_name_en = "Vendor Name Missing"
    rule_name_ar = "اسم المورد مفقود"
    default_severity = "high"
    rule_type = "validation"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return True

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        vendor = doc.counterparty_name or doc.get("vendor_name") or doc.get("seller_name") or ""
        if not str(vendor).strip():
            return self._fail(
                "Vendor / seller name is missing from the invoice.",
                "اسم المورد / البائع مفقود من الفاتورة.",
                evidence=[EvidenceItem(
                    evidence_type="field_value",
                    field_name="vendor_name",
                    field_name_ar="اسم المورد",
                    expected_value="Non-empty vendor name",
                    actual_value=None,
                    description="Vendor name field is empty or absent.",
                    description_ar="حقل اسم المورد فارغ أو غائب.",
                )]
            )
        return self._pass(
            f"Vendor name present: '{vendor}'.",
            f"اسم المورد موجود: '{vendor}'.",
        )


class InvoiceVendorVATRule(AuditRuleBase):
    """INV-M02 — Vendor VAT/Tax registration number must be present."""
    rule_code = "INV-M02"
    rule_name_en = "Vendor VAT Number Missing"
    rule_name_ar = "رقم الضريبة للمورد مفقود"
    default_severity = "high"
    rule_type = "compliance"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        country = (doc.get_org("country") or "SA").upper()
        return country not in ("KW", "QA")

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        vat_num = doc.tax_id or doc.get("vendor_vat_number") or doc.get("seller_vat_number") or ""
        if not str(vat_num).strip():
            return self._fail(
                "Vendor VAT / tax registration number is missing.",
                "رقم تسجيل ضريبة المورد مفقود.",
                evidence=[EvidenceItem(
                    evidence_type="field_value",
                    field_name="vendor_vat_number",
                    field_name_ar="الرقم الضريبي للمورد",
                    expected_value="Valid tax registration number",
                    actual_value=None,
                    description="Vendor tax registration number not found in the document.",
                    description_ar="لم يتم العثور على رقم التسجيل الضريبي للمورد.",
                )]
            )
        return self._pass(
            f"Vendor VAT number present: '{vat_num}'.",
            f"الرقم الضريبي للمورد موجود: '{vat_num}'.",
        )


class InvoiceDueDateRule(AuditRuleBase):
    """INV-M03 — Due date must be present and must not precede the invoice date."""
    rule_code = "INV-M03"
    rule_name_en = "Invoice Due Date Invalid"
    rule_name_ar = "تاريخ استحقاق الفاتورة غير صالح"
    default_severity = "medium"
    rule_type = "validation"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return doc.document_date is not None

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        from datetime import date as date_type, datetime
        due_date_raw = doc.get("due_date")
        if not due_date_raw:
            return self._warning(
                "Invoice due date is not specified.",
                "تاريخ استحقاق الفاتورة غير محدد.",
                evidence=[EvidenceItem(
                    evidence_type="field_value",
                    field_name="due_date",
                    field_name_ar="تاريخ الاستحقاق",
                    expected_value="Valid future date",
                    actual_value=None,
                    description="Due date field is absent.",
                    description_ar="حقل تاريخ الاستحقاق غائب.",
                )]
            )

        try:
            due = due_date_raw if isinstance(due_date_raw, date_type) else datetime.fromisoformat(str(due_date_raw)).date()
            inv = doc.document_date if isinstance(doc.document_date, date_type) else datetime.fromisoformat(str(doc.document_date)).date()
        except (ValueError, TypeError):
            return self._skipped("Could not parse due date for comparison.")

        if due < inv:
            return self._fail(
                f"Due date ({due}) precedes the invoice date ({inv}). "
                "Payment cannot be due before the invoice is issued.",
                f"تاريخ الاستحقاق ({due}) قبل تاريخ الفاتورة ({inv}). "
                "لا يمكن أن يكون الاستحقاق قبل إصدار الفاتورة.",
                evidence=[EvidenceItem(
                    evidence_type="comparison",
                    field_name="due_date",
                    field_name_ar="تاريخ الاستحقاق",
                    expected_value=f">= {inv}",
                    actual_value=str(due),
                    description=f"Due date {due} is before invoice date {inv}.",
                    description_ar=f"تاريخ الاستحقاق {due} قبل تاريخ الفاتورة {inv}.",
                )]
            )
        return self._pass(
            f"Due date ({due}) is valid — on or after invoice date ({inv}).",
            f"تاريخ الاستحقاق ({due}) صالح — في أو بعد تاريخ الفاتورة ({inv}).",
        )


class InvoiceLineItemsPresenceRule(AuditRuleBase):
    """INV-M04 — Invoice must contain at least one line item."""
    rule_code = "INV-M04"
    rule_name_en = "Invoice Has No Line Items"
    rule_name_ar = "الفاتورة لا تحتوي على بنود"
    default_severity = "high"
    rule_type = "validation"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return True

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        items = doc.get("line_items") or []
        if not items:
            return self._fail(
                "Invoice contains no line items. At least one item is required.",
                "الفاتورة لا تحتوي على أي بنود. مطلوب بند واحد على الأقل.",
                evidence=[EvidenceItem(
                    evidence_type="field_value",
                    field_name="line_items",
                    field_name_ar="بنود الفاتورة",
                    expected_value="Non-empty list",
                    actual_value=[],
                    description="No line items found in the invoice.",
                    description_ar="لم يتم العثور على أي بنود في الفاتورة.",
                )]
            )
        return self._pass(
            f"Invoice contains {len(items)} line item(s).",
            f"الفاتورة تحتوي على {len(items)} بند.",
        )


class InvoiceLineItemTotalRule(AuditRuleBase):
    """INV-M05 — Sum of line item totals must equal the declared subtotal."""
    rule_code = "INV-M05"
    rule_name_en = "Line Items Total Mismatch"
    rule_name_ar = "مجموع بنود الفاتورة لا يطابق الإجمالي"
    default_severity = "critical"
    rule_type = "validation"

    TOLERANCE = Decimal("0.50")

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        items = doc.get("line_items") or []
        return len(items) > 0 and doc.get("subtotal") is not None

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        tolerance = self.safe_decimal(self.get_config("tolerance", "0.50"))
        items = doc.get("line_items") or []
        subtotal = self.safe_decimal(doc.get("subtotal") or doc.total_amount or 0)

        lines_total = Decimal("0")
        for item in items:
            item_total = item.get("total") or item.get("amount") or 0
            lines_total += self.safe_decimal(item_total)

        discrepancy = abs(lines_total - subtotal)
        evidence = [EvidenceItem(
            evidence_type="calculation",
            field_name="subtotal",
            field_name_ar="الإجمالي قبل الضريبة",
            expected_value=float(lines_total),
            actual_value=float(subtotal),
            description=f"Sum of {len(items)} line items = {lines_total}, declared subtotal = {subtotal}",
            description_ar=f"مجموع {len(items)} بند = {lines_total}، الإجمالي المُعلن = {subtotal}",
        )]

        if discrepancy > tolerance:
            return self._fail(
                f"Line items sum ({lines_total}) differs from subtotal ({subtotal}) by {discrepancy}.",
                f"مجموع البنود ({lines_total}) يختلف عن الإجمالي ({subtotal}) بفارق {discrepancy}.",
                evidence=evidence,
            )
        return self._pass(
            f"Line items total ({lines_total}) matches subtotal ({subtotal}) within tolerance.",
            f"مجموع البنود ({lines_total}) يطابق الإجمالي ({subtotal}) ضمن حد التفاوت.",
        )


class InvoiceSequenceGapRule(AuditRuleBase):
    """INV-M06 — Detects suspicious gaps in sequential invoice numbering from same vendor."""
    rule_code = "INV-M06"
    rule_name_en = "Invoice Sequence Gap Detected"
    rule_name_ar = "فجوة في تسلسل أرقام الفواتير"
    default_severity = "medium"
    rule_type = "anomaly"

    MAX_GAP = 100  # Flag if gap > 100 between consecutive numeric invoice numbers

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        num = doc.document_number or doc.get("invoice_number") or ""
        return bool(str(num).strip())

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        try:
            from apps.invoices.models import Invoice
            inv_number = doc.document_number or doc.get("invoice_number") or ""
            vendor = doc.counterparty_name or doc.get("vendor_name") or ""
            org_id = doc.organization_id
            max_gap = int(self.get_config("max_gap", self.MAX_GAP))

            # Extract numeric suffix from invoice number
            digits = "".join(c for c in str(inv_number) if c.isdigit())
            if not digits:
                return self._skipped("Invoice number has no numeric component for sequence check.")

            current_num = int(digits)

            # Find the most recent previous invoice from the same vendor
            qs = Invoice.objects.filter(
                organization_id=org_id,
                vendor_name__iexact=vendor,
            ).exclude(id=doc.document_id).order_by("-invoice_date")

            for prev_inv in qs[:20]:
                prev_digits = "".join(c for c in str(prev_inv.invoice_number or "") if c.isdigit())
                if not prev_digits:
                    continue
                prev_num = int(prev_digits)
                gap = abs(current_num - prev_num)
                if gap > max_gap:
                    return self._warning(
                        f"Invoice number gap of {gap} detected vs previous invoice "
                        f"'{prev_inv.invoice_number}' from same vendor. "
                        f"Gaps > {max_gap} may indicate hidden or voided invoices.",
                        f"فجوة في التسلسل بمقدار {gap} مقارنةً بالفاتورة السابقة "
                        f"'{prev_inv.invoice_number}' من نفس المورد. "
                        f"الفجوات > {max_gap} قد تشير إلى فواتير مخفية أو ملغاة.",
                        evidence=[EvidenceItem(
                            evidence_type="comparison",
                            field_name="invoice_number",
                            field_name_ar="رقم الفاتورة",
                            expected_value=f"Sequential (gap ≤ {max_gap})",
                            actual_value=f"Gap = {gap} (current: {inv_number}, prev: {prev_inv.invoice_number})",
                            description=f"Numeric gap of {gap} between current and previous invoice.",
                            description_ar=f"فجوة رقمية بمقدار {gap} بين الفاتورة الحالية والسابقة.",
                        )]
                    )
                break  # Only check the most recent comparable invoice

            return self._pass(
                "Invoice numbering sequence is within acceptable range.",
                "تسلسل أرقام الفواتير ضمن النطاق المقبول.",
            )
        except Exception as e:
            return self._error(e)
