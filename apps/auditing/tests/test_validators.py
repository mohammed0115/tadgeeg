"""Edge case tests for ValidationService."""

from django.test import TestCase

from apps.auditing.services.validation_service import ValidationService


class ValidationServiceEdgeCaseTests(TestCase):
    """Edge cases for ValidationService."""

    def setUp(self):
        self.validator = ValidationService()

    # ─── _to_float ───────────────────────────────────────────

    def test_to_float_integer(self):
        self.assertEqual(ValidationService._to_float(100), 100.0)

    def test_to_float_float(self):
        self.assertAlmostEqual(ValidationService._to_float(3.14), 3.14)

    def test_to_float_string_with_commas(self):
        self.assertAlmostEqual(ValidationService._to_float("1,500.00"), 1500.0)

    def test_to_float_string_with_sar(self):
        self.assertAlmostEqual(ValidationService._to_float("1500.00 SAR"), 1500.0)

    def test_to_float_none_returns_none(self):
        self.assertIsNone(ValidationService._to_float(None))

    def test_to_float_invalid_string_returns_none(self):
        self.assertIsNone(ValidationService._to_float("not_a_number"))

    # ─── Invoice / totals validation ─────────────────────────

    def test_invoice_correct_vat_passes(self):
        data = {
            "document_number": "INV-001",
            "total_amount": 1150.0,
            "line_items": [
                {"description": "Service", "qty": 1, "unit_price": 1000.0, "total": 1000.0}
            ],
            "subtotal": 1000.0,
            "vat_amount": 150.0,
        }
        findings = self.validator.validate("invoice", data)
        vat_check = next((f for f in findings if f["check"] == "vat_rate_15_percent"), None)
        self.assertIsNotNone(vat_check)
        self.assertEqual(vat_check["status"], "pass")

    def test_invoice_wrong_vat_rate_warns(self):
        data = {
            "document_number": "INV-002",
            "total_amount": 1050.0,
            "line_items": [
                {"description": "Service", "qty": 1, "unit_price": 1000.0, "total": 1000.0}
            ],
            "subtotal": 1000.0,
            "vat_amount": 50.0,  # 5% — wrong for Saudi Arabia
        }
        findings = self.validator.validate("invoice", data)
        vat_check = next((f for f in findings if f["check"] == "vat_rate_15_percent"), None)
        self.assertIsNotNone(vat_check)
        self.assertEqual(vat_check["status"], "warning")

    def test_invoice_total_mismatch_fails(self):
        data = {
            "document_number": "INV-003",
            "total_amount": 9999.0,  # Wrong total
            "line_items": [
                {"description": "Item A", "qty": 2, "unit_price": 500.0, "total": 1000.0}
            ],
            "subtotal": 1000.0,
            "vat_amount": 150.0,
        }
        findings = self.validator.validate("invoice", data)
        total_check = next((f for f in findings if f["check"] == "total_amount_correct"), None)
        self.assertIsNotNone(total_check)
        self.assertEqual(total_check["status"], "fail")

    def test_line_item_qty_price_mismatch_fails(self):
        data = {
            "document_number": "INV-004",
            "total_amount": 1150.0,
            "line_items": [
                # qty=2, price=500 should be 1000, but stated as 800
                {"description": "Item B", "qty": 2, "unit_price": 500.0, "total": 800.0}
            ],
            "subtotal": 800.0,
            "vat_amount": 120.0,
        }
        findings = self.validator.validate("invoice", data)
        arith_check = next((f for f in findings if f["check"] == "line_item_arithmetic"), None)
        self.assertIsNotNone(arith_check)
        self.assertEqual(arith_check["status"], "fail")

    def test_no_line_items_warns(self):
        data = {
            "document_number": "INV-005",
            "total_amount": 1150.0,
            "subtotal": 1000.0,
            "vat_amount": 150.0,
            "line_items": [],
        }
        findings = self.validator.validate("invoice", data)
        warn = next((f for f in findings if f["check"] == "line_items_present"), None)
        self.assertIsNotNone(warn)
        self.assertEqual(warn["status"], "warning")

    # ─── VAT Return ──────────────────────────────────────────

    def test_vat_return_arithmetic_pass(self):
        data = {
            "vat_number": "300012345600003",  # 15 digits
            "net_vat_payable": 7500.0,
            "output_vat": 15000.0,
            "input_vat": 7500.0,
        }
        findings = self.validator.validate("vat_return", data)
        check = next((f for f in findings if f["check"] == "net_vat_arithmetic"), None)
        self.assertIsNotNone(check)
        self.assertEqual(check["status"], "pass")

    def test_vat_return_arithmetic_fail(self):
        data = {
            "vat_number": "300012345600003",
            "net_vat_payable": 99999.0,  # Wrong
            "output_vat": 15000.0,
            "input_vat": 7500.0,
        }
        findings = self.validator.validate("vat_return", data)
        check = next((f for f in findings if f["check"] == "net_vat_arithmetic"), None)
        self.assertIsNotNone(check)
        self.assertEqual(check["status"], "fail")

    def test_vat_number_format_15_digits_pass(self):
        data = {
            "vat_number": "300012345600003",
            "net_vat_payable": 7500.0,
        }
        findings = self.validator.validate("vat_return", data)
        check = next((f for f in findings if f["check"] == "vat_number_format"), None)
        self.assertIsNotNone(check)
        self.assertEqual(check["status"], "pass")

    def test_vat_number_wrong_length_warns(self):
        data = {
            "vat_number": "12345",  # Too short
            "net_vat_payable": 7500.0,
        }
        findings = self.validator.validate("vat_return", data)
        check = next((f for f in findings if f["check"] == "vat_number_format"), None)
        self.assertIsNotNone(check)
        self.assertEqual(check["status"], "warning")

    # ─── Fixed Asset ─────────────────────────────────────────

    def test_fixed_asset_nbv_correct(self):
        data = {
            "asset_name": "Machinery",
            "acquisition_cost": 100000.0,
            "accumulated_depreciation": 30000.0,
            "net_book_value": 70000.0,
        }
        findings = self.validator.validate("fixed_asset", data)
        check = next((f for f in findings if f["check"] == "net_book_value_arithmetic"), None)
        self.assertIsNotNone(check)
        self.assertEqual(check["status"], "pass")

    def test_fixed_asset_nbv_wrong_fails(self):
        data = {
            "asset_name": "Machinery",
            "acquisition_cost": 100000.0,
            "accumulated_depreciation": 30000.0,
            "net_book_value": 50000.0,  # Wrong — should be 70000
        }
        findings = self.validator.validate("fixed_asset", data)
        check = next((f for f in findings if f["check"] == "net_book_value_arithmetic"), None)
        self.assertIsNotNone(check)
        self.assertEqual(check["status"], "fail")

    def test_fixed_asset_accumulated_dep_exceeds_cost_warns(self):
        data = {
            "asset_name": "Old Equipment",
            "acquisition_cost": 10000.0,
            "accumulated_depreciation": 15000.0,  # Exceeds cost
            "net_book_value": -5000.0,
        }
        findings = self.validator.validate("fixed_asset", data)
        warn = next((f for f in findings if f["check"] == "accumulated_depreciation_reasonable"), None)
        self.assertIsNotNone(warn)
        self.assertEqual(warn["status"], "warning")

    # ─── Expense Report ──────────────────────────────────────

    def test_expense_total_correct(self):
        data = {
            "employee_or_department": "Sales Team",
            "total_expense": 1500.0,
            "line_items": [
                {"category": "Travel", "amount": 800.0},
                {"category": "Meals", "amount": 700.0},
            ],
        }
        findings = self.validator.validate("expense_report", data)
        check = next((f for f in findings if f["check"] == "expense_total_matches_line_items"), None)
        self.assertIsNotNone(check)
        self.assertEqual(check["status"], "pass")

    def test_expense_negative_items_warn(self):
        data = {
            "employee_or_department": "Finance",
            "total_expense": 500.0,
            "line_items": [
                {"category": "Travel", "amount": 800.0},
                {"category": "Adjustment", "amount": -300.0},
            ],
        }
        findings = self.validator.validate("expense_report", data)
        warn = next((f for f in findings if f["check"] == "no_negative_expenses"), None)
        self.assertIsNotNone(warn)
        self.assertEqual(warn["status"], "warning")

    # ─── Date Validation ─────────────────────────────────────

    def test_issue_date_before_due_date_passes(self):
        data = {
            "document_number": "INV-100",
            "total_amount": 1000.0,
            "issue_date": "2024-01-01",
            "due_date": "2024-01-30",
        }
        findings = self.validator.validate("invoice", data)
        date_check = next((f for f in findings if "date_order" in f["check"]), None)
        self.assertIsNotNone(date_check)
        self.assertEqual(date_check["status"], "pass")

    def test_issue_date_after_due_date_fails(self):
        data = {
            "document_number": "INV-101",
            "total_amount": 1000.0,
            "issue_date": "2024-02-28",
            "due_date": "2024-01-01",  # Before issue date
        }
        findings = self.validator.validate("invoice", data)
        date_check = next((f for f in findings if "date_order" in f["check"]), None)
        self.assertIsNotNone(date_check)
        self.assertEqual(date_check["status"], "fail")

    # ─── Unknown doc type ────────────────────────────────────

    def test_unknown_doc_type_runs_only_base_checks(self):
        data = {"some_field": "value"}
        findings = self.validator.validate("other", data)
        self.assertIsInstance(findings, list)

    def test_returns_list_always(self):
        findings = self.validator.validate("invoice", {})
        self.assertIsInstance(findings, list)
