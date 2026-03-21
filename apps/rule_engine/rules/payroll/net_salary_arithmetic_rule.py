"""PAY-M04: Net Salary Arithmetic + PAY-M11: Duplicate Employee IDs"""
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
