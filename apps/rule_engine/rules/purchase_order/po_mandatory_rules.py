"""
PO-M01 – PO-M05, PO-M07 — Purchase Order mandatory and control rules.
"""
from decimal import Decimal
from apps.rule_engine.rules.base import AuditRuleBase, NormalizedDocument, RuleResult, EvidenceItem


class POBudgetAvailabilityRule(AuditRuleBase):
    """PO-M01 — PO total must not exceed the assigned budget limit."""
    rule_code = "PO-M01"
    rule_name_en = "Purchase Order Exceeds Budget Limit"
    rule_name_ar = "أمر الشراء يتجاوز حد الميزانية"
    default_severity = "critical"
    rule_type = "compliance"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return doc.budget_limit is not None and doc.total_amount is not None

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        budget = self.safe_decimal(doc.budget_limit)
        total = self.safe_decimal(doc.total_amount or 0)
        tolerance_pct = self.safe_decimal(self.get_config("tolerance_pct", "0"))

        if budget <= 0:
            return self._skipped("Budget limit is zero or not set.")

        limit_with_tolerance = budget * (1 + tolerance_pct / 100)

        if total > limit_with_tolerance:
            over_by = total - budget
            over_pct = (over_by / budget) * 100
            return self._fail(
                f"PO amount {total:,.2f} exceeds budget limit {budget:,.2f} "
                f"by {over_by:,.2f} ({over_pct:.1f}%).",
                f"مبلغ أمر الشراء {total:,.2f} يتجاوز حد الميزانية {budget:,.2f} "
                f"بمقدار {over_by:,.2f} ({over_pct:.1f}%).",
                evidence=[EvidenceItem(
                    evidence_type="comparison",
                    field_name="total_amount",
                    field_name_ar="إجمالي أمر الشراء",
                    expected_value=float(budget),
                    actual_value=float(total),
                    description=f"PO total {total} exceeds budget {budget} by {over_by}.",
                    description_ar=f"إجمالي الأمر {total} يتجاوز الميزانية {budget} بمقدار {over_by}.",
                )]
            )
        return self._pass(
            f"PO amount {total:,.2f} is within budget limit {budget:,.2f}.",
            f"مبلغ أمر الشراء {total:,.2f} ضمن حد الميزانية {budget:,.2f}.",
        )


class POAuthorizationLevelRule(AuditRuleBase):
    """PO-M02 — PO approval authority must match the amount tier."""
    rule_code = "PO-M02"
    rule_name_en = "PO Approval Authority Level Insufficient"
    rule_name_ar = "مستوى صلاحية اعتماد أمر الشراء غير كافٍ"
    default_severity = "critical"
    rule_type = "compliance"

    # Default tiers: {max_amount: required_role}
    DEFAULT_TIERS = [
        (50000,   "manager"),
        (200000,  "director"),
        (500000,  "vp"),
        (float("inf"), "cfo"),
    ]

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return doc.total_amount is not None

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        total = float(doc.total_amount or 0)
        approver_role = str(doc.get("approver_role") or doc.get_org("approver_role") or "").lower()
        approval_status = str(doc.get("approval_status") or "").lower()

        tiers = self.get_config("authorization_tiers") or self.DEFAULT_TIERS
        required_role = "manager"
        for (limit, role) in tiers:
            if total <= float(limit):
                required_role = role
                break

        ROLE_RANK = {"manager": 1, "director": 2, "vp": 3, "cfo": 4, "ceo": 5}
        required_rank = ROLE_RANK.get(required_role, 1)
        actual_rank = ROLE_RANK.get(approver_role, 0)

        if approval_status not in ("approved", "accepted"):
            return self._warning(
                f"PO amount {total:,.2f} requires '{required_role}' approval but status is '{approval_status}'.",
                f"مبلغ أمر الشراء {total:,.2f} يتطلب موافقة '{required_role}' لكن الحالة '{approval_status}'.",
            )

        if approver_role and actual_rank < required_rank:
            return self._fail(
                f"PO amount {total:,.2f} requires '{required_role}' authorization but "
                f"approver role is '{approver_role}'.",
                f"مبلغ أمر الشراء {total:,.2f} يتطلب تفويض '{required_role}' لكن "
                f"دور المعتمد '{approver_role}'.",
                evidence=[EvidenceItem(
                    evidence_type="comparison",
                    field_name="approver_role",
                    field_name_ar="دور المعتمد",
                    expected_value=required_role,
                    actual_value=approver_role,
                    description=f"Amount {total:,.0f} requires role '{required_role}', got '{approver_role}'.",
                    description_ar=f"المبلغ {total:,.0f} يتطلب دور '{required_role}'، الموجود '{approver_role}'.",
                )]
            )
        return self._pass(
            f"PO authorization level is sufficient for amount {total:,.2f}.",
            f"مستوى تفويض أمر الشراء كافٍ للمبلغ {total:,.2f}.",
        )


class POThreeQuotationsRule(AuditRuleBase):
    """PO-M03 — High-value POs must be supported by at least three vendor quotations."""
    rule_code = "PO-M03"
    rule_name_en = "Minimum Three Quotations Not Obtained"
    rule_name_ar = "لم يتم الحصول على ثلاثة عروض أسعار على الأقل"
    default_severity = "high"
    rule_type = "compliance"

    DEFAULT_THRESHOLD = 50000.0

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return doc.total_amount is not None

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        threshold = float(self.get_config("quotation_threshold", self.DEFAULT_THRESHOLD))
        total = float(doc.total_amount or 0)

        if total < threshold:
            return self._not_applicable(
                f"PO amount {total:,.2f} is below quotation threshold {threshold:,.0f}.",
                f"مبلغ أمر الشراء {total:,.2f} أقل من حد عروض الأسعار {threshold:,.0f}.",
            )

        quotations_obtained = doc.get("three_quotes_obtained") or doc.get("quotation_count", 0)
        min_quotes = int(self.get_config("min_quotations", 3))

        # If it's a boolean flag
        if isinstance(quotations_obtained, bool):
            has_quotes = quotations_obtained
            count = min_quotes if has_quotes else 0
        else:
            count = int(quotations_obtained or 0)
            has_quotes = count >= min_quotes

        if not has_quotes:
            return self._fail(
                f"PO amount {total:,.2f} exceeds threshold {threshold:,.0f} but only "
                f"{count} quotation(s) obtained (minimum {min_quotes} required).",
                f"مبلغ أمر الشراء {total:,.2f} يتجاوز الحد {threshold:,.0f} لكن "
                f"عدد العروض {count} (المطلوب على الأقل {min_quotes}).",
                evidence=[EvidenceItem(
                    evidence_type="field_value",
                    field_name="quotation_count",
                    field_name_ar="عدد عروض الأسعار",
                    expected_value=f">= {min_quotes}",
                    actual_value=count,
                    description=f"Only {count} quotation(s) for PO above threshold.",
                    description_ar=f"{count} عرض أسعار فقط لأمر يتجاوز الحد.",
                )]
            )
        return self._pass(
            f"Minimum quotation requirement satisfied ({count} quotations).",
            f"تم استيفاء حد عروض الأسعار الأدنى ({count} عروض).",
        )


class POSplittingRule(AuditRuleBase):
    """PO-M04 — Detects PO splitting (multiple small POs to avoid authorization thresholds)."""
    rule_code = "PO-M04"
    rule_name_en = "Purchase Order Splitting Detected"
    rule_name_ar = "اكتشاف تجزئة أوامر الشراء"
    default_severity = "high"
    rule_type = "anomaly"

    DEFAULT_THRESHOLD  = 50000.0
    ROLLING_DAYS       = 30

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return doc.total_amount is not None and doc.counterparty_name is not None

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        threshold   = float(self.get_config("split_threshold", self.DEFAULT_THRESHOLD))
        window_days = int(self.get_config("rolling_days", self.ROLLING_DAYS))
        total       = float(doc.total_amount or 0)

        if total >= threshold:
            return self._not_applicable(
                f"PO amount {total:,.2f} already meets threshold {threshold:,.0f} — no split risk.",
                f"مبلغ أمر الشراء {total:,.2f} يبلغ الحد {threshold:,.0f} — لا خطر تجزئة.",
            )

        try:
            from apps.documents.typed_models import PurchaseOrder
            from datetime import timedelta, datetime, date as date_type

            vendor = doc.counterparty_name
            org_id = doc.organization_id
            po_date = doc.document_date
            if po_date and not isinstance(po_date, date_type):
                po_date = datetime.fromisoformat(str(po_date)).date()

            if not po_date:
                return self._skipped("Cannot determine PO date for split check.")

            window_start = po_date - timedelta(days=window_days)
            related_pos = PurchaseOrder.objects.filter(
                organization_id=org_id,
                vendor_name__iexact=vendor,
                po_date__gte=window_start,
                po_date__lte=po_date,
            ).exclude(id=doc.document_id)

            if related_pos.exists():
                combined_total = sum(float(po.total_amount or 0) for po in related_pos) + total
                if combined_total >= threshold:
                    po_count = related_pos.count() + 1
                    return self._warning(
                        f"Potential PO splitting: {po_count} POs to '{vendor}' within {window_days} days "
                        f"totalling {combined_total:,.2f} (threshold: {threshold:,.0f}). "
                        "Split POs are used to circumvent approval thresholds.",
                        f"احتمال تجزئة الأوامر: {po_count} أوامر للمورد '{vendor}' خلال {window_days} يوماً "
                        f"بإجمالي {combined_total:,.2f} (الحد: {threshold:,.0f}). "
                        "تجزئة الأوامر تُستخدم للتحايل على حدود التفويض.",
                        evidence=[EvidenceItem(
                            evidence_type="statistical",
                            field_name="total_amount",
                            field_name_ar="إجمالي الأوامر المجمَّعة",
                            expected_value=f"< {threshold:,.0f} per vendor per {window_days} days",
                            actual_value=f"{combined_total:,.2f} across {po_count} POs",
                            description=f"Combined PO total {combined_total:,.2f} for '{vendor}' in {window_days} days.",
                            description_ar=f"إجمالي أوامر الشراء {combined_total:,.2f} للمورد '{vendor}' في {window_days} يوماً.",
                        )]
                    )
        except Exception as e:
            return self._error(e)

        return self._pass(
            "No PO splitting pattern detected.",
            "لم يتم اكتشاف نمط تجزئة أوامر الشراء.",
        )


class PODeliveryDateRule(AuditRuleBase):
    """PO-M05 — PO delivery date must be specified and not overdue without a GRN."""
    rule_code = "PO-M05"
    rule_name_en = "PO Delivery Date Missing or Overdue"
    rule_name_ar = "تاريخ تسليم أمر الشراء مفقود أو متأخر"
    default_severity = "medium"
    rule_type = "compliance"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return True

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        from datetime import date as date_type, datetime, date
        delivery_raw = doc.get("delivery_date")
        po_date_raw  = doc.document_date or doc.get("po_date")

        if not delivery_raw:
            return self._warning(
                "Purchase Order does not specify a delivery date. "
                "Delivery dates are required for goods receipt tracking.",
                "أمر الشراء لا يحدد تاريخ تسليم. "
                "تواريخ التسليم مطلوبة لتتبع استلام البضاعة.",
                evidence=[EvidenceItem(
                    evidence_type="field_value",
                    field_name="delivery_date",
                    field_name_ar="تاريخ التسليم",
                    expected_value="Valid delivery date",
                    actual_value=None,
                    description="No delivery date specified on PO.",
                    description_ar="لم يتم تحديد تاريخ تسليم في أمر الشراء.",
                )]
            )

        try:
            delivery = delivery_raw if isinstance(delivery_raw, date_type) else datetime.fromisoformat(str(delivery_raw)).date()
            today = date.today()
            approval_status = str(doc.get("approval_status") or "").lower()
            linked_grn = doc.get("linked_grn_id") or doc.get("grn_number")

            if delivery < today and approval_status == "approved" and not linked_grn:
                days_overdue = (today - delivery).days
                return self._warning(
                    f"PO delivery date ({delivery}) is {days_overdue} days overdue and no GRN is linked.",
                    f"تاريخ تسليم أمر الشراء ({delivery}) تأخر {days_overdue} يوماً ولا يوجد إشعار استلام مرتبط.",
                    evidence=[EvidenceItem(
                        evidence_type="comparison",
                        field_name="delivery_date",
                        field_name_ar="تاريخ التسليم",
                        expected_value=f">= {today} or linked GRN",
                        actual_value=str(delivery),
                        description=f"Delivery {days_overdue} days overdue, no GRN.",
                        description_ar=f"التسليم متأخر {days_overdue} يوماً، لا يوجد إشعار استلام.",
                    )]
                )
        except (ValueError, TypeError):
            return self._skipped("Could not parse delivery date.")

        return self._pass(
            f"PO delivery date '{delivery_raw}' is specified and valid.",
            f"تاريخ تسليم أمر الشراء '{delivery_raw}' محدد وصالح.",
        )


class POCompletenessRule(AuditRuleBase):
    """PO-M07 — All mandatory PO fields must be present."""
    rule_code = "PO-M07"
    rule_name_en = "Purchase Order Missing Required Fields"
    rule_name_ar = "أمر الشراء يفتقر إلى حقول مطلوبة"
    default_severity = "high"
    rule_type = "validation"

    REQUIRED_FIELDS = [
        ("po_number",       "رقم أمر الشراء"),
        ("vendor_name",     "اسم المورد"),
        ("total_amount",    "المبلغ الإجمالي"),
        ("currency",        "العملة"),
        ("po_date",         "تاريخ الأمر"),
    ]

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return True

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        required = self.get_config("required_fields") or self.REQUIRED_FIELDS
        missing = []
        evidence = []

        for field_en, field_ar in required:
            # Map canonical vs typed_data fields
            value = (
                doc.get(field_en) or
                getattr(doc, field_en, None) or
                (doc.total_amount if field_en == "total_amount" else None) or
                (doc.document_number if field_en == "po_number" else None) or
                (doc.counterparty_name if field_en == "vendor_name" else None) or
                (doc.currency if field_en == "currency" else None) or
                (doc.document_date if field_en == "po_date" else None)
            )
            if not value and str(value) not in ("0", "0.0"):
                missing.append(field_en)
                evidence.append(EvidenceItem(
                    evidence_type="field_value",
                    field_name=field_en,
                    field_name_ar=field_ar,
                    expected_value="Non-empty value",
                    actual_value=None,
                    description=f"Required field '{field_en}' is missing.",
                    description_ar=f"الحقل الإلزامي '{field_ar}' مفقود.",
                ))

        if missing:
            return self._fail(
                f"PO is missing {len(missing)} required field(s): {', '.join(missing)}.",
                f"أمر الشراء يفتقر إلى {len(missing)} حقل إلزامي: {', '.join(missing)}.",
                evidence=evidence,
            )
        return self._pass(
            "All required PO fields are present.",
            "جميع الحقول الإلزامية لأمر الشراء موجودة.",
        )
