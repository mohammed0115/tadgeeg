"""Validation Service — validate financial consistency from extracted AI data."""

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


class ValidationService:
    """Validate financial consistency from extracted AI data."""

    REQUIRED_FIELDS = {
        "purchase_order": ["po_number", "vendor_name", "total_amount"],
        "bank_statement": ["account_number", "opening_balance", "closing_balance"],
        "payroll": ["company_name", "total_net_salary", "employees"],
        "expense_report": ["employee_or_department", "total_expense"],
        "vat_return": ["vat_number", "net_vat_payable"],
        "fixed_asset": ["asset_name", "acquisition_cost", "net_book_value"],
        "sales_receipt": ["receipt_number", "total_amount"],
        "invoice": ["document_number", "total_amount"],
        "other": [],
    }

    TOLERANCE = 0.02  # 2 cents tolerance for floating-point comparisons

    def validate(self, doc_type: str, extracted_data: dict) -> list:
        """
        Run all relevant validation checks for the given document type.
        Returns list of {check, status, details} dicts.
        """
        if not extracted_data:
            return [{"check": "data_available", "status": "fail", "details": "No data was extracted."}]

        findings = []

        # Always run required fields check
        findings.extend(self._validate_required_fields(doc_type, extracted_data))

        # Always run date validation
        findings.extend(self._validate_dates(extracted_data))

        # Type-specific checks
        type_validators = {
            "bank_statement": self._validate_bank_statement,
            "payroll": self._validate_payroll,
            "expense_report": self._validate_expense_report,
            "purchase_order": self._validate_totals,
            "invoice": self._validate_totals,
            "sales_receipt": self._validate_totals,
            "vat_return": self._validate_vat_return,
            "fixed_asset": self._validate_fixed_asset,
        }

        validator_fn = type_validators.get(doc_type)
        if validator_fn:
            findings.extend(validator_fn(extracted_data))

        return findings

    def _validate_required_fields(self, doc_type: str, data: dict) -> list:
        """Check that required fields are present and non-null."""
        required = self.REQUIRED_FIELDS.get(doc_type, [])
        findings = []
        for field in required:
            value = data.get(field)
            if value is None or value == "" or value == [] or value == {}:
                findings.append({
                    "check": f"required_field_{field}",
                    "status": "fail",
                    "details": f"الحقل المطلوب '{field}' مفقود أو فارغ.",
                })
            else:
                findings.append({
                    "check": f"required_field_{field}",
                    "status": "pass",
                    "details": "",
                })
        return findings

    def _validate_totals(self, data: dict) -> list:
        """Validate that line item totals match the stated total."""
        findings = []
        line_items = data.get("line_items", [])
        if not line_items:
            findings.append({
                "check": "line_items_present",
                "status": "warning",
                "details": "لا توجد بنود تفصيلية للتحقق من الإجمالي.",
            })
            return findings

        computed_subtotal = 0.0
        for item in line_items:
            if not isinstance(item, dict):
                continue
            qty = self._to_float(item.get("qty", 1))
            unit_price = self._to_float(item.get("unit_price", 0))
            item_total = self._to_float(item.get("total", 0))

            # Validate qty × price = item total
            expected = qty * unit_price
            if item_total and abs(expected - item_total) > self.TOLERANCE and expected > 0:
                findings.append({
                    "check": "line_item_arithmetic",
                    "status": "fail",
                    "details": (
                        f"بند '{item.get('description', '')}': "
                        f"الكمية ({qty}) × السعر ({unit_price}) = {expected:.2f} "
                        f"لا يساوي الإجمالي المذكور ({item_total:.2f})."
                    ),
                })
            computed_subtotal += item_total if item_total else expected

        stated_subtotal = self._to_float(data.get("subtotal", 0))
        stated_total = self._to_float(data.get("total_amount", 0))
        vat_amount = self._to_float(data.get("vat_amount", 0))

        if stated_subtotal and abs(computed_subtotal - stated_subtotal) > self.TOLERANCE:
            findings.append({
                "check": "subtotal_matches_line_items",
                "status": "fail",
                "details": (
                    f"مجموع البنود ({computed_subtotal:.2f}) لا يتطابق مع "
                    f"الإجمالي الفرعي المذكور ({stated_subtotal:.2f})."
                ),
            })
        else:
            findings.append({
                "check": "subtotal_matches_line_items",
                "status": "pass",
                "details": "",
            })

        if stated_total and stated_subtotal and vat_amount:
            expected_total = stated_subtotal + vat_amount
            if abs(expected_total - stated_total) > self.TOLERANCE:
                findings.append({
                    "check": "total_amount_correct",
                    "status": "fail",
                    "details": (
                        f"الإجمالي الفرعي ({stated_subtotal:.2f}) + ضريبة القيمة المضافة "
                        f"({vat_amount:.2f}) = {expected_total:.2f} لا يتطابق مع "
                        f"الإجمالي الكلي ({stated_total:.2f})."
                    ),
                })
            else:
                findings.append({
                    "check": "total_amount_correct",
                    "status": "pass",
                    "details": "",
                })

        # Validate VAT rate (15% standard for Saudi Arabia)
        if vat_amount and stated_subtotal and stated_subtotal > 0:
            actual_rate = (vat_amount / stated_subtotal) * 100
            if abs(actual_rate - 15.0) > 0.5:
                findings.append({
                    "check": "vat_rate_15_percent",
                    "status": "warning",
                    "details": (
                        f"معدل ضريبة القيمة المضافة المحسوب ({actual_rate:.1f}%) "
                        f"يختلف عن المعدل القياسي (15%)."
                    ),
                })
            else:
                findings.append({
                    "check": "vat_rate_15_percent",
                    "status": "pass",
                    "details": "",
                })

        return findings

    def _validate_bank_statement(self, data: dict) -> list:
        """Validate bank statement balance arithmetic."""
        findings = []
        opening = self._to_float(data.get("opening_balance"))
        closing = self._to_float(data.get("closing_balance"))
        total_credits = self._to_float(data.get("total_credits"))
        total_debits = self._to_float(data.get("total_debits"))

        if opening is None or closing is None:
            findings.append({
                "check": "balance_arithmetic",
                "status": "not_applicable",
                "details": "الرصيد الافتتاحي أو الختامي غير موجود.",
            })
            return findings

        if total_credits is not None and total_debits is not None:
            expected_closing = opening + total_credits - total_debits
            if abs(expected_closing - closing) > self.TOLERANCE:
                findings.append({
                    "check": "balance_arithmetic",
                    "status": "fail",
                    "details": (
                        f"الرصيد الافتتاحي ({opening:.2f}) + الإيداعات ({total_credits:.2f}) "
                        f"- السحوبات ({total_debits:.2f}) = {expected_closing:.2f} "
                        f"لا يتطابق مع الرصيد الختامي ({closing:.2f})."
                    ),
                })
            else:
                findings.append({
                    "check": "balance_arithmetic",
                    "status": "pass",
                    "details": "",
                })
        else:
            findings.append({
                "check": "balance_arithmetic",
                "status": "warning",
                "details": "إجمالي الإيداعات أو السحوبات غير متوفر للتحقق من الرصيد.",
            })

        # Validate transaction running balances
        transactions = data.get("transactions", [])
        if transactions and isinstance(transactions, list):
            prev_balance = opening
            errors = 0
            for txn in transactions:
                if not isinstance(txn, dict):
                    continue
                debit = self._to_float(txn.get("debit", 0)) or 0.0
                credit = self._to_float(txn.get("credit", 0)) or 0.0
                stated_balance = self._to_float(txn.get("balance"))
                if stated_balance is not None:
                    expected_bal = prev_balance - debit + credit
                    if abs(expected_bal - stated_balance) > self.TOLERANCE:
                        errors += 1
                    prev_balance = stated_balance

            if errors > 0:
                findings.append({
                    "check": "transaction_running_balance",
                    "status": "fail",
                    "details": f"تم اكتشاف {errors} خطأ في أرصدة المعاملات التسلسلية.",
                })
            elif transactions:
                findings.append({
                    "check": "transaction_running_balance",
                    "status": "pass",
                    "details": "",
                })

        return findings

    def _validate_payroll(self, data: dict) -> list:
        """Validate payroll totals and employee-level arithmetic."""
        findings = []
        employees = data.get("employees", [])
        total_gross = self._to_float(data.get("total_gross_salary"))
        total_deductions = self._to_float(data.get("total_deductions"))
        total_net = self._to_float(data.get("total_net_salary"))
        stated_count = data.get("employee_count")

        if not employees:
            findings.append({
                "check": "employee_list_present",
                "status": "warning",
                "details": "قائمة الموظفين غير موجودة للتحقق.",
            })
            return findings

        # Validate employee count
        actual_count = len(employees)
        if stated_count is not None and int(stated_count) != actual_count:
            findings.append({
                "check": "employee_count_match",
                "status": "fail",
                "details": (
                    f"عدد الموظفين المذكور ({stated_count}) لا يتطابق "
                    f"مع عدد السجلات ({actual_count})."
                ),
            })
        else:
            findings.append({
                "check": "employee_count_match",
                "status": "pass" if stated_count else "not_applicable",
                "details": "",
            })

        # Validate individual net salaries
        computed_total_net = 0.0
        errors = 0
        for emp in employees:
            if not isinstance(emp, dict):
                continue
            basic = self._to_float(emp.get("basic_salary", 0)) or 0.0
            allowances = self._to_float(emp.get("allowances", 0)) or 0.0
            deductions = self._to_float(emp.get("deductions", 0)) or 0.0
            net = self._to_float(emp.get("net_salary", 0)) or 0.0
            gross = basic + allowances
            expected_net = gross - deductions
            if net and abs(expected_net - net) > self.TOLERANCE:
                errors += 1
            computed_total_net += net

        if errors > 0:
            findings.append({
                "check": "employee_net_salary_arithmetic",
                "status": "fail",
                "details": f"{errors} موظف لديهم خطأ في حساب صافي الراتب.",
            })
        else:
            findings.append({
                "check": "employee_net_salary_arithmetic",
                "status": "pass",
                "details": "",
            })

        # Validate total net salary
        if total_net and computed_total_net and abs(total_net - computed_total_net) > self.TOLERANCE:
            findings.append({
                "check": "total_net_salary_match",
                "status": "fail",
                "details": (
                    f"مجموع صافي رواتب الموظفين ({computed_total_net:.2f}) "
                    f"لا يتطابق مع الإجمالي المذكور ({total_net:.2f})."
                ),
            })
        elif total_net:
            findings.append({
                "check": "total_net_salary_match",
                "status": "pass",
                "details": "",
            })

        # Validate gross - deductions = net at aggregate level
        if total_gross and total_deductions and total_net:
            expected_net = total_gross - total_deductions
            if abs(expected_net - total_net) > self.TOLERANCE:
                findings.append({
                    "check": "gross_minus_deductions_equals_net",
                    "status": "fail",
                    "details": (
                        f"إجمالي الرواتب ({total_gross:.2f}) - إجمالي الخصومات "
                        f"({total_deductions:.2f}) = {expected_net:.2f} "
                        f"لا يتطابق مع إجمالي صافي الرواتب ({total_net:.2f})."
                    ),
                })
            else:
                findings.append({
                    "check": "gross_minus_deductions_equals_net",
                    "status": "pass",
                    "details": "",
                })

        return findings

    def _validate_expense_report(self, data: dict) -> list:
        """Validate expense report line item totals."""
        findings = []
        line_items = data.get("line_items", [])
        total_expense = self._to_float(data.get("total_expense"))

        if not line_items:
            findings.append({
                "check": "line_items_present",
                "status": "warning",
                "details": "لا توجد بنود تفصيلية للمصروفات.",
            })
            return findings

        computed_total = sum(
            self._to_float(item.get("amount", 0)) or 0.0
            for item in line_items
            if isinstance(item, dict)
        )

        if total_expense and abs(computed_total - total_expense) > self.TOLERANCE:
            findings.append({
                "check": "expense_total_matches_line_items",
                "status": "fail",
                "details": (
                    f"مجموع بنود المصروفات ({computed_total:.2f}) لا يتطابق "
                    f"مع الإجمالي المذكور ({total_expense:.2f})."
                ),
            })
        else:
            findings.append({
                "check": "expense_total_matches_line_items",
                "status": "pass",
                "details": "",
            })

        # Check for negative expenses
        negative = [i for i in line_items if isinstance(i, dict) and (self._to_float(i.get("amount", 0)) or 0.0) < 0]
        if negative:
            findings.append({
                "check": "no_negative_expenses",
                "status": "warning",
                "details": f"تم اكتشاف {len(negative)} بند مصروف بقيمة سالبة.",
            })

        return findings

    def _validate_dates(self, data: dict) -> list:
        """Check for date consistency across common date fields."""
        findings = []

        date_pairs = [
            ("issue_date", "due_date", "تاريخ الإصدار يجب أن يكون قبل تاريخ الاستحقاق"),
            ("period_from", "period_to", "تاريخ بداية الفترة يجب أن يكون قبل تاريخ النهاية"),
            ("acquisition_date", "due_date", None),
        ]

        for start_field, end_field, message in date_pairs:
            start_val = data.get(start_field)
            end_val = data.get(end_field)
            if not start_val or not end_val:
                continue
            try:
                start_dt = datetime.fromisoformat(str(start_val))
                end_dt = datetime.fromisoformat(str(end_val))
                if start_dt > end_dt:
                    msg = message or f"'{start_field}' يجب أن يكون قبل '{end_field}'"
                    findings.append({
                        "check": f"date_order_{start_field}_{end_field}",
                        "status": "fail",
                        "details": msg,
                    })
                else:
                    findings.append({
                        "check": f"date_order_{start_field}_{end_field}",
                        "status": "pass",
                        "details": "",
                    })
            except (ValueError, TypeError):
                pass  # Date format unrecognized, skip

        return findings

    def _validate_vat_return(self, data: dict) -> list:
        """Validate VAT return arithmetic."""
        findings = []

        output_vat = self._to_float(data.get("output_vat"))
        input_vat = self._to_float(data.get("input_vat"))
        net_vat = self._to_float(data.get("net_vat_payable"))

        if output_vat is not None and input_vat is not None and net_vat is not None:
            expected_net = output_vat - input_vat
            if abs(expected_net - net_vat) > self.TOLERANCE:
                findings.append({
                    "check": "net_vat_arithmetic",
                    "status": "fail",
                    "details": (
                        f"ضريبة المخرجات ({output_vat:.2f}) - ضريبة المدخلات ({input_vat:.2f}) "
                        f"= {expected_net:.2f} لا يتطابق مع صافي الضريبة المستحقة ({net_vat:.2f})."
                    ),
                })
            else:
                findings.append({
                    "check": "net_vat_arithmetic",
                    "status": "pass",
                    "details": "",
                })

        vat_number = data.get("vat_number", "")
        if vat_number:
            # Saudi VAT number is 15 digits
            clean = str(vat_number).replace("-", "").replace(" ", "")
            if len(clean) == 15 and clean.isdigit():
                findings.append({
                    "check": "vat_number_format",
                    "status": "pass",
                    "details": "",
                })
            else:
                findings.append({
                    "check": "vat_number_format",
                    "status": "warning",
                    "details": f"الرقم الضريبي '{vat_number}' لا يتطابق مع تنسيق الـ 15 رقماً السعودي.",
                })

        return findings

    def _validate_fixed_asset(self, data: dict) -> list:
        """Validate fixed asset net book value."""
        findings = []
        cost = self._to_float(data.get("acquisition_cost"))
        accum_dep = self._to_float(data.get("accumulated_depreciation"))
        nbv = self._to_float(data.get("net_book_value"))

        if cost and accum_dep is not None and nbv is not None:
            expected_nbv = cost - accum_dep
            if abs(expected_nbv - nbv) > self.TOLERANCE:
                findings.append({
                    "check": "net_book_value_arithmetic",
                    "status": "fail",
                    "details": (
                        f"تكلفة الاقتناء ({cost:.2f}) - الاستهلاك المتراكم ({accum_dep:.2f}) "
                        f"= {expected_nbv:.2f} لا يتطابق مع القيمة الدفترية ({nbv:.2f})."
                    ),
                })
            else:
                findings.append({
                    "check": "net_book_value_arithmetic",
                    "status": "pass",
                    "details": "",
                })

            if accum_dep > cost:
                findings.append({
                    "check": "accumulated_depreciation_reasonable",
                    "status": "warning",
                    "details": "الاستهلاك المتراكم يتجاوز تكلفة الاقتناء.",
                })

        return findings

    @staticmethod
    def _to_float(value: Any) -> float | None:
        """Safely convert value to float, return None if impossible."""
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            # Remove currency symbols and commas
            cleaned = value.replace(",", "").replace("SAR", "").replace("ر.س", "").strip()
            try:
                return float(cleaned)
            except ValueError:
                return None
        return None
