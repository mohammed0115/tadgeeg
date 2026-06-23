"""TADGEEG-FIN-AUDIT-1A — Trial Balance import staging tests.

Covers: model creation linked to the canonical AuditEngagement, CSV/XLSX
parsing, Arabic/English header aliases, balance detection, invalid-row capture,
import summary totals, period validation, unsupported-format rejection,
organization↔engagement consistency, and the safety invariant that NOTHING is
written to the ledger.
"""
from __future__ import annotations

import datetime
import io
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from apps.audit.models import AuditEngagement, TrialBalanceImport, TrialBalanceRow
from apps.audit.services import trial_balance_import as tb
from apps.authentication.models import Organization, User


def _org(name="Acme", **kw):
    return Organization.objects.create(name=name, country=Organization.Country.SAUDI_ARABIA, **kw)


def _user(org, email="a@e.com"):
    return User.objects.create_user(
        email=email, password="StrongPass123!", full_name="Tester",
        role=User.Role.ADMIN, organization=org,
    )


def _engagement(org, code="AUD-2026-001"):
    return AuditEngagement.objects.create(
        organization=org, engagement_code=code, title="FY2025 Audit",
        period_start=datetime.date(2025, 1, 1), period_end=datetime.date(2025, 12, 31),
    )


def _import(engagement, *, fmt="csv", **kw):
    return TrialBalanceImport.objects.create(
        engagement=engagement, organization=engagement.organization,
        source_format=fmt, **kw,
    )


CSV_BALANCED = (
    "Account Code,Account Name,Debit,Credit\n"
    "1000,Cash,1500.00,0\n"
    "2000,Payables,0,500.00\n"
    "3000,Equity,0,1000.00\n"
)

CSV_UNBALANCED = (
    "Account Code,Account Name,Debit,Credit\n"
    "1000,Cash,1500.00,0\n"
    "2000,Payables,0,300.00\n"
)

CSV_ARABIC = (
    "كود الحساب,اسم الحساب,مدين,دائن\n"
    "1000,النقدية,1500.00,0\n"
    "2000,الدائنون,0,1500.00\n"
)

CSV_INVALID_ROWS = (
    "Account Code,Account Name,Debit,Credit\n"
    ",Missing Code,100,0\n"             # missing account_code
    "2000,Bad Amount,abc,0\n"           # non-numeric debit
    "3000,Good,0,100\n"
)


class TrialBalanceModelTests(TestCase):
    def test_create_import_linked_to_engagement(self):
        eng = _engagement(_org())
        imp = _import(eng, fiscal_year=2025, currency="SAR")
        self.assertEqual(imp.engagement_id, eng.id)
        self.assertEqual(imp.organization_id, eng.organization_id)
        self.assertEqual(imp.status, TrialBalanceImport.Status.UPLOADED)

    def test_create_row(self):
        eng = _engagement(_org())
        imp = _import(eng)
        row = TrialBalanceRow.objects.create(
            import_batch=imp, engagement=eng, organization=eng.organization,
            row_number=1, account_code="1000", account_name="Cash",
            closing_debit=Decimal("100"),
        )
        self.assertEqual(row.import_batch_id, imp.id)
        self.assertEqual(imp.rows.count(), 1)

    def test_clean_rejects_cross_tenant(self):
        org_a, org_b = _org("A"), _org("B")
        eng_a = _engagement(org_a)
        imp = TrialBalanceImport(engagement=eng_a, organization=org_b,
                                 source_format="csv")
        with self.assertRaises(ValidationError):
            imp.clean()


class TrialBalanceParseTests(TestCase):
    def setUp(self):
        self.org = _org()
        self.eng = _engagement(self.org)

    def _run_csv(self, text, **import_kw):
        imp = _import(self.eng, **import_kw)
        return tb.parse_and_validate(imp, io.BytesIO(text.encode("utf-8")))

    def test_csv_balanced(self):
        imp = self._run_csv(CSV_BALANCED)
        self.assertEqual(imp.row_count, 3)
        self.assertEqual(imp.valid_row_count, 3)
        self.assertEqual(imp.invalid_row_count, 0)
        self.assertEqual(imp.total_debit, Decimal("1500.0000"))
        self.assertEqual(imp.total_credit, Decimal("1500.0000"))
        self.assertTrue(imp.is_balanced)
        self.assertEqual(imp.status, TrialBalanceImport.Status.VALIDATED)
        self.assertIsNotNone(imp.validated_at)
        self.assertEqual(imp.rows.count(), 3)

    def test_csv_unbalanced(self):
        imp = self._run_csv(CSV_UNBALANCED)
        self.assertFalse(imp.is_balanced)
        self.assertEqual(imp.difference, Decimal("1200.0000"))
        # Unbalanced but all rows individually valid → still flagged for review.
        self.assertEqual(imp.invalid_row_count, 0)

    def test_arabic_headers(self):
        imp = self._run_csv(CSV_ARABIC)
        self.assertIn("account_code", imp.column_mapping)
        self.assertIn("debit", imp.column_mapping)
        self.assertEqual(imp.valid_row_count, 2)
        self.assertTrue(imp.is_balanced)
        first = imp.rows.order_by("row_number").first()
        self.assertEqual(first.account_code, "1000")
        self.assertEqual(first.account_name, "النقدية")

    def test_invalid_rows_captured(self):
        imp = self._run_csv(CSV_INVALID_ROWS)
        self.assertEqual(imp.row_count, 3)
        self.assertEqual(imp.invalid_row_count, 2)
        self.assertEqual(imp.valid_row_count, 1)
        self.assertEqual(imp.status, TrialBalanceImport.Status.VALIDATION_FAILED)
        bad = imp.rows.filter(is_valid=False)
        self.assertEqual(bad.count(), 2)
        self.assertTrue(any("missing account_code" in r.validation_errors for r in bad))

    def test_summary_totals_stored(self):
        imp = self._run_csv(CSV_BALANCED)
        s = imp.validation_summary
        self.assertEqual(Decimal(s["total_debit"]), Decimal("1500"))
        self.assertEqual(Decimal(s["total_credit"]), Decimal("1500"))
        self.assertTrue(s["is_balanced"])
        self.assertIn("account_code", s["columns_detected"])

    def test_closing_debit_credit_aliases(self):
        text = ("Account Code,Account Name,الرصيد المدين,الرصيد الدائن\n"
                "1000,Cash,2000,0\n1100,Bank,0,2000\n")
        imp = self._run_csv(text)
        self.assertIn("closing_debit", imp.column_mapping)
        self.assertTrue(imp.is_balanced)

    def test_signed_balance_column(self):
        text = "Account Code,Account Name,Balance\n1000,Cash,500\n2000,Loan,-500\n"
        imp = self._run_csv(text)
        self.assertTrue(imp.is_balanced)
        self.assertEqual(imp.total_debit, Decimal("500.0000"))
        self.assertEqual(imp.total_credit, Decimal("500.0000"))

    def test_blank_rows_skipped(self):
        text = CSV_BALANCED + ",,,\n,,,\n"
        imp = self._run_csv(text)
        self.assertEqual(imp.row_count, 3)

    def test_period_validation(self):
        imp = _import(self.eng,
                      period_start=datetime.date(2025, 12, 31),
                      period_end=datetime.date(2025, 1, 1))
        result = tb.parse_and_validate(imp, io.BytesIO(CSV_BALANCED.encode("utf-8")))
        self.assertIn("period_start is after period_end", result.errors)
        self.assertEqual(result.status, TrialBalanceImport.Status.VALIDATION_FAILED)

    def test_unsupported_format_rejected(self):
        imp = _import(self.eng, fmt="pdf")
        with self.assertRaises(tb.TrialBalanceImportError):
            tb.parse_and_validate(imp, io.BytesIO(b"whatever"))
        imp.refresh_from_db()
        self.assertEqual(imp.status, TrialBalanceImport.Status.VALIDATION_FAILED)

    def test_xlsx_parsing(self):
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.append(["Account Code", "Account Name", "Debit", "Credit"])
        ws.append(["1000", "Cash", 1500, 0])
        ws.append(["2000", "Equity", 0, 1500])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        imp = _import(self.eng, fmt="xlsx")
        result = tb.parse_and_validate(imp, buf)
        self.assertEqual(result.valid_row_count, 2)
        self.assertTrue(result.is_balanced)

    def test_file_sha256_captured(self):
        imp = self._run_csv(CSV_BALANCED)
        self.assertEqual(len(imp.file_sha256), 64)


class TrialBalanceTenantSafetyTests(TestCase):
    def test_cross_tenant_import_denied_by_service(self):
        org_a, org_b = _org("A"), _org("B")
        eng_a = _engagement(org_a)
        # Force a mismatched org on the import row, then run the service.
        imp = TrialBalanceImport.objects.create(
            engagement=eng_a, organization=org_b, source_format="csv",
        )
        with self.assertRaises(ValidationError):
            tb.parse_and_validate(imp, io.BytesIO(CSV_BALANCED.encode("utf-8")))

    def test_rows_inherit_engagement_org(self):
        org = _org()
        eng = _engagement(org)
        imp = _import(eng)
        tb.parse_and_validate(imp, io.BytesIO(CSV_BALANCED.encode("utf-8")))
        for row in imp.rows.all():
            self.assertEqual(row.organization_id, org.id)
            self.assertEqual(row.engagement_id, eng.id)


class TrialBalanceLedgerIsolationTests(TestCase):
    def test_no_writes_to_ledger(self):
        from apps.ledger.models import JournalEntry, JournalLine
        je_before, jl_before = JournalEntry.objects.count(), JournalLine.objects.count()
        org = _org()
        eng = _engagement(org)
        imp = _import(eng)
        tb.parse_and_validate(imp, io.BytesIO(CSV_BALANCED.encode("utf-8")))
        # Staging rows created, ledger untouched.
        self.assertEqual(imp.rows.count(), 3)
        self.assertEqual(JournalEntry.objects.count(), je_before)
        self.assertEqual(JournalLine.objects.count(), jl_before)


class TrialBalanceUploadedFileTests(TestCase):
    def test_parses_from_attached_file(self):
        org = _org()
        eng = _engagement(org)
        upload = SimpleUploadedFile("tb.csv", CSV_BALANCED.encode("utf-8"),
                                    content_type="text/csv")
        imp = TrialBalanceImport.objects.create(
            engagement=eng, organization=org, source_format="csv",
            uploaded_file=upload, original_filename="tb.csv",
        )
        result = tb.parse_and_validate(imp)  # reads from imp.uploaded_file
        self.assertEqual(result.valid_row_count, 3)
        self.assertTrue(result.is_balanced)
