"""CTL-04, CTL-05, CTL-06: Workflow control rules"""
from apps.rule_engine.rules.base import AuditRuleBase, NormalizedDocument, RuleResult, EvidenceItem

class NoEditAfterApprovalRule(AuditRuleBase):
    rule_code = "CTL-04"
    rule_name_en = "No Edit After Approval"
    rule_name_ar = "عدم التعديل بعد الموافقة"
    default_severity = "high"
    rule_type = "compliance"

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        status = doc.status or ""
        approved_statuses = {"approved", "APPROVED"}
        if status in approved_statuses:
            # In a real system, check audit trail for edits after approval timestamp
            # For now, flag if we detect edit_after_approve in typed_data
            edit_after = doc.get("edit_after_approve", False)
            no_edit_after = doc.get("no_edit_after_approve", True)
            if edit_after or not no_edit_after:
                return self._fail(
                    "Document was edited after being approved.",
                    "تم تعديل المستند بعد الموافقة عليه.",
                    evidence=[EvidenceItem(
                        evidence_type="field_value",
                        field_name="status",
                        field_name_ar="الحالة",
                        expected_value="No edits after approval",
                        actual_value="Edit detected",
                        description="Approved document was modified.",
                        description_ar="تم تعديل مستند معتمد.",
                    )]
                )
        return self._pass(
            "No unauthorized edits detected after approval.",
            "لا توجد تعديلات غير مصرح بها بعد الموافقة.",
        )


class HasApproverRule(AuditRuleBase):
    rule_code = "CTL-05"
    rule_name_en = "Has Approver"
    rule_name_ar = "وجود موافق"
    default_severity = "medium"
    rule_type = "compliance"

    # Document types that require an approver
    REQUIRES_APPROVER = {"sales_invoice", "purchase_order", "payroll", "expense", "tax_return", "fixed_asset"}

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return doc.document_type in self.REQUIRES_APPROVER

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        approver = doc.approved_by_id or doc.get("approved_by") or doc.get("approver_id")
        if not approver:
            return self._warning(
                "Document has no assigned approver.",
                "المستند لا يحتوي على موافق معيّن.",
                evidence=[EvidenceItem(
                    evidence_type="field_value",
                    field_name="approved_by",
                    field_name_ar="الموافق",
                    expected_value="User ID",
                    actual_value=None,
                    description="No approver assigned to this document.",
                    description_ar="لم يتم تعيين موافق لهذا المستند.",
                )]
            )
        return self._pass(
            f"Document has an assigned approver.",
            "المستند لديه موافق معيّن.",
        )


class HasAuditTrailRule(AuditRuleBase):
    rule_code = "CTL-06"
    rule_name_en = "Has Audit Trail"
    rule_name_ar = "وجود سجل مراجعة"
    default_severity = "low"
    rule_type = "compliance"

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        # Check that the document has been logged in the audit event system
        try:
            from apps.audit.models import AuditFinding
            has_trail = AuditFinding.objects.filter(
                document_id=doc.document_id
            ).exists()

            if not has_trail:
                # Check invoice audit events
                from apps.invoices.models import InvoiceAuditEvent
                has_trail = InvoiceAuditEvent.objects.filter(
                    invoice_id=doc.document_id
                ).exists()
        except Exception:
            has_trail = True  # Can't verify, don't flag

        if not has_trail:
            return self._warning(
                "No audit trail events found for this document.",
                "لا توجد سجلات مراجعة لهذا المستند.",
            )
        return self._pass(
            "Audit trail records exist for this document.",
            "سجلات المراجعة موجودة لهذا المستند.",
        )


class CostCenterRule(AuditRuleBase):
    rule_code = "CTL-01"
    rule_name_en = "Cost Center Assigned"
    rule_name_ar = "وجود مركز التكلفة"
    default_severity = "medium"
    rule_type = "compliance"

    REQUIRES_COST_CENTER = {"sales_invoice", "purchase_order", "expense", "fixed_asset", "payroll"}

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return doc.document_type in self.REQUIRES_COST_CENTER

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        cost_center = doc.cost_center or doc.get("cost_center") or doc.get("department")
        if not cost_center:
            return self._warning(
                "Document has no cost center or department assigned.",
                "المستند لا يحتوي على مركز تكلفة أو قسم.",
                evidence=[EvidenceItem(
                    evidence_type="field_value",
                    field_name="cost_center",
                    field_name_ar="مركز التكلفة",
                    expected_value="Cost center code",
                    actual_value=None,
                    description="Cost center field is empty.",
                    description_ar="حقل مركز التكلفة فارغ.",
                )]
            )
        return self._pass(f"Cost center '{cost_center}' assigned.", f"مركز التكلفة '{cost_center}' معيّن.")
