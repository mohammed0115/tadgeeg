"""
Document Validators — Rules for all 7 Financial Document Types
==============================================================
Each validator returns:
  {
    "rules_passed": int,
    "rules_failed": int,
    "validation_score": float,  # 0-100
    "risk_level": str,          # low|medium|high|critical
    "failed_rule_codes": list,
    "passed_rule_codes": list,
    "rule_details": list,       # [{code, name, passed, message, severity}]
  }
"""

from decimal import Decimal, InvalidOperation
from datetime import date, timedelta


# ── Shared helpers ─────────────────────────────────────────────────────────────

SEVERITY_WEIGHTS = {"critical": 25, "high": 15, "medium": 8, "low": 3}

def _rule(code, name, passed, message, severity="medium"):
    return {"code": code, "name": name, "passed": passed, "message": message, "severity": severity}

def _score(rules):
    total  = sum(SEVERITY_WEIGHTS[r["severity"]] for r in rules)
    passed = sum(SEVERITY_WEIGHTS[r["severity"]] for r in rules if r["passed"])
    score  = round((passed / total) * 100, 1) if total else 100.0
    return score

def _risk(score):
    if score >= 85: return "low"
    if score >= 70: return "medium"
    if score >= 50: return "high"
    return "critical"

def _compile(rules):
    score = _score(rules)
    return {
        "rules_passed":     sum(1 for r in rules if r["passed"]),
        "rules_failed":     sum(1 for r in rules if not r["passed"]),
        "validation_score": score,
        "risk_level":       _risk(score),
        "failed_rule_codes":[r["code"] for r in rules if not r["passed"]],
        "passed_rule_codes":[r["code"] for r in rules if r["passed"]],
        "rule_details":     rules,
    }

def _dec(v, default=Decimal("0")):
    try: return Decimal(str(v))
    except (InvalidOperation, TypeError): return default


# ══════════════════════════════════════════════════════════════════════════════
# 1. PURCHASE ORDER  — PO-001 to PO-010
# ══════════════════════════════════════════════════════════════════════════════

def validate_purchase_order(po) -> dict:
    rules = []

    # PO-001 — PO number present
    rules.append(_rule("PO-001", "رقم أمر الشراء موجود",
        bool(po.po_number),
        "رقم أمر الشراء مفقود" if not po.po_number else "رقم أمر الشراء موجود",
        "high"))

    # PO-002 — PO date valid
    rules.append(_rule("PO-002", "تاريخ أمر الشراء صحيح",
        bool(po.po_date) and po.po_date <= date.today(),
        "تاريخ أمر الشراء غير صحيح أو في المستقبل" if not po.po_date or po.po_date > date.today() else "التاريخ صحيح",
        "high"))

    # PO-003 — Vendor name present
    rules.append(_rule("PO-003", "اسم المورد موجود",
        bool(po.vendor_name),
        "اسم المورد مفقود" if not po.vendor_name else "اسم المورد موجود",
        "high"))

    # PO-004 — Vendor VAT number
    vat_ok = bool(po.vendor_vat_number) and len(po.vendor_vat_number) == 15
    rules.append(_rule("PO-004", "رقم ضريبي للمورد صحيح",
        vat_ok,
        "رقم الضريبي للمورد مفقود أو غير صحيح (يجب 15 رقم)" if not vat_ok else "الرقم الضريبي صحيح",
        "critical"))

    # PO-005 — VAT calculation (15%)
    subtotal = _dec(po.subtotal)
    vat      = _dec(po.vat_amount)
    total    = _dec(po.total_amount)
    vat_expected = (subtotal * Decimal("0.15")).quantize(Decimal("0.01"))
    vat_ok2 = abs(vat - vat_expected) <= Decimal("1.00")
    rules.append(_rule("PO-005", "حساب ضريبة القيمة المضافة صحيح (15%)",
        vat_ok2,
        f"الضريبة المحسوبة {vat_expected} ≠ المذكورة {vat}" if not vat_ok2 else "حساب الضريبة صحيح",
        "critical"))

    # PO-006 — Total = subtotal + VAT
    total_expected = subtotal + vat
    total_ok = abs(total - total_expected) <= Decimal("1.00")
    rules.append(_rule("PO-006", "الإجمالي = المبلغ قبل الضريبة + الضريبة",
        total_ok,
        f"الإجمالي {total} لا يساوي {total_expected}" if not total_ok else "الإجمالي صحيح",
        "critical"))

    # PO-007 — Within budget
    within_budget = not po.budget_limit or total <= _dec(po.budget_limit)
    rules.append(_rule("PO-007", "المبلغ ضمن الميزانية المعتمدة",
        within_budget,
        f"المبلغ {total} يتجاوز حد الميزانية {po.budget_limit}" if not within_budget else "ضمن الميزانية",
        "high"))

    # PO-008 — Has approver
    rules.append(_rule("PO-008", "يوجد موافق على الأمر",
        po.approved_by is not None or po.approval_status in ["approved", "received"],
        "لا يوجد موافق على أمر الشراء",
        "high"))

    # PO-009 — No price discrepancy vs invoice
    rules.append(_rule("PO-009", "لا يوجد فرق في الأسعار مع الفاتورة",
        not po.has_price_discrepancy,
        f"فارق الأسعار مع الفاتورة: {po.price_discrepancy_pct:.1f}%" if po.has_price_discrepancy else "الأسعار متطابقة",
        "high"))

    # PO-010 — Cost center present
    rules.append(_rule("PO-010", "مركز التكلفة موجود",
        bool(po.cost_center),
        "مركز التكلفة مفقود" if not po.cost_center else "مركز التكلفة موجود",
        "medium"))

    return _compile(rules)


# ══════════════════════════════════════════════════════════════════════════════
# 2. BANK STATEMENT  — BNK-001 to BNK-009
# ══════════════════════════════════════════════════════════════════════════════

def validate_bank_statement(stmt) -> dict:
    rules = []

    # BNK-001 — Balance reconciled
    rules.append(_rule("BNK-001", "تطابق رصيد الختام",
        stmt.balance_matches,
        f"رصيد الختام المحسوب {stmt.calculated_closing} لا يتطابق مع المُعلَن {stmt.closing_balance}" if not stmt.balance_matches else "الرصيد متطابق",
        "critical"))

    # BNK-002 — No unusually large transactions
    rules.append(_rule("BNK-002", "لا توجد معاملات كبيرة غير مبررة",
        stmt.large_tx_count == 0,
        f"يوجد {stmt.large_tx_count} معاملة كبيرة تستوجب المراجعة" if stmt.large_tx_count else "لا توجد معاملات مشبوهة",
        "high"))

    # BNK-003 — No duplicate transactions
    rules.append(_rule("BNK-003", "لا توجد معاملات مكررة",
        stmt.duplicate_tx_count == 0,
        f"يوجد {stmt.duplicate_tx_count} معاملة مكررة" if stmt.duplicate_tx_count else "لا توجد تكرارات",
        "critical"))

    # BNK-004 — Benford's Law
    benford_ok = stmt.benford_deviation <= 0.015
    rules.append(_rule("BNK-004", "توزيع المبالغ يتوافق مع قانون بنفورد",
        benford_ok,
        f"انحراف بنفورد {stmt.benford_deviation:.4f} — محتمل تلاعب في المبالغ" if not benford_ok else "التوزيع طبيعي",
        "high"))

    # BNK-005 — Round amounts
    round_ok = stmt.round_amount_count <= max(3, stmt.transaction_count * 0.15)
    rules.append(_rule("BNK-005", "نسبة المبالغ المدوّرة معقولة",
        round_ok,
        f"{stmt.round_amount_count} معاملة بمبالغ مدوّرة — قد تشير إلى تلاعب" if not round_ok else "نسبة طبيعية",
        "medium"))

    # BNK-006 — Weekend transactions
    rules.append(_rule("BNK-006", "لا توجد معاملات في عطل نهاية الأسبوع",
        stmt.weekend_tx_count == 0,
        f"{stmt.weekend_tx_count} معاملة في عطلة — تستوجب المراجعة" if stmt.weekend_tx_count else "لا معاملات في العطل",
        "medium"))

    # BNK-007 — Account number present
    rules.append(_rule("BNK-007", "رقم الحساب المصرفي موجود",
        bool(stmt.account_number),
        "رقم الحساب مفقود",
        "high"))

    # BNK-008 — Period complete
    period_ok = bool(stmt.statement_period_from) and bool(stmt.statement_period_to) and stmt.statement_period_from <= stmt.statement_period_to
    rules.append(_rule("BNK-008", "فترة الكشف محددة وصحيحة",
        period_ok,
        "فترة الكشف غير محددة أو غير صحيحة" if not period_ok else "الفترة محددة",
        "high"))

    # BNK-009 — IBAN valid format
    iban_ok = bool(stmt.iban) and len(stmt.iban) == 24 and stmt.iban.upper().startswith("SA")
    rules.append(_rule("BNK-009", "رقم IBAN سعودي صحيح",
        iban_ok,
        "رقم IBAN مفقود أو غير صحيح (يجب SA + 22 رقم)" if not iban_ok else "IBAN صحيح",
        "medium"))

    return _compile(rules)


# ══════════════════════════════════════════════════════════════════════════════
# 3. PAYROLL SHEET  — PAY-001 to PAY-009
# ══════════════════════════════════════════════════════════════════════════════

def validate_payroll(payroll) -> dict:
    rules = []

    # PAY-001 — No duplicate IDs
    rules.append(_rule("PAY-001", "لا يوجد تكرار في أرقام الهوية الوطنية",
        len(payroll.duplicate_employee_ids) == 0,
        f"تكرار في الهوية الوطنية: {', '.join(payroll.duplicate_employee_ids[:3])}" if payroll.duplicate_employee_ids else "لا تكرار في الهويات",
        "critical"))

    # PAY-002 — No ghost employees
    rules.append(_rule("PAY-002", "لا يوجد موظفون وهميون محتملون",
        len(payroll.ghost_employee_flags) == 0,
        f"يوجد {len(payroll.ghost_employee_flags)} موظف وهمي محتمل" if payroll.ghost_employee_flags else "لا موظفين وهميين",
        "critical"))

    # PAY-003 — Net salary calculation correct
    rules.append(_rule("PAY-003", "حساب صافي الراتب صحيح (إجمالي - الخصومات)",
        len(payroll.calculation_errors) == 0,
        f"{len(payroll.calculation_errors)} خطأ في حساب صافي الراتب" if payroll.calculation_errors else "الحسابات صحيحة",
        "critical"))

    # PAY-004 — GOSI present
    gosi_ok = _dec(payroll.total_gosi) > 0 or payroll.employee_count == 0
    rules.append(_rule("PAY-004", "التأمينات الاجتماعية (GOSI) موجودة",
        gosi_ok,
        "لا توجد اشتراكات تأمينات اجتماعية" if not gosi_ok else "التأمينات موجودة",
        "high"))

    # PAY-005 — No salary spikes
    rules.append(_rule("PAY-005", "لا توجد زيادات راتب مفاجئة (>30%)",
        len(payroll.salary_spike_flags) == 0,
        f"{len(payroll.salary_spike_flags)} موظف بزيادة راتب مفاجئة" if payroll.salary_spike_flags else "لا زيادات مشبوهة",
        "high"))

    # PAY-006 — Bank accounts present
    employees_with_bank = sum(1 for e in payroll.employees if e.get("bank_account"))
    has_banks = payroll.employee_count == 0 or employees_with_bank == payroll.employee_count
    rules.append(_rule("PAY-006", "جميع الموظفين لديهم حسابات بنكية",
        has_banks,
        f"{payroll.employee_count - employees_with_bank} موظف بدون حساب بنكي" if not has_banks else "جميع الحسابات موجودة",
        "medium"))

    # PAY-007 — Period valid
    period_ok = bool(payroll.payroll_period_from) and bool(payroll.payroll_period_to)
    rules.append(_rule("PAY-007", "فترة كشف الرواتب محددة",
        period_ok,
        "فترة كشف الرواتب غير محددة",
        "medium"))

    # PAY-008 — Totals match
    calc_gross = sum(_dec(e.get("gross", 0)) for e in payroll.employees)
    gross_ok = abs(calc_gross - _dec(payroll.total_gross_salary)) <= Decimal("1.00") or not payroll.employees
    rules.append(_rule("PAY-008", "الإجمالي يتطابق مع مجموع السجلات",
        gross_ok,
        f"الإجمالي المحسوب {calc_gross} لا يتطابق مع المُعلَن {payroll.total_gross_salary}" if not gross_ok else "الإجمالي متطابق",
        "high"))

    # PAY-009 — Employee count consistent
    count_ok = payroll.employee_count == len(payroll.employees) or not payroll.employees
    rules.append(_rule("PAY-009", "عدد الموظفين متسق",
        count_ok,
        f"عدد مُعلَن {payroll.employee_count} لا يتطابق مع {len(payroll.employees)} سجل" if not count_ok else "العدد متسق",
        "medium"))

    return _compile(rules)


# ══════════════════════════════════════════════════════════════════════════════
# 4. EXPENSE REPORT  — EXP-001 to EXP-008
# ══════════════════════════════════════════════════════════════════════════════

EXPENSE_LIMITS = {
    "meals":        500,
    "travel":       2000,
    "accommodation":1500,
    "other":        1000,
}

def validate_expense_report(report) -> dict:
    rules = []

    # EXP-001 — All receipts attached
    total_lines = len(report.expense_lines)
    rules.append(_rule("EXP-001", "جميع المصروفات مدعومة بإيصالات",
        report.missing_receipts_count == 0,
        f"{report.missing_receipts_count} مصروف بدون إيصال" if report.missing_receipts_count else "جميع الإيصالات مرفقة",
        "high"))

    # EXP-002 — No duplicate claims
    rules.append(_rule("EXP-002", "لا يوجد تكرار في المطالبات",
        len(report.duplicate_claims) == 0,
        f"{len(report.duplicate_claims)} مطالبة مكررة" if report.duplicate_claims else "لا تكرار",
        "critical"))

    # EXP-003 — Within policy limits
    rules.append(_rule("EXP-003", "المصروفات ضمن حدود السياسة",
        report.over_policy_limit_count == 0,
        f"{report.over_policy_limit_count} مصروف يتجاوز الحد المسموح" if report.over_policy_limit_count else "ضمن الحدود",
        "medium"))

    # EXP-004 — Has approver
    rules.append(_rule("EXP-004", "التقرير معتمد من مسؤول",
        report.approved_by is not None,
        "التقرير لم يُعتمد بعد",
        "high"))

    # EXP-005 — No split transactions
    rules.append(_rule("EXP-005", "لا يوجد تقسيم مشبوه للمصروفات",
        len(report.split_transaction_flags) == 0,
        f"{len(report.split_transaction_flags)} معاملة مقسّمة محتملة لتجاوز الحد" if report.split_transaction_flags else "لا تقسيم مشبوه",
        "high"))

    # EXP-006 — Valid dates
    date_ok = bool(report.report_period_from) and bool(report.report_period_to) and bool(report.submitted_date)
    rules.append(_rule("EXP-006", "التواريخ محددة وصحيحة",
        date_ok,
        "التواريخ غير مكتملة",
        "medium"))

    # EXP-007 — VAT calculation (when applicable)
    vat = _dec(report.vat_included)
    total = _dec(report.total_claimed)
    vat_ok = vat == Decimal("0") or abs(vat - (total - total / Decimal("1.15"))) <= Decimal("5")
    rules.append(_rule("EXP-007", "حساب ضريبة القيمة المضافة صحيح",
        vat_ok,
        "خطأ في حساب ضريبة القيمة المضافة للمصروفات",
        "medium"))

    # EXP-008 — Totals match
    calc_total = sum(_dec(e.get("amount", 0)) for e in report.expense_lines)
    totals_ok = abs(calc_total - _dec(report.total_claimed)) <= Decimal("1.00") or not report.expense_lines
    rules.append(_rule("EXP-008", "إجمالي المطالبة يتطابق مع مجموع السجلات",
        totals_ok,
        f"الإجمالي المحسوب {calc_total} لا يتطابق مع {report.total_claimed}",
        "high"))

    return _compile(rules)


# ══════════════════════════════════════════════════════════════════════════════
# 5. VAT RETURN  — VATR-001 to VATR-008
# ══════════════════════════════════════════════════════════════════════════════

def validate_vat_return(ret) -> dict:
    rules = []

    # VATR-001 — VAT number valid (15 digit SA format)
    vat_ok = bool(ret.vat_number) and len(ret.vat_number) == 15
    rules.append(_rule("VATR-001", "الرقم الضريبي للممول صحيح",
        vat_ok,
        "الرقم الضريبي مفقود أو لا يتكون من 15 رقم",
        "critical"))

    # VATR-002 — Output VAT = standard_rated_sales × 15%
    output_expected = (_dec(ret.standard_rated_sales) * Decimal("0.15")).quantize(Decimal("0.01"))
    output_ok = abs(_dec(ret.output_vat) - output_expected) <= Decimal("10")
    rules.append(_rule("VATR-002", "ضريبة المخرجات = المبيعات × 15%",
        output_ok,
        f"المحسوبة {output_expected} ≠ المُعلَنة {ret.output_vat}",
        "critical"))

    # VATR-003 — Input VAT calculation
    input_ok = _dec(ret.input_vat) >= Decimal("0")
    rules.append(_rule("VATR-003", "ضريبة المدخلات قيمة موجبة",
        input_ok,
        "ضريبة المدخلات بقيمة سالبة — يستوجب المراجعة",
        "high"))

    # VATR-004 — Net VAT = output - input
    net_expected = _dec(ret.output_vat) - _dec(ret.input_vat)
    net_ok = abs(_dec(ret.net_vat_payable) - net_expected) <= Decimal("10")
    rules.append(_rule("VATR-004", "صافي الضريبة المستحقة = مخرجات - مدخلات",
        net_ok,
        f"صافي محسوب {net_expected} ≠ مُعلَن {ret.net_vat_payable}",
        "critical"))

    # VATR-005 — No output discrepancy vs ledger
    rules.append(_rule("VATR-005", "لا يوجد فارق في ضريبة المخرجات",
        abs(_dec(ret.output_discrepancy)) <= Decimal("100"),
        f"فارق ضريبة المخرجات: {ret.output_discrepancy} ر.س",
        "high"))

    # VATR-006 — No input discrepancy
    rules.append(_rule("VATR-006", "لا يوجد فارق في ضريبة المدخلات",
        abs(_dec(ret.input_discrepancy)) <= Decimal("100"),
        f"فارق ضريبة المدخلات: {ret.input_discrepancy} ر.س",
        "high"))

    # VATR-007 — Filed on time
    rules.append(_rule("VATR-007", "الإقرار مقدَّم في الموعد المحدد",
        not ret.is_late_filing,
        f"الإقرار متأخر {ret.late_days} يوم عن الموعد المحدد" if ret.is_late_filing else "الإقرار في الوقت",
        "high"))

    # VATR-008 — Period complete
    period_ok = bool(ret.period_from) and bool(ret.period_to)
    rules.append(_rule("VATR-008", "فترة الإقرار محددة",
        period_ok,
        "فترة الإقرار الضريبي غير محددة",
        "medium"))

    return _compile(rules)


# ══════════════════════════════════════════════════════════════════════════════
# 6. FIXED ASSET LEDGER  — AST-001 to AST-009
# ══════════════════════════════════════════════════════════════════════════════

DEPRECIATION_RATES = {
    "buildings": (2, 5),
    "vehicles":  (20, 25),
    "equipment": (10, 25),
    "computers": (25, 33),
    "furniture": (10, 20),
    "land":      (0, 0),
    "other":     (5, 33),
}

def validate_fixed_assets(register) -> dict:
    rules = []

    # AST-001 — No negative book values
    rules.append(_rule("AST-001", "لا توجد قيم دفترية سالبة",
        register.negative_book_value_count == 0,
        f"{register.negative_book_value_count} أصل بقيمة دفترية سالبة" if register.negative_book_value_count else "لا قيم سالبة",
        "critical"))

    # AST-002 — No over-depreciation (accumulated > cost)
    rules.append(_rule("AST-002", "الإهلاك المتراكم لا يتجاوز التكلفة الأصلية",
        register.over_depreciated_count == 0,
        f"{register.over_depreciated_count} أصل بإهلاك متراكم يتجاوز تكلفته" if register.over_depreciated_count else "الإهلاك ضمن الحدود",
        "critical"))

    # AST-003 — Depreciation rates within range
    rules.append(_rule("AST-003", "معدلات الإهلاك ضمن النطاق المقبول",
        len(register.wrong_depreciation_rate) == 0,
        f"{len(register.wrong_depreciation_rate)} أصل بمعدل إهلاك خارج النطاق" if register.wrong_depreciation_rate else "المعدلات صحيحة",
        "high"))

    # AST-004 — No duplicate asset IDs
    rules.append(_rule("AST-004", "لا تكرار في أرقام الأصول",
        register.duplicate_asset_id_count == 0,
        f"{register.duplicate_asset_id_count} رقم أصل مكرر" if register.duplicate_asset_id_count else "لا تكرار",
        "high"))

    # AST-005 — All assets have IDs
    rules.append(_rule("AST-005", "جميع الأصول لها أرقام تعريفية",
        register.missing_asset_id_count == 0,
        f"{register.missing_asset_id_count} أصل بدون رقم تعريفي",
        "medium"))

    # AST-006 — Book value = cost - accumulated depreciation
    errors = []
    for a in register.assets:
        cost = _dec(a.get("cost", 0))
        acc  = _dec(a.get("accumulated_depreciation", 0))
        bv   = _dec(a.get("book_value", 0))
        expected_bv = cost - acc
        if abs(bv - expected_bv) > Decimal("1"):
            errors.append(a.get("asset_id", "?"))
    rules.append(_rule("AST-006", "القيمة الدفترية = التكلفة - الإهلاك المتراكم",
        len(errors) == 0,
        f"{len(errors)} أصل بخطأ في القيمة الدفترية: {errors[:3]}" if errors else "الحسابات صحيحة",
        "critical"))

    # AST-007 — Useful life reasonable (3-50 years)
    bad_life = [a.get("asset_id","?") for a in register.assets
                if a.get("useful_life_years") and not (3 <= a["useful_life_years"] <= 50)
                and a.get("category","") != "land"]
    rules.append(_rule("AST-007", "العمر الإنتاجي للأصول معقول (3-50 سنة)",
        len(bad_life) == 0,
        f"{len(bad_life)} أصل بعمر إنتاجي غير معقول",
        "medium"))

    # AST-008 — Totals consistent
    calc_cost = sum(_dec(a.get("cost", 0)) for a in register.assets)
    totals_ok = abs(calc_cost - _dec(register.total_cost)) <= Decimal("10") or not register.assets
    rules.append(_rule("AST-008", "إجمالي التكاليف متسق مع السجلات",
        totals_ok,
        f"إجمالي محسوب {calc_cost} ≠ مُعلَن {register.total_cost}",
        "high"))

    # AST-009 — Purchase dates valid
    bad_dates = [a.get("asset_id","?") for a in register.assets
                 if a.get("purchase_date") and str(a["purchase_date"]) > str(date.today())]
    rules.append(_rule("AST-009", "تواريخ الشراء صحيحة وغير مستقبلية",
        len(bad_dates) == 0,
        f"{len(bad_dates)} أصل بتاريخ شراء مستقبلي",
        "medium"))

    return _compile(rules)


# ══════════════════════════════════════════════════════════════════════════════
# 7. SALES RECEIPT  — REC-001 to REC-008
# ══════════════════════════════════════════════════════════════════════════════

def validate_sales_receipt(receipt) -> dict:
    rules = []

    # REC-001 — Receipt number
    rules.append(_rule("REC-001", "رقم الإيصال موجود",
        bool(receipt.receipt_number),
        "رقم الإيصال مفقود",
        "high"))

    # REC-002 — Receipt date
    date_ok = bool(receipt.receipt_date) and receipt.receipt_date <= date.today()
    rules.append(_rule("REC-002", "تاريخ الإيصال صحيح",
        date_ok,
        "تاريخ الإيصال مفقود أو في المستقبل",
        "high"))

    # REC-003 — VAT rate 15%
    rules.append(_rule("REC-003", "معدل ضريبة القيمة المضافة = 15%",
        abs(_dec(receipt.vat_rate) - Decimal("15")) < Decimal("0.01"),
        f"معدل الضريبة {receipt.vat_rate}% ≠ 15%",
        "critical"))

    # REC-004 — VAT calculation correct
    subtotal = _dec(receipt.subtotal)
    vat = _dec(receipt.vat_amount)
    total = _dec(receipt.total_amount)
    vat_expected = (subtotal * Decimal("0.15")).quantize(Decimal("0.01"))
    vat_ok = abs(vat - vat_expected) <= Decimal("1")
    rules.append(_rule("REC-004", "مبلغ الضريبة = المبلغ قبل الضريبة × 15%",
        vat_ok,
        f"الضريبة المحسوبة {vat_expected} ≠ المذكورة {vat}",
        "critical"))

    # REC-005 — QR code present
    rules.append(_rule("REC-005", "رمز QR الزاتكا موجود",
        receipt.has_qr_code,
        "رمز QR مفقود — مطلوب لإيصالات المستهلك",
        "high"))

    # REC-006 — QR code valid
    rules.append(_rule("REC-006", "رمز QR صحيح ويطابق بيانات الإيصال",
        receipt.qr_code_valid,
        "رمز QR غير صحيح أو لا يطابق بيانات الإيصال",
        "critical"))

    # REC-007 — Not a duplicate
    rules.append(_rule("REC-007", "الإيصال غير مكرر",
        not receipt.is_duplicate,
        "إيصال مكرر — يوجد إيصال سابق بنفس الرقم أو المبلغ والتاريخ",
        "critical"))

    # REC-008 — Seller VAT number present
    rules.append(_rule("REC-008", "الرقم الضريبي للبائع موجود",
        bool(receipt.seller_vat_number),
        "الرقم الضريبي للبائع مفقود",
        "critical"))

    return _compile(rules)


# ── Public router ─────────────────────────────────────────────────────────────

VALIDATORS = {
    "purchase_order": validate_purchase_order,
    "bank_statement": validate_bank_statement,
    "payroll":        validate_payroll,
    "expense_report": validate_expense_report,
    "vat_return":     validate_vat_return,
    "fixed_asset":    validate_fixed_assets,
    "sales_receipt":  validate_sales_receipt,
}

# Phase-3 additions: pull in the 15 new doc-type validators and merge them
# into the public dispatch. The lazy import + try/except keeps the original
# module loadable even if v2 is absent (e.g. partial deployment).
try:
    from .doc_validators_v2 import VALIDATORS_V2  # noqa: E402
    VALIDATORS.update(VALIDATORS_V2)
    # Aliases — same business doc, different conventional name
    VALIDATORS.setdefault("payment", VALIDATORS["payment_voucher"])
    VALIDATORS.setdefault("tax_vat_document", VALIDATORS["vat_return"])
    # GRN is registered as "grn" in V2; the rest of the codebase uses the
    # long form. Alias both ways so any caller resolves correctly.
    VALIDATORS.setdefault("goods_receipt_note", VALIDATORS["grn"])
    VALIDATORS.setdefault("invoice", VALIDATORS["sales_invoice"])  # canonical Invoice → SI rules
except ImportError:  # pragma: no cover — defensive
    pass


def run_document_validation(doc_type: str, document_obj) -> dict:
    """Route to the correct validator by document type."""
    validator = VALIDATORS.get(doc_type)
    if not validator:
        raise ValueError(f"No validator for document type: {doc_type}")
    return validator(document_obj)
