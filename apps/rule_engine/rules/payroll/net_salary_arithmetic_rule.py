"""PAY-M04: Net Salary Arithmetic + PAY-M11: Duplicate Employee IDs + PAY-M02/M05/M06 extended payroll rules"""
from decimal import Decimal
from apps.rule_engine.rules.base import AuditRuleBase, NormalizedDocument, RuleResult, EvidenceItem


class NetSalaryArithmeticRule(AuditRuleBase):
    rule_code = "PAY-M04"
    rule_name_en = "Net Salary Arithmetic Validation"
    rule_name_ar = "التحقق من حساب صافي الراتب"
    default_severity = "critical"
    rule_type = "validation"

    TOLERANCE = Decimal("0.01")

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        employees = doc.get("employees", [])
        return isinstance(employees, list) and len(employees) > 0

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        employees = doc.get("employees", [])
        errors = []
        evidence = []
        calculated_total = Decimal("0")

        for emp in employees:
            emp_id = emp.get("id", "?")
            emp_name = emp.get("name", "غير معروف")
            basic = self.safe_decimal(emp.get("gross", emp.get("basic", 0)))
            allowances = self.safe_decimal(emp.get("allowances", 0))
            deductions = self.safe_decimal(emp.get("deductions", 0))
            net_declared = self.safe_decimal(emp.get("net", 0))

            expected_net = basic + allowances - deductions
            discrepancy = abs(expected_net - net_declared)
            calculated_total += expected_net

            if discrepancy > self.TOLERANCE:
                errors.append(f"{emp_id} ({emp_name})")
                evidence.append(EvidenceItem(
                    evidence_type="calculation",
                    field_name="net_salary",
                    field_name_ar="صافي الراتب",
                    expected_value=float(expected_net),
                    actual_value=float(net_declared),
                    description=f"Employee {emp_name}: Gross+Allowances-Deductions={expected_net}, declared={net_declared}",
                    description_ar=f"الموظف {emp_name}: الأساسي+البدلات-الاستقطاعات={expected_net}، المُعلن={net_declared}",
                ))

        # Validate total
        total_declared = self.safe_decimal(doc.get("total_net_salary", 0))
        total_discrepancy = abs(calculated_total - total_declared)
        if total_discrepancy > self.TOLERANCE:
            errors.append("Total net salary mismatch")
            evidence.append(EvidenceItem(
                evidence_type="calculation",
                field_name="total_net_salary",
                field_name_ar="إجمالي صافي الرواتب",
                expected_value=float(calculated_total),
                actual_value=float(total_declared),
                description=f"Sum of individual nets: {calculated_total}, declared total: {total_declared}",
                description_ar=f"مجموع الصوافي الفردية: {calculated_total}، الإجمالي المُعلن: {total_declared}",
            ))

        if errors:
            return self._fail(
                f"Salary arithmetic errors in {len(errors)} record(s): {', '.join(errors[:3])}",
                f"أخطاء في حسابات الرواتب في {len(errors)} سجل: {', '.join(errors[:3])}",
                evidence=evidence,
            )
        return self._pass(
            f"All {len(employees)} employee salaries calculate correctly.",
            f"جميع رواتب الـ {len(employees)} موظف محسوبة بشكل صحيح.",
        )


class GOSICalculationRule(AuditRuleBase):
    rule_code = "PAY-M03"
    rule_name_en = "GOSI Contribution Mismatch"
    rule_name_ar = "خطأ في حساب اشتراكات التأمينات الاجتماعية (GOSI)"
    default_severity = "high"
    rule_type = "validation"

    SAUDI_RATE = Decimal("0.1175")   # 11.75% for Saudi nationals
    NON_SAUDI_RATE = Decimal("0.0975")  # 9.75% for non-Saudis
    TOLERANCE = Decimal("1.00")

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        employees = doc.get("employees", [])
        return isinstance(employees, list) and len(employees) > 0

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        employees = doc.get("employees", [])
        errors = []
        evidence = []

        for emp in employees:
            gosi = self.safe_decimal(emp.get("gosi", 0))
            if gosi == 0:
                continue

            basic = self.safe_decimal(emp.get("gross", emp.get("basic", 0)))
            is_saudi = emp.get("is_saudi", True)
            rate = self.SAUDI_RATE if is_saudi else self.NON_SAUDI_RATE
            expected_gosi = (basic * rate).quantize(Decimal("0.01"))
            discrepancy = abs(gosi - expected_gosi)

            if discrepancy > self.TOLERANCE:
                emp_name = emp.get("name", emp.get("id", "Unknown"))
                errors.append(emp_name)
                evidence.append(EvidenceItem(
                    evidence_type="calculation",
                    field_name="gosi",
                    field_name_ar="اشتراك التأمينات",
                    expected_value=float(expected_gosi),
                    actual_value=float(gosi),
                    description=f"Employee {emp_name}: basic={basic}, rate={float(rate)*100}%, expected GOSI={expected_gosi}, actual={gosi}",
                    description_ar=f"الموظف {emp_name}: الأساسي={basic}، النسبة={float(rate)*100}%، التأمينات المتوقعة={expected_gosi}، الفعلية={gosi}",
                ))

        if errors:
            return self._fail(
                f"GOSI calculation errors for {len(errors)} employee(s): {', '.join(errors[:3])}",
                f"أخطاء في حساب التأمينات لـ {len(errors)} موظف: {', '.join(errors[:3])}",
                evidence=evidence,
            )
        return self._pass(
            "GOSI contributions are correctly calculated.",
            "اشتراكات التأمينات الاجتماعية محسوبة بشكل صحيح.",
        )


class GhostEmployeeRule(AuditRuleBase):
    rule_code = "PAY-M01"
    rule_name_en = "Ghost Employee Detection"
    rule_name_ar = "كشف الموظف الوهمي"
    default_severity = "critical"
    rule_type = "anomaly"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        employees = doc.get("employees", [])
        ghost_flags = doc.get("ghost_employee_flags", [])
        return isinstance(employees, list) and len(employees) > 0

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        ghost_flags = doc.get("ghost_employee_flags", []) or []
        dup_ids = doc.get("duplicate_employee_ids", []) or []

        issues = []
        evidence = []

        if ghost_flags:
            issues.extend(ghost_flags)
            evidence.append(EvidenceItem(
                evidence_type="reference",
                field_name="ghost_employee_flags",
                field_name_ar="بيانات الموظفين الوهميين",
                expected_value="[]",
                actual_value=ghost_flags[:5],
                description=f"{len(ghost_flags)} employee(s) flagged as ghost employees.",
                description_ar=f"تم الإشارة إلى {len(ghost_flags)} موظف كموظف وهمي.",
            ))

        if dup_ids:
            issues.extend(dup_ids)
            evidence.append(EvidenceItem(
                evidence_type="validation",
                field_name="duplicate_employee_ids",
                field_name_ar="معرّفات موظفين مكررة",
                expected_value="Unique IDs",
                actual_value=dup_ids[:5],
                description=f"{len(dup_ids)} duplicate employee ID(s) detected.",
                description_ar=f"تم اكتشاف {len(dup_ids)} معرّف موظف مكرر.",
            ))

        if issues:
            return self._fail(
                f"Ghost employee indicators detected: {len(ghost_flags)} ghost flags, {len(dup_ids)} duplicate IDs.",
                f"مؤشرات موظفين وهميين: {len(ghost_flags)} موظف مشكوك به، {len(dup_ids)} معرّف مكرر.",
                evidence=evidence,
            )

        return self._pass(
            "No ghost employee indicators detected.",
            "لا توجد مؤشرات على موظفين وهميين.",
        )


class DuplicateEmployeeIDRule(AuditRuleBase):
    rule_code = "PAY-M11"
    rule_name_en = "Duplicate Employee ID"
    rule_name_ar = "معرّف موظف مكرر في الكشف"
    default_severity = "high"
    rule_type = "validation"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        employees = doc.get("employees", [])
        return isinstance(employees, list) and len(employees) > 1

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        employees = doc.get("employees", [])
        seen_ids = {}
        duplicates = []

        for emp in employees:
            emp_id = emp.get("id")
            if not emp_id:
                continue
            if emp_id in seen_ids:
                duplicates.append(emp_id)
            else:
                seen_ids[emp_id] = True

        if duplicates:
            return self._fail(
                f"Duplicate employee IDs found: {duplicates[:5]}",
                f"معرّفات موظفين مكررة: {duplicates[:5]}",
                evidence=[EvidenceItem(
                    evidence_type="validation",
                    field_name="employee_id",
                    field_name_ar="معرّف الموظف",
                    expected_value="All unique",
                    actual_value=duplicates[:5],
                    description=f"{len(duplicates)} duplicate employee ID(s).",
                    description_ar=f"{len(duplicates)} معرّف موظف مكرر.",
                )]
            )
        return self._pass("All employee IDs are unique.", "جميع معرّفات الموظفين فريدة.")


class SalarySpikeRule(AuditRuleBase):
    """PAY-M02 — Detect abnormal salary increases (>30% month-over-month) without documented justification."""
    rule_code = "PAY-M02"
    rule_name_en = "Unexplained Salary Spike Detected"
    rule_name_ar = "ارتفاع مفاجئ غير مبرر في الراتب"
    default_severity = "high"
    rule_type = "anomaly"

    DEFAULT_SPIKE_PCT = 30.0

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        employees = doc.get("employees", [])
        return isinstance(employees, list) and len(employees) > 0

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        threshold_pct = float(self.get_config("spike_threshold_pct", self.DEFAULT_SPIKE_PCT))
        spike_flags = doc.get("salary_spike_flags") or []
        employees = doc.get("employees", [])

        spikes = []
        evidence = []

        # Fast path: use pre-computed flags if available
        if spike_flags:
            spikes.extend(spike_flags)
            evidence.append(EvidenceItem(
                evidence_type="reference",
                field_name="salary_spike_flags",
                field_name_ar="بيانات الارتفاع المفاجئ في الراتب",
                expected_value=f"<= {threshold_pct}% increase",
                actual_value=spike_flags[:5],
                description=f"{len(spike_flags)} employee(s) flagged for salary spikes.",
                description_ar=f"تم الإشارة إلى {len(spike_flags)} موظف بسبب ارتفاع مفاجئ في الراتب.",
            ))

        # Live check: compare current vs previous salary in employee records
        for emp in employees:
            emp_id = str(emp.get("id", "?"))
            current = self.safe_decimal(emp.get("gross", emp.get("basic", 0)))
            previous = self.safe_decimal(emp.get("previous_gross", emp.get("previous_basic", 0)))
            if previous <= 0 or current <= 0:
                continue
            increase_pct = float((current - previous) / previous * 100)
            if increase_pct > threshold_pct:
                emp_name = emp.get("name", emp_id)
                if emp_id not in spikes:  # avoid duplicates with pre-computed flags
                    spikes.append(emp_id)
                evidence.append(EvidenceItem(
                    evidence_type="comparison",
                    field_name="gross_salary",
                    field_name_ar="الراتب الإجمالي",
                    expected_value=f"<= {threshold_pct}% increase",
                    actual_value=f"{increase_pct:.1f}% increase for {emp_name}",
                    description=f"Employee {emp_name}: previous={float(previous):,.2f}, current={float(current):,.2f}, increase={increase_pct:.1f}%.",
                    description_ar=f"الموظف {emp_name}: السابق={float(previous):,.2f}، الحالي={float(current):,.2f}، الزيادة={increase_pct:.1f}%.",
                ))

        if spikes:
            return self._fail(
                f"Unexplained salary spike(s) detected in {len(spikes)} employee record(s) "
                f"(threshold: >{threshold_pct}% increase). Justification required.",
                f"تم اكتشاف ارتفاع مفاجئ في رواتب {len(spikes)} موظف "
                f"(الحد: >{threshold_pct}% زيادة). مطلوب توثيق المبرر.",
                evidence=evidence,
            )
        return self._pass(
            f"No salary spikes exceeding {threshold_pct}% detected.",
            f"لا توجد ارتفاعات مفاجئة تتجاوز {threshold_pct}% في الرواتب.",
        )


class EmployeeCountConsistencyRule(AuditRuleBase):
    """PAY-M05 — Headcount in the payroll list must match the declared employee_count field."""
    rule_code = "PAY-M05"
    rule_name_en = "Employee Headcount Inconsistency"
    rule_name_ar = "تناقض في عدد الموظفين المُدرجين"
    default_severity = "high"
    rule_type = "validation"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        employees = doc.get("employees", [])
        return isinstance(employees, list) and len(employees) > 0

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        employees = doc.get("employees", [])
        actual_count = len(employees)

        declared_count = doc.get("employee_count")
        expected_count = doc.get_org("expected_employee_count")

        issues = []
        evidence = []

        if declared_count is not None:
            declared_count = int(declared_count)
            if actual_count != declared_count:
                issues.append(f"list count ({actual_count}) != declared count ({declared_count})")
                evidence.append(EvidenceItem(
                    evidence_type="comparison",
                    field_name="employee_count",
                    field_name_ar="عدد الموظفين المُعلن",
                    expected_value=str(declared_count),
                    actual_value=str(actual_count),
                    description=f"Payroll list has {actual_count} employees but header declares {declared_count}.",
                    description_ar=f"كشف الرواتب يحتوي على {actual_count} موظف لكن الرأسية تُعلن {declared_count}.",
                ))

        if expected_count is not None:
            expected_count = int(expected_count)
            variance = abs(actual_count - expected_count)
            variance_pct = (variance / expected_count * 100) if expected_count > 0 else 0
            tolerance_pct = float(self.get_config("headcount_tolerance_pct", 10.0))
            if variance_pct > tolerance_pct:
                issues.append(f"headcount {actual_count} deviates {variance_pct:.1f}% from org baseline {expected_count}")
                evidence.append(EvidenceItem(
                    evidence_type="comparison",
                    field_name="employee_count",
                    field_name_ar="عدد الموظفين",
                    expected_value=f"{expected_count} ± {tolerance_pct}%",
                    actual_value=str(actual_count),
                    description=f"Headcount {actual_count} deviates {variance_pct:.1f}% from expected {expected_count}.",
                    description_ar=f"عدد الموظفين {actual_count} ينحرف بنسبة {variance_pct:.1f}% عن المتوقع {expected_count}.",
                ))

        if issues:
            return self._fail(
                f"Employee headcount inconsistency: {'; '.join(issues)}.",
                f"تناقض في عدد الموظفين: {'; '.join(issues)}.",
                evidence=evidence,
            )
        return self._pass(
            f"Employee headcount ({actual_count}) is consistent.",
            f"عدد الموظفين ({actual_count}) متسق.",
        )


class PayrollPeriodOverlapRule(AuditRuleBase):
    """PAY-M06 — Two payroll sheets must not cover the same period for the same organization."""
    rule_code = "PAY-M06"
    rule_name_en = "Duplicate Payroll Period Detected"
    rule_name_ar = "تكرار فترة صرف رواتب"
    default_severity = "critical"
    rule_type = "compliance"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return bool(doc.get("payroll_period_start") and doc.get("payroll_period_end"))

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        try:
            from datetime import date as date_type, datetime
            from apps.documents.typed_models import PayrollSheet

            def _parse(val):
                if isinstance(val, date_type):
                    return val
                return datetime.fromisoformat(str(val)).date()

            period_start = _parse(doc.get("payroll_period_start"))
            period_end = _parse(doc.get("payroll_period_end"))
            org_id = doc.organization_id
            doc_id = doc.document_id

            if org_id is None:
                return self._not_applicable(
                    "No organization context — overlap check skipped.",
                    "لا يوجد سياق مؤسسي — تم تخطي فحص التداخل.",
                )

            overlapping = PayrollSheet.objects.filter(
                organization_id=org_id,
                payroll_period_start__lte=period_end,
                payroll_period_end__gte=period_start,
            ).exclude(pk=doc_id).values_list("pk", "payroll_period_start", "payroll_period_end")

            overlapping = list(overlapping)

            if overlapping:
                overlap_details = [
                    f"Sheet {pk}: {s} to {e}" for pk, s, e in overlapping[:3]
                ]
                return self._fail(
                    f"Payroll period {period_start} – {period_end} overlaps with {len(overlapping)} "
                    f"existing sheet(s): {', '.join(overlap_details)}. Double-payment risk.",
                    f"فترة الرواتب {period_start} – {period_end} تتداخل مع {len(overlapping)} "
                    f"كشف موجود: {', '.join(overlap_details)}. خطر صرف مزدوج.",
                    evidence=[EvidenceItem(
                        evidence_type="reference",
                        field_name="payroll_period",
                        field_name_ar="فترة الرواتب",
                        expected_value="No overlap with existing periods",
                        actual_value=overlap_details,
                        description=f"Period {period_start}–{period_end} conflicts with {len(overlapping)} payroll sheet(s).",
                        description_ar=f"الفترة {period_start}–{period_end} تتعارض مع {len(overlapping)} كشف رواتب.",
                    )]
                )
            return self._pass(
                f"Payroll period {period_start} – {period_end} has no overlaps.",
                f"فترة الرواتب {period_start} – {period_end} لا تتداخل مع أي كشف آخر.",
            )
        except Exception as e:
            return self._error(e)
