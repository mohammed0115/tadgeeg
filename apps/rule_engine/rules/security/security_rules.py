"""
SEC-M01 – SEC-M06 — Security and access control audit rules.
These rules enforce segregation of duties, approval controls, and access patterns.
"""
from apps.rule_engine.rules.base import AuditRuleBase, NormalizedDocument, RuleResult, EvidenceItem


class SelfApprovalSecurityRule(AuditRuleBase):
    """SEC-M01 — Segregation of duties: uploader and approver must be different persons."""
    rule_code = "SEC-M01"
    rule_name_en = "Self-Approval Security Violation"
    rule_name_ar = "انتهاك أمني: موافقة الشخص على عمله"
    default_severity = "critical"
    rule_type = "compliance"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return bool(doc.approved_by_id)

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        approved_by = str(doc.approved_by_id or "")
        uploaded_by = str(doc.get("uploaded_by_id") or "")
        submitted_by = str(doc.get("employee_id") or doc.get("submitted_by") or "")

        submitter = uploaded_by or submitted_by

        if approved_by and submitter and approved_by == submitter:
            return self._fail(
                f"Segregation of duties violation: the same person (ID: {approved_by}) "
                "submitted and approved this document. "
                "This is a critical internal control failure.",
                f"انتهاك مبدأ الفصل بين المهام: الشخص نفسه (المعرّف: {approved_by}) "
                "قدَّم المستند واعتمده. "
                "هذا إخفاق حرج في الرقابة الداخلية.",
                evidence=[EvidenceItem(
                    evidence_type="comparison",
                    field_name="approved_by_id",
                    field_name_ar="معرّف المعتمد",
                    expected_value="Different from submitter",
                    actual_value=f"Same as submitter: {approved_by}",
                    description=f"Submitter ID == Approver ID: {approved_by}",
                    description_ar=f"معرّف المقدِّم == معرّف المعتمد: {approved_by}",
                )]
            )
        return self._pass(
            "Segregation of duties satisfied — submitter and approver are different.",
            "مبدأ الفصل بين المهام محقَّق — المقدِّم والمعتمد مختلفان.",
        )


class HighValueDualAuthorizationRule(AuditRuleBase):
    """SEC-M02 — Documents above the dual-authorization threshold need two approvers."""
    rule_code = "SEC-M02"
    rule_name_en = "High-Value Document Missing Dual Authorization"
    rule_name_ar = "مستند ذو قيمة عالية يفتقر للتفويض المزدوج"
    default_severity = "high"
    rule_type = "compliance"

    DEFAULT_THRESHOLD = 100000.0

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return doc.total_amount is not None

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        threshold = float(self.get_config("dual_auth_threshold",
                                          doc.get_org("dual_approval_threshold") or self.DEFAULT_THRESHOLD))
        amount = float(doc.total_amount or 0)

        if amount <= threshold:
            return self._not_applicable(
                f"Amount {amount:,.2f} is below dual-authorization threshold {threshold:,.0f}.",
                f"المبلغ {amount:,.2f} أقل من حد التفويض المزدوج {threshold:,.0f}.",
            )

        approvers = doc.get("approver_ids") or []
        if not approvers:
            approver_id = doc.approved_by_id or doc.get("approved_by_id")
            approvers = [approver_id] if approver_id else []

        if len(approvers) < 2:
            return self._fail(
                f"Document amount {amount:,.2f} requires dual authorization "
                f"(threshold: {threshold:,.0f}) but only {len(approvers)} approver(s) recorded.",
                f"مبلغ المستند {amount:,.2f} يستلزم تفويضاً مزدوجاً "
                f"(الحد: {threshold:,.0f}) لكن عدد المعتمدين المسجَّلين: {len(approvers)}.",
                evidence=[EvidenceItem(
                    evidence_type="comparison",
                    field_name="approver_ids",
                    field_name_ar="معرّفات المعتمدين",
                    expected_value="≥ 2 approvers",
                    actual_value=f"{len(approvers)} approver(s): {approvers}",
                    description=f"High-value document requires 2+ approvers, found {len(approvers)}.",
                    description_ar=f"المستند ذو القيمة العالية يحتاج 2+ معتمدين، تم العثور على {len(approvers)}.",
                )]
            )
        return self._pass(
            f"Dual authorization satisfied ({len(approvers)} approvers for amount {amount:,.2f}).",
            f"التفويض المزدوج محقَّق ({len(approvers)} معتمدين للمبلغ {amount:,.2f}).",
        )


class BlockedVendorRule(AuditRuleBase):
    """SEC-M03 — Vendor must not appear on the organization's blocked / sanctioned list."""
    rule_code = "SEC-M03"
    rule_name_en = "Transaction with Blocked or Sanctioned Vendor"
    rule_name_ar = "معاملة مع مورد محظور أو خاضع لعقوبات"
    default_severity = "critical"
    rule_type = "compliance"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        blocked = doc.get_org("blocked_vendor_ids") or []
        return bool(blocked)

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        blocked = doc.get_org("blocked_vendor_ids") or []
        vendor_name = str(doc.counterparty_name or doc.get("vendor_name") or doc.get("payee_name") or "").strip()
        vendor_vat = str(doc.tax_id or doc.get("vendor_vat_number") or doc.get("payee_vat_number") or "").strip()

        blocked_lower = [str(b).lower() for b in blocked]

        matched = None
        if vendor_name.lower() in blocked_lower:
            matched = vendor_name
        elif vendor_vat and vendor_vat.lower() in blocked_lower:
            matched = vendor_vat

        if matched:
            return self._fail(
                f"Vendor '{matched}' appears on the organization's blocked/sanctioned list. "
                "This transaction must be halted immediately.",
                f"المورد '{matched}' مدرج في قائمة الموردين المحظورين للمؤسسة. "
                "يجب إيقاف هذه المعاملة فوراً.",
                evidence=[EvidenceItem(
                    evidence_type="reference",
                    field_name="vendor_name",
                    field_name_ar="اسم المورد",
                    expected_value="Not on blocked list",
                    actual_value=matched,
                    description=f"Vendor '{matched}' found in blocked vendor list.",
                    description_ar=f"المورد '{matched}' موجود في قائمة الموردين المحظورين.",
                )]
            )
        return self._pass(
            f"Vendor '{vendor_name}' is not on the blocked list.",
            f"المورد '{vendor_name}' غير مدرج في قائمة الموردين المحظورين.",
        )


class WeekendSubmissionRule(AuditRuleBase):
    """SEC-M04 — Documents submitted on weekends (Fri/Sat in GCC) are higher risk."""
    rule_code = "SEC-M04"
    rule_name_en = "Weekend / Off-Hours Document Submission"
    rule_name_ar = "تقديم مستند في عطلة نهاية الأسبوع"
    default_severity = "medium"
    rule_type = "anomaly"

    # Saudi/GCC weekend: Friday (4) and Saturday (5) in Python weekday()
    WEEKEND_DAYS = {4, 5}  # Friday=4, Saturday=5

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return doc.document_date is not None

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        try:
            from datetime import date as date_type, datetime
            doc_date = doc.document_date
            if not isinstance(doc_date, date_type):
                doc_date = datetime.fromisoformat(str(doc_date)).date()

            weekday = doc_date.weekday()
            weekend_days = set(self.get_config("weekend_days") or self.WEEKEND_DAYS)

            if weekday in weekend_days:
                day_name = doc_date.strftime("%A")
                return self._warning(
                    f"Document dated {doc_date} ({day_name}) falls on a weekend. "
                    "Weekend transactions carry elevated fraud risk and may bypass standard controls.",
                    f"تاريخ المستند {doc_date} ({day_name}) يقع في عطلة نهاية الأسبوع. "
                    "معاملات العطلة تحمل مخاطر احتيال أعلى وقد تتجاوز الضوابط المعيارية.",
                    evidence=[EvidenceItem(
                        evidence_type="field_value",
                        field_name="document_date",
                        field_name_ar="تاريخ المستند",
                        expected_value="Weekday (Sun–Thu)",
                        actual_value=f"{doc_date} ({day_name})",
                        description=f"Document date falls on {day_name} (weekend).",
                        description_ar=f"تاريخ المستند يقع يوم {day_name} (عطلة).",
                    )]
                )
            return self._pass(
                f"Document date {doc_date} is a standard business day.",
                f"تاريخ المستند {doc_date} يوم عمل اعتيادي.",
            )
        except Exception as e:
            return self._error(e)


class EditAfterApprovalRule(AuditRuleBase):
    """SEC-M05 — Documents must not be modified after they have been approved."""
    rule_code = "SEC-M05"
    rule_name_en = "Document Edited After Approval"
    rule_name_ar = "تعديل المستند بعد الموافقة"
    default_severity = "critical"
    rule_type = "compliance"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return doc.get("approval_status") is not None or doc.status is not None

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        status = doc.get("approval_status") or doc.status or ""
        updated_at = doc.get("updated_at")
        approved_at = doc.get("approved_at")

        is_approved = status.lower() in ("approved", "accepted")

        if not is_approved:
            return self._not_applicable(
                "Document is not yet approved — edit-after-approval check skipped.",
                "المستند لم تتم الموافقة عليه بعد — تم تخطي فحص التعديل بعد الموافقة.",
            )

        if updated_at and approved_at:
            try:
                from datetime import datetime
                upd = updated_at if not isinstance(updated_at, str) else datetime.fromisoformat(str(updated_at))
                appr = approved_at if not isinstance(approved_at, str) else datetime.fromisoformat(str(approved_at))

                if upd > appr:
                    return self._fail(
                        f"Document was modified after approval (updated: {upd}, approved: {appr}). "
                        "Post-approval edits are a critical internal control violation.",
                        f"تم تعديل المستند بعد الموافقة (التعديل: {upd}، الموافقة: {appr}). "
                        "التعديلات بعد الموافقة تُعدّ انتهاكاً حرجاً للرقابة الداخلية.",
                        evidence=[EvidenceItem(
                            evidence_type="comparison",
                            field_name="updated_at",
                            field_name_ar="تاريخ آخر تعديل",
                            expected_value=f"<= {appr}",
                            actual_value=str(upd),
                            description=f"Updated {upd} is after approval {appr}.",
                            description_ar=f"تاريخ التعديل {upd} بعد تاريخ الموافقة {appr}.",
                        )]
                    )
            except (ValueError, TypeError):
                pass

        return self._pass(
            "No post-approval modifications detected.",
            "لم يتم اكتشاف أي تعديلات بعد الموافقة.",
        )


class AuditTrailCompletenessRule(AuditRuleBase):
    """SEC-M06 — Document must have a complete audit trail (at least one logged event)."""
    rule_code = "SEC-M06"
    rule_name_en = "Audit Trail Incomplete or Missing"
    rule_name_ar = "سجل التدقيق غير مكتمل أو مفقود"
    default_severity = "high"
    rule_type = "compliance"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return True

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        audit_trail = doc.get("audit_trail") or doc.get("audit_events") or []
        has_trail = bool(audit_trail) or doc.get("has_audit_trail", False)

        # Also check for approved_at / created_at as minimal trail evidence
        has_timestamps = bool(doc.get("approved_at") or doc.get("created_at"))

        if not has_trail and not has_timestamps:
            return self._warning(
                "No audit trail events found for this document. "
                "Complete audit trails are required for regulatory compliance.",
                "لم يتم العثور على أحداث في سجل التدقيق لهذا المستند. "
                "سجلات التدقيق الكاملة مطلوبة للامتثال التنظيمي.",
                evidence=[EvidenceItem(
                    evidence_type="field_value",
                    field_name="audit_trail",
                    field_name_ar="سجل التدقيق",
                    expected_value="At least 1 audit event",
                    actual_value=[],
                    description="Audit trail is empty.",
                    description_ar="سجل التدقيق فارغ.",
                )]
            )
        return self._pass(
            "Audit trail is present.",
            "سجل التدقيق موجود.",
        )
