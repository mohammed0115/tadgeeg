"""TADGEEG-FIN-AUDIT-2A — General Ledger import staging tests.

Covers model creation linked to AuditEngagement, CSV/XLSX parsing, AR/EN header
aliases, balanced/unbalanced detection, signed-amount support, per-journal
balancing, invalid-row capture, summary totals, sha256, period validation,
format rejection, org consistency, related_trial_balance_import validation,
AccountMapping linking + unmapped count, TB-alignment warnings, org-scoped
upload/list/detail API, cross-org denial, and no writes to the ledger.
"""
from __future__ import annotations

import datetime
import io
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework.test import APIClient

from apps.audit.models import (
    AccountMapping,
    AuditEngagement,
    GeneralLedgerImport,
    GeneralLedgerRow,
    TrialBalanceImport,
)
from apps.audit.services import general_ledger_import as gl
from apps.audit.services import trial_balance_import as tb_service
from apps.authentication.models import Organization, User

_GL_LIST = "/api/v1/audit/general-ledger/imports/"


def _org(name="Acme"):
    return Organization.objects.create(name=name, country=Organization.Country.SAUDI_ARABIA)


def _user(org, email="a@e.com", role=None):
    return User.objects.create_user(
        email=email, password="StrongPass123!", full_name="Tester",
        role=role or User.Role.ADMIN, organization=org,
    )


def _engagement(org, code="AUD-2026-001"):
    return AuditEngagement.objects.create(
        organization=org, engagement_code=code, title="FY2025 Audit",
        period_start=datetime.date(2025, 1, 1), period_end=datetime.date(2025, 12, 31),
    )


def _gl_import(engagement, *, fmt="csv", tb=None, **kw):
    return GeneralLedgerImport.objects.create(
        engagement=engagement, organization=engagement.organization,
        related_trial_balance_import=tb, source_format=fmt, **kw,
    )


# Balanced GL: two journals, each balanced; totals 1500/1500.
CSV_GL_BALANCED = (
    "Journal Number,Date,Account Code,Account Name,Debit,Credit,Description\n"
    "JV-1,2025-03-01,1000,Cash,1000.00,0,Receipt\n"
    "JV-1,2025-03-01,4000,Sales,0,1000.00,Receipt\n"
    "JV-2,2025-03-02,5000,Rent,500.00,0,Rent\n"
    "JV-2,2025-03-02,1000,Cash,0,500.00,Rent\n"
)

CSV_GL_UNBALANCED = (
    "Journal Number,Date,Account Code,Account Name,Debit,Credit\n"
    "JV-1,2025-03-01,1000,Cash,1000.00,0\n"
    "JV-1,2025-03-01,4000,Sales,0,800.00\n"
)

CSV_GL_ARABIC = (
    "رقم القيد,التاريخ,رقم الحساب,اسم الحساب,مدين,دائن\n"
    "ق-1,2025-03-01,1000,النقدية,1000.00,0\n"
    "ق-1,2025-03-01,4000,المبيعات,0,1000.00\n"
)

CSV_GL_SIGNED = (
    "Account Code,Account Name,Amount,Date\n"
    "1000,Cash,1000.00,2025-03-01\n"
    "4000,Sales,-1000.00,2025-03-01\n"
)

CSV_GL_INVALID = (
    "Journal Number,Account Code,Debit,Credit\n"
    "JV-1,,100,0\n"            # missing account_code
    "JV-1,4000,abc,0\n"       # non-numeric debit
    "JV-2,5000,0,100\n"
)


class GLModelTests(TestCase):
    def test_create_import_linked_to_engagement(self):
        eng = _engagement(_org())
        imp = _gl_import(eng, fiscal_year=2025)
        self.assertEqual(imp.engagement_id, eng.id)
        self.assertEqual(imp.organization_id, eng.organization_id)
        self.assertEqual(imp.status, GeneralLedgerImport.Status.UPLOADED)

    def test_create_row(self):
        eng = _engagement(_org())
        imp = _gl_import(eng)
        row = GeneralLedgerRow.objects.create(
            import_batch=imp, engagement=eng, organization=eng.organization,
            row_number=1, account_code="1000", debit=Decimal("10"),
        )
        self.assertEqual(imp.rows.count(), 1)
        self.assertEqual(row.import_batch_id, imp.id)

    def test_clean_rejects_cross_tenant(self):
        eng = _engagement(_org("A"))
        imp = GeneralLedgerImport(engagement=eng, organization=_org("B"), source_format="csv")
        with self.assertRaises(ValidationError):
            imp.clean()

    def test_clean_rejects_foreign_tb_import(self):
        org = _org()
        eng = _engagement(org)
        other_eng = _engagement(org, code="AUD-2")
        foreign_tb = TrialBalanceImport.objects.create(
            engagement=other_eng, organization=org, source_format="csv")
        imp = GeneralLedgerImport(engagement=eng, organization=org,
                                  related_trial_balance_import=foreign_tb,
                                  source_format="csv")
        with self.assertRaises(ValidationError):
            imp.clean()

    def test_unique_row_number_per_import(self):
        eng = _engagement(_org())
        imp = _gl_import(eng)
        GeneralLedgerRow.objects.create(import_batch=imp, engagement=eng,
                                        organization=eng.organization, row_number=1)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                GeneralLedgerRow.objects.create(import_batch=imp, engagement=eng,
                                                organization=eng.organization, row_number=1)


class GLParseTests(TestCase):
    def setUp(self):
        self.org = _org()
        self.eng = _engagement(self.org)

    def _run(self, text, **kw):
        imp = _gl_import(self.eng, **kw)
        return gl.parse_and_validate(imp, io.BytesIO(text.encode("utf-8")))

    def test_balanced_gl_and_journal_grouping(self):
        imp = self._run(CSV_GL_BALANCED)
        self.assertEqual(imp.row_count, 4)
        self.assertEqual(imp.valid_row_count, 4)
        self.assertEqual(imp.total_debit, Decimal("1500.0000"))
        self.assertEqual(imp.total_credit, Decimal("1500.0000"))
        self.assertTrue(imp.is_balanced)
        self.assertEqual(imp.journal_count, 2)
        self.assertEqual(imp.balanced_journal_count, 2)
        self.assertEqual(imp.unbalanced_journal_count, 0)
        self.assertEqual(imp.status, GeneralLedgerImport.Status.VALIDATED)
        # Dates parsed.
        first = imp.rows.order_by("row_number").first()
        self.assertEqual(first.transaction_date, datetime.date(2025, 3, 1))

    def test_unbalanced_gl_and_journal(self):
        imp = self._run(CSV_GL_UNBALANCED)
        self.assertFalse(imp.is_balanced)
        self.assertEqual(imp.difference, Decimal("200.0000"))
        self.assertEqual(imp.unbalanced_journal_count, 1)
        self.assertTrue(any("unbalanced journal" in w for w in imp.warnings))

    def test_arabic_headers(self):
        imp = self._run(CSV_GL_ARABIC)
        self.assertIn("account_code", imp.column_mapping)
        self.assertIn("journal_number", imp.column_mapping)
        self.assertIn("debit", imp.column_mapping)
        self.assertTrue(imp.is_balanced)
        self.assertEqual(imp.journal_count, 1)

    def test_signed_amount_support(self):
        imp = self._run(CSV_GL_SIGNED)
        self.assertTrue(imp.is_balanced)
        self.assertEqual(imp.total_debit, Decimal("1000.0000"))
        self.assertEqual(imp.total_credit, Decimal("1000.0000"))

    def test_invalid_rows_captured(self):
        imp = self._run(CSV_GL_INVALID)
        self.assertEqual(imp.row_count, 3)
        self.assertEqual(imp.invalid_row_count, 2)
        self.assertEqual(imp.valid_row_count, 1)
        self.assertEqual(imp.status, GeneralLedgerImport.Status.VALIDATION_FAILED)
        bad = imp.rows.filter(is_valid=False)
        self.assertTrue(any("missing account_code" in r.validation_errors for r in bad))

    def test_summary_and_sha256(self):
        imp = self._run(CSV_GL_BALANCED)
        s = imp.validation_summary
        self.assertEqual(Decimal(s["total_debit"]), Decimal("1500"))
        self.assertEqual(s["journal_count"], 2)
        self.assertIn("unmapped_account_count", s)
        self.assertEqual(len(imp.file_sha256), 64)

    def test_period_validation(self):
        imp = _gl_import(self.eng, period_start=datetime.date(2025, 12, 31),
                         period_end=datetime.date(2025, 1, 1))
        result = gl.parse_and_validate(imp, io.BytesIO(CSV_GL_BALANCED.encode("utf-8")))
        self.assertIn("period_start is after period_end", result.errors)
        self.assertEqual(result.status, GeneralLedgerImport.Status.VALIDATION_FAILED)

    def test_unsupported_format_rejected(self):
        imp = _gl_import(self.eng, fmt="pdf")
        with self.assertRaises(gl.GeneralLedgerImportError):
            gl.parse_and_validate(imp, io.BytesIO(b"data"))
        imp.refresh_from_db()
        self.assertEqual(imp.status, GeneralLedgerImport.Status.VALIDATION_FAILED)

    def test_xlsx_parsing(self):
        from openpyxl import Workbook
        wb = Workbook(); ws = wb.active
        ws.append(["Journal Number", "Account Code", "Account Name", "Debit", "Credit"])
        ws.append(["JV-1", "1000", "Cash", 1000, 0])
        ws.append(["JV-1", "4000", "Sales", 0, 1000])
        buf = io.BytesIO(); wb.save(buf); buf.seek(0)
        imp = _gl_import(self.eng, fmt="xlsx")
        result = gl.parse_and_validate(imp, buf)
        self.assertEqual(result.valid_row_count, 2)
        self.assertTrue(result.is_balanced)

    def test_rows_inherit_engagement_org(self):
        imp = self._run(CSV_GL_BALANCED)
        for row in imp.rows.all():
            self.assertEqual(row.organization_id, self.org.id)
            self.assertEqual(row.engagement_id, self.eng.id)


class GLAccountMappingTests(TestCase):
    def setUp(self):
        self.org = _org()
        self.eng = _engagement(self.org)

    def test_links_existing_mapping_and_counts_unmapped(self):
        # Map only account 1000; 4000/5000 stay unmapped.
        AccountMapping.objects.create(
            engagement=self.eng, organization=self.org, account_code="1000",
            mapped_category=AccountMapping.Category.CASH_AND_BANK)
        imp = _gl_import(self.eng)
        gl.parse_and_validate(imp, io.BytesIO(CSV_GL_BALANCED.encode("utf-8")))
        linked = imp.rows.filter(account_code="1000", mapped_account__isnull=False)
        self.assertTrue(linked.exists())
        unlinked = imp.rows.filter(account_code="4000", mapped_account__isnull=True)
        self.assertTrue(unlinked.exists())
        # 4000 and 5000 unmapped → count 2.
        self.assertEqual(imp.validation_summary["unmapped_account_count"], 2)


class GLTrialBalanceAlignmentTests(TestCase):
    def setUp(self):
        self.org = _org()
        self.eng = _engagement(self.org)
        # TB has 1000, 4000, 9999 (9999 has no GL activity).
        self.tb = TrialBalanceImport.objects.create(
            engagement=self.eng, organization=self.org, source_format="csv")
        tb_csv = ("Account Code,Account Name,Debit,Credit\n"
                  "1000,Cash,1000,0\n4000,Sales,0,1000\n9999,Suspense,0,0\n")
        tb_service.parse_and_validate(self.tb, io.BytesIO(tb_csv.encode("utf-8")))

    def test_alignment_flags_missing_accounts(self):
        # GL references 5000 (not in TB); TB has 9999 (no GL activity).
        imp = _gl_import(self.eng, tb=self.tb)
        gl.parse_and_validate(imp, io.BytesIO(CSV_GL_BALANCED.encode("utf-8")))
        align = imp.validation_summary["trial_balance_alignment"]
        self.assertIn("5000", align["gl_accounts_missing_from_tb"])
        self.assertIn("9999", align["tb_accounts_without_gl_activity"])
        self.assertTrue(any("missing from the trial balance" in w for w in imp.warnings))
        # Alignment gaps are warnings, not hard failures.
        self.assertEqual(imp.status, GeneralLedgerImport.Status.VALIDATED)


class GLApiTests(TestCase):
    def setUp(self):
        self.org = _org("OrgA")
        self.user = _user(self.org, "a@e.com")
        self.eng = _engagement(self.org)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_upload_own_engagement_succeeds(self):
        resp = self.client.post(_GL_LIST, {
            "engagement": str(self.eng.id),
            "uploaded_file": SimpleUploadedFile("gl.csv", CSV_GL_BALANCED.encode("utf-8")),
        }, format="multipart")
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertEqual(body["status"], GeneralLedgerImport.Status.VALIDATED)
        self.assertEqual(body["journal_count"], 2)
        self.assertTrue(body["is_balanced"])

    def test_upload_other_org_denied(self):
        other_eng = _engagement(_org("OrgB"), code="OTHER-1")
        resp = self.client.post(_GL_LIST, {
            "engagement": str(other_eng.id),
            "uploaded_file": SimpleUploadedFile("gl.csv", CSV_GL_BALANCED.encode("utf-8")),
        }, format="multipart")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(GeneralLedgerImport.objects.filter(engagement=other_eng).count(), 0)

    def test_list_and_detail_org_scoped(self):
        up = self.client.post(_GL_LIST, {
            "engagement": str(self.eng.id),
            "uploaded_file": SimpleUploadedFile("gl.csv", CSV_GL_BALANCED.encode("utf-8")),
        }, format="multipart").json()
        # Another org's import is invisible.
        other_eng = _engagement(_org("OrgB"), code="OTHER-2")
        other = GeneralLedgerImport.objects.create(engagement=other_eng,
                                                   organization=other_eng.organization,
                                                   source_format="csv")
        lst = self.client.get(_GL_LIST)
        ids = {r["id"] for r in lst.json()}
        self.assertIn(up["id"], ids)
        self.assertNotIn(str(other.id), ids)
        # Cross-org detail 404.
        self.assertEqual(self.client.get(f"{_GL_LIST}{other.id}/").status_code, 404)
        # Own detail shows summary + sample.
        detail = self.client.get(f"{_GL_LIST}{up['id']}/").json()
        for k in ("journal_count", "unbalanced_journal_count", "validation_summary",
                  "invalid_rows_sample"):
            self.assertIn(k, detail)


class GLLedgerIsolationTests(TestCase):
    def test_no_writes_to_ledger(self):
        from apps.ledger.models import Account, JournalEntry, JournalLine
        acc, je, jl = (Account.objects.count(), JournalEntry.objects.count(),
                       JournalLine.objects.count())
        eng = _engagement(_org())
        imp = _gl_import(eng)
        gl.parse_and_validate(imp, io.BytesIO(CSV_GL_BALANCED.encode("utf-8")))
        self.assertEqual(imp.rows.count(), 4)
        self.assertEqual(Account.objects.count(), acc)
        self.assertEqual(JournalEntry.objects.count(), je)
        self.assertEqual(JournalLine.objects.count(), jl)
