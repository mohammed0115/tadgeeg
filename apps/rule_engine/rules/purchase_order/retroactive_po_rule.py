"""PO-M08: Retroactive PO (PO date after invoice date)"""
from datetime import date
from apps.rule_engine.rules.base import AuditRuleBase, NormalizedDocument, RuleResult, EvidenceItem

class RetroactivePORule(AuditRuleBase):
    rule_code = "PO-M08"
    rule_name_en = "Retroactive PO Creation"
    rule_name_ar = "إنشاء أمر شراء بأثر رجعي"
    default_severity = "high"
    rule_type = "compliance"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return doc.document_date is not None and doc.get("linked_invoice_id") is not None

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        try:
            from apps.invoices.models import Invoice
            linked_id = doc.get("linked_invoice_id")
            inv = Invoice.objects.filter(id=linked_id).first()

            if not inv or not inv.invoice_date:
                return self._skipped("No linked invoice date available for comparison.")

            po_date = doc.document_date
            if isinstance(po_date, str):
                from datetime import datetime
                po_date = datetime.fromisoformat(po_date).date()

            inv_date = inv.invoice_date
            if isinstance(inv_date, str):
                from datetime import datetime
                inv_date = datetime.fromisoformat(inv_date).date()

            if po_date > inv_date:
                return self._fail(
                    f"PO date ({po_date}) is after the linked invoice date ({inv_date}). PO should precede invoicing.",
                    f"تاريخ أمر الشراء ({po_date}) بعد تاريخ الفاتورة المرتبطة ({inv_date}). يجب أن يسبق الأمر الفاتورة.",
                    evidence=[EvidenceItem(
                        evidence_type="comparison",
                        field_name="po_date",
                        field_name_ar="تاريخ أمر الشراء",
                        expected_value=f"<= {inv_date}",
                        actual_value=str(po_date),
                        description=f"PO issued {(po_date - inv_date).days} days after the invoice.",
                        description_ar=f"أمر الشراء صدر بعد الفاتورة بـ {(po_date - inv_date).days} يوم.",
                        linked_document_type="sales_invoice",
                        linked_document_id=str(linked_id),
                    )]
                )

            return self._pass(
                f"PO date ({po_date}) precedes invoice date ({inv_date}). ✓",
                f"تاريخ أمر الشراء ({po_date}) سابق لتاريخ الفاتورة ({inv_date}). ✓",
            )
        except Exception as e:
            return self._error(e)


class VendorApprovedListRule(AuditRuleBase):
    rule_code = "PO-M06"
    rule_name_en = "Vendor Not on Approved List"
    rule_name_ar = "مورد غير موجود في القائمة المعتمدة"
    default_severity = "high"
    rule_type = "compliance"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        approved_vendors = doc.get_org("approved_vendor_ids", [])
        return bool(approved_vendors)  # Only run if org has an approved list

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        try:
            approved_vendors = doc.get_org("approved_vendor_ids", [])
            vendor_name = doc.counterparty_name or doc.get("vendor_name", "")
            vendor_vat = doc.tax_id or doc.get("vendor_vat_number", "")

            if not vendor_name:
                return self._skipped("No vendor name available for approval check.")

            vendor_approved = (
                vendor_name in approved_vendors or
                vendor_vat in approved_vendors
            )

            if not vendor_approved:
                return self._warning(
                    f"Vendor '{vendor_name}' is not on the organization's approved vendor list.",
                    f"المورد '{vendor_name}' غير موجود في قائمة الموردين المعتمدين.",
                    evidence=[EvidenceItem(
                        evidence_type="reference",
                        field_name="vendor_name",
                        field_name_ar="اسم المورد",
                        expected_value="In approved vendor list",
                        actual_value=vendor_name,
                        description=f"Vendor '{vendor_name}' not in approved list.",
                        description_ar=f"المورد '{vendor_name}' غير موجود في القائمة المعتمدة.",
                    )]
                )

            return self._pass(
                f"Vendor '{vendor_name}' is on the approved vendor list.",
                f"المورد '{vendor_name}' موجود في القائمة المعتمدة.",
            )
        except Exception as e:
            return self._error(e)
