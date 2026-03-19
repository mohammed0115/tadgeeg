"""Tests for auditing service classes."""

from django.test import TestCase

from apps.auditing.services.file_router import FileRouterService
from apps.auditing.services.normalization_service import TextNormalizationService
from apps.auditing.services.document_detection_service import DocumentDetectionService
from apps.auditing.services.validation_service import ValidationService


class FileRouterServiceTests(TestCase):
    """Test FileRouterService.route() for all supported extensions."""

    def setUp(self):
        self.router = FileRouterService()

    def test_pdf_extension(self):
        self.assertEqual(self.router.route("invoice.pdf"), "pdf")

    def test_pdf_uppercase(self):
        self.assertEqual(self.router.route("DOCUMENT.PDF"), "pdf")

    def test_jpg_extension(self):
        self.assertEqual(self.router.route("photo.jpg"), "image")

    def test_jpeg_extension(self):
        self.assertEqual(self.router.route("scan.jpeg"), "image")

    def test_png_extension(self):
        self.assertEqual(self.router.route("receipt.png"), "image")

    def test_tiff_extension(self):
        self.assertEqual(self.router.route("document.tiff"), "image")

    def test_tif_extension(self):
        self.assertEqual(self.router.route("document.tif"), "image")

    def test_xlsx_extension(self):
        self.assertEqual(self.router.route("payroll.xlsx"), "excel")

    def test_xls_extension(self):
        self.assertEqual(self.router.route("report.xls"), "excel")

    def test_csv_extension(self):
        self.assertEqual(self.router.route("transactions.csv"), "csv")

    def test_json_extension(self):
        self.assertEqual(self.router.route("data.json"), "json")

    def test_jsonl_extension(self):
        self.assertEqual(self.router.route("records.jsonl"), "json")

    def test_zip_extension(self):
        self.assertEqual(self.router.route("archive.zip"), "zip")

    def test_unknown_extension(self):
        self.assertEqual(self.router.route("file.docx"), "unknown")

    def test_empty_filename(self):
        self.assertEqual(self.router.route(""), "unknown")

    def test_filename_with_path(self):
        self.assertEqual(self.router.route("/uploads/2024/bank_statement.pdf"), "pdf")

    def test_filename_with_dots_in_name(self):
        self.assertEqual(self.router.route("report.v2.2024.xlsx"), "excel")


class TextNormalizationServiceTests(TestCase):
    """Test TextNormalizationService."""

    def setUp(self):
        self.normalizer = TextNormalizationService()

    # ─── Arabic numeral conversion ───────────────────────────

    def test_arabic_numerals_converted(self):
        result = self.normalizer.normalize("المبلغ: ١٢٣٤٥")
        self.assertIn("12345", result)
        self.assertNotIn("١٢٣٤٥", result)

    def test_all_arabic_digits(self):
        result = self.normalizer._normalize_arabic_numerals("٠١٢٣٤٥٦٧٨٩")
        self.assertEqual(result, "0123456789")

    def test_mixed_arabic_western_numerals(self):
        result = self.normalizer.normalize("Invoice: ١٢٣ - Total: 456")
        self.assertIn("123", result)
        self.assertIn("456", result)

    def test_no_arabic_numerals_unchanged(self):
        text = "Total amount: 1234.56 SAR"
        result = self.normalizer.normalize(text)
        self.assertIn("1234.56", result)

    # ─── Whitespace normalization ────────────────────────────

    def test_collapses_multiple_spaces(self):
        result = self.normalizer.normalize("hello    world")
        self.assertNotIn("    ", result)
        self.assertIn("hello world", result)

    def test_collapses_excessive_newlines(self):
        result = self.normalizer.normalize("line1\n\n\n\n\nline2")
        self.assertNotIn("\n\n\n", result)

    def test_empty_string_returns_empty(self):
        result = self.normalizer.normalize("")
        self.assertEqual(result, "")

    def test_none_like_empty(self):
        # Should not raise
        result = self.normalizer.normalize("")
        self.assertIsInstance(result, str)

    # ─── Language detection ──────────────────────────────────

    def test_detect_arabic(self):
        text = "هذه فاتورة ضريبية صادرة من شركة تقنية المملكة العربية السعودية"
        lang = self.normalizer.detect_language(text)
        self.assertEqual(lang, "ar")

    def test_detect_english(self):
        text = "This is a tax invoice issued by the company for services rendered."
        lang = self.normalizer.detect_language(text)
        self.assertEqual(lang, "en")

    def test_detect_mixed(self):
        text = "Invoice رقم الفاتورة 12345 Total المجموع 500 SAR"
        lang = self.normalizer.detect_language(text)
        self.assertIn(lang, ("ar", "ar-en"))

    def test_detect_unknown_for_numbers_only(self):
        text = "1234 5678 9012 3456"
        lang = self.normalizer.detect_language(text)
        self.assertIn(lang, ("unknown", "en"))

    def test_detect_empty_returns_unknown(self):
        lang = self.normalizer.detect_language("")
        self.assertEqual(lang, "unknown")


class DocumentDetectionServiceTests(TestCase):
    """Test DocumentDetectionService.detect() keyword matching."""

    def setUp(self):
        self.detector = DocumentDetectionService()

    def test_detects_bank_statement(self):
        text = "Bank Statement\nOpening Balance: 10,000\nClosing Balance: 15,500\nDebit\nCredit"
        doc_type, confidence = self.detector.detect(text)
        self.assertEqual(doc_type, "bank_statement")
        self.assertGreater(confidence, 0.3)

    def test_detects_payroll(self):
        text = "Payroll Report\nEmployee Name\nBasic Salary\nNet Salary\nDeductions\nAllowance"
        doc_type, confidence = self.detector.detect(text)
        self.assertEqual(doc_type, "payroll")
        self.assertGreater(confidence, 0.3)

    def test_detects_purchase_order(self):
        text = "Purchase Order\nPO Number: PO-2024-001\nVendor Name: ABC Company"
        doc_type, confidence = self.detector.detect(text)
        self.assertEqual(doc_type, "purchase_order")

    def test_detects_vat_return(self):
        text = "VAT Return Filing\nZATCA\nOutput Tax\nInput Tax\nNet VAT Payable"
        doc_type, confidence = self.detector.detect(text)
        self.assertEqual(doc_type, "vat_return")

    def test_detects_expense_report(self):
        text = "Expense Report\nEmployee: John Doe\nReimbursement\nTravel Expense"
        doc_type, confidence = self.detector.detect(text)
        self.assertEqual(doc_type, "expense_report")

    def test_detects_invoice(self):
        text = "Tax Invoice\nInvoice Number: INV-001\nTotal Amount: 1,150 SAR"
        doc_type, confidence = self.detector.detect(text)
        self.assertEqual(doc_type, "invoice")

    def test_arabic_bank_statement(self):
        text = "كشف حساب بنكي\nالرصيد الافتتاحي: ٥٠٠٠\nالرصيد الختامي: ٧٠٠٠\nمدين\nدائن"
        doc_type, confidence = self.detector.detect(text)
        self.assertEqual(doc_type, "bank_statement")

    def test_arabic_payroll(self):
        text = "مسير الرواتب\nاسم الموظف\nالراتب الأساسي\nصافي الراتب\nالخصومات"
        doc_type, confidence = self.detector.detect(text)
        self.assertEqual(doc_type, "payroll")

    def test_hint_boosts_confidence(self):
        text = "Bank Statement Opening Balance Closing Balance"
        _, conf_no_hint = self.detector.detect(text, hint="auto")
        _, conf_with_hint = self.detector.detect(text, hint="bank_statement")
        self.assertGreaterEqual(conf_with_hint, conf_no_hint)

    def test_empty_text_returns_other(self):
        doc_type, confidence = self.detector.detect("")
        self.assertEqual(doc_type, "other")

    def test_empty_text_with_hint(self):
        doc_type, confidence = self.detector.detect("", hint="invoice")
        self.assertEqual(doc_type, "invoice")
        self.assertGreater(confidence, 0.0)

    def test_returns_tuple(self):
        result = self.detector.detect("some text")
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)


class ValidationServiceBankStatementTests(TestCase):
    """Tests for ValidationService bank statement validation."""

    def setUp(self):
        self.validator = ValidationService()

    def test_correct_balance_passes(self):
        data = {
            "account_number": "SA12345678901234567890",
            "opening_balance": 10000.0,
            "closing_balance": 13000.0,
            "total_credits": 5000.0,
            "total_debits": 2000.0,
        }
        findings = self.validator.validate("bank_statement", data)
        balance_check = next((f for f in findings if f["check"] == "balance_arithmetic"), None)
        self.assertIsNotNone(balance_check)
        self.assertEqual(balance_check["status"], "pass")

    def test_wrong_closing_balance_fails(self):
        data = {
            "account_number": "SA12345678901234567890",
            "opening_balance": 10000.0,
            "closing_balance": 99999.0,  # Wrong
            "total_credits": 5000.0,
            "total_debits": 2000.0,
        }
        findings = self.validator.validate("bank_statement", data)
        balance_check = next((f for f in findings if f["check"] == "balance_arithmetic"), None)
        self.assertIsNotNone(balance_check)
        self.assertEqual(balance_check["status"], "fail")

    def test_missing_opening_balance_not_applicable(self):
        data = {
            "account_number": "SA12345678901234567890",
            "closing_balance": 5000.0,
        }
        findings = self.validator.validate("bank_statement", data)
        balance_check = next((f for f in findings if f["check"] == "balance_arithmetic"), None)
        self.assertIsNotNone(balance_check)
        self.assertEqual(balance_check["status"], "not_applicable")

    def test_required_fields_missing_returns_fail(self):
        data = {"account_number": "SA123"}
        findings = self.validator.validate("bank_statement", data)
        field_failures = [f for f in findings if "required_field" in f["check"] and f["status"] == "fail"]
        self.assertGreater(len(field_failures), 0)

    def test_empty_data_returns_data_available_fail(self):
        findings = self.validator.validate("bank_statement", {})
        self.assertTrue(any(f["check"] == "data_available" for f in findings))


class ValidationServicePayrollTests(TestCase):
    """Tests for ValidationService payroll validation."""

    def setUp(self):
        self.validator = ValidationService()

    def test_correct_payroll_passes(self):
        data = {
            "company_name": "ABC Corp",
            "total_gross_salary": 50000.0,
            "total_deductions": 5000.0,
            "total_net_salary": 45000.0,
            "employee_count": 2,
            "employees": [
                {
                    "id": "E001", "name": "Ali",
                    "basic_salary": 20000.0, "allowances": 5000.0,
                    "deductions": 2000.0, "net_salary": 23000.0,
                },
                {
                    "id": "E002", "name": "Sara",
                    "basic_salary": 15000.0, "allowances": 10000.0,
                    "deductions": 3000.0, "net_salary": 22000.0,
                },
            ],
        }
        findings = self.validator.validate("payroll", data)
        net_check = next((f for f in findings if f["check"] == "gross_minus_deductions_equals_net"), None)
        self.assertIsNotNone(net_check)
        self.assertEqual(net_check["status"], "pass")

    def test_payroll_count_mismatch_fails(self):
        data = {
            "company_name": "ABC Corp",
            "total_net_salary": 45000.0,
            "employee_count": 5,  # Wrong count
            "employees": [
                {"id": "E001", "name": "Ali", "basic_salary": 20000.0,
                 "allowances": 5000.0, "deductions": 2000.0, "net_salary": 23000.0},
                {"id": "E002", "name": "Sara", "basic_salary": 15000.0,
                 "allowances": 10000.0, "deductions": 3000.0, "net_salary": 22000.0},
            ],
        }
        findings = self.validator.validate("payroll", data)
        count_check = next((f for f in findings if f["check"] == "employee_count_match"), None)
        self.assertIsNotNone(count_check)
        self.assertEqual(count_check["status"], "fail")

    def test_wrong_net_salary_total_fails(self):
        """When employees are provided but gross-net arithmetic is wrong, it fails."""
        data = {
            "company_name": "ABC Corp",
            "total_gross_salary": 50000.0,
            "total_deductions": 5000.0,
            "total_net_salary": 99999.0,  # Wrong — should be 45000
            "employee_count": 1,
            "employees": [
                {
                    "id": "E001", "name": "Ali",
                    "basic_salary": 40000.0, "allowances": 10000.0,
                    "deductions": 5000.0, "net_salary": 45000.0,
                }
            ],
        }
        findings = self.validator.validate("payroll", data)
        total_check = next(
            (f for f in findings if f["check"] == "total_net_salary_match"), None
        )
        self.assertIsNotNone(total_check)
        self.assertEqual(total_check["status"], "fail")

    def test_no_employees_returns_warning(self):
        data = {
            "company_name": "ABC Corp",
            "total_net_salary": 45000.0,
            "employees": [],
        }
        findings = self.validator.validate("payroll", data)
        warning = next((f for f in findings if f["check"] == "employee_list_present"), None)
        self.assertIsNotNone(warning)
        self.assertEqual(warning["status"], "warning")
