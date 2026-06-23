"""TADGEEG-FIN-AUDIT-1B — Trial Balance upload/API + Account Mapping tests.

Covers org-scoped upload/list/detail, cross-tenant denial, that the upload
calls parse_and_validate, AccountMapping creation/uniqueness, deterministic
AR/EN category suggestions, manual-mapping preservation, and that nothing is
written to the ledger.
"""
from __future__ import annotations

import datetime
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from apps.audit.models import (
    AccountMapping,
    AuditEngagement,
    TrialBalanceImport,
)
from apps.audit.services import account_mapping as mapping_service
from apps.audit.services import trial_balance_import as tb_service
from apps.authentication.models import Organization, User

_LIST = "/api/v1/audit/trial-balance/imports/"
_MAP_LIST = "/api/v1/audit/trial-balance/account-mappings/"
_MAP_GEN = "/api/v1/audit/trial-balance/account-mappings/generate/"


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


CSV_BALANCED = (
    "Account Code,Account Name,Debit,Credit\n"
    "1000,Cash at Bank,1500.00,0\n"
    "2000,Trade Payables,0,500.00\n"
    "3000,Share Capital,0,1000.00\n"
)


def _csv_upload(name="tb.csv", body=CSV_BALANCED):
    return SimpleUploadedFile(name, body.encode("utf-8"), content_type="text/csv")


# ── API: upload / list / detail (org-scoped) ──────────────────────────────────
class TrialBalanceUploadApiTests(TestCase):
    def setUp(self):
        self.org = _org("OrgA")
        self.user = _user(self.org, "a@e.com")
        self.eng = _engagement(self.org)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_upload_to_own_engagement_succeeds(self):
        resp = self.client.post(_LIST, {
            "engagement": str(self.eng.id),
            "uploaded_file": _csv_upload(),
        }, format="multipart")
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertEqual(body["status"], TrialBalanceImport.Status.VALIDATED)
        self.assertEqual(body["valid_row_count"], 3)
        self.assertTrue(body["is_balanced"])
        # parse_and_validate ran → staging rows exist.
        imp = TrialBalanceImport.objects.get(id=body["id"])
        self.assertEqual(imp.rows.count(), 3)

    def test_upload_to_other_org_engagement_denied(self):
        other_eng = _engagement(_org("OrgB"), code="OTHER-1")
        resp = self.client.post(_LIST, {
            "engagement": str(other_eng.id),
            "uploaded_file": _csv_upload(),
        }, format="multipart")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(TrialBalanceImport.objects.filter(engagement=other_eng).count(), 0)

    def test_upload_unsupported_extension_rejected(self):
        resp = self.client.post(_LIST, {
            "engagement": str(self.eng.id),
            "uploaded_file": SimpleUploadedFile("tb.pdf", b"x", content_type="application/pdf"),
        }, format="multipart")
        self.assertEqual(resp.status_code, 400)

    def test_list_is_org_scoped(self):
        # One import in our org, one in another org.
        self.client.post(_LIST, {"engagement": str(self.eng.id),
                                  "uploaded_file": _csv_upload()}, format="multipart")
        other_eng = _engagement(_org("OrgB"), code="OTHER-2")
        TrialBalanceImport.objects.create(engagement=other_eng,
                                          organization=other_eng.organization,
                                          source_format="csv")
        resp = self.client.get(_LIST)
        self.assertEqual(resp.status_code, 200)
        ids = {row["id"] for row in resp.json()}
        self.assertEqual(len(ids), 1)  # only our org's import

    def test_detail_shows_summary(self):
        up = self.client.post(_LIST, {"engagement": str(self.eng.id),
                                       "uploaded_file": _csv_upload()}, format="multipart").json()
        resp = self.client.get(f"{_LIST}{up['id']}/")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        for key in ("status", "row_count", "valid_row_count", "invalid_row_count",
                    "total_debit", "total_credit", "difference", "is_balanced",
                    "validation_summary", "errors", "warnings", "invalid_rows_sample"):
            self.assertIn(key, body)

    def test_detail_other_org_not_found(self):
        other_eng = _engagement(_org("OrgB"), code="OTHER-3")
        imp = TrialBalanceImport.objects.create(engagement=other_eng,
                                                organization=other_eng.organization,
                                                source_format="csv")
        resp = self.client.get(f"{_LIST}{imp.id}/")
        self.assertEqual(resp.status_code, 404)


# ── Account mapping model ─────────────────────────────────────────────────────
class AccountMappingModelTests(TestCase):
    def test_create_linked_to_engagement(self):
        org = _org()
        eng = _engagement(org)
        m = AccountMapping.objects.create(
            engagement=eng, organization=org, account_code="1000",
            account_name="Cash", mapped_category=AccountMapping.Category.CASH_AND_BANK,
        )
        self.assertEqual(m.engagement_id, eng.id)
        self.assertEqual(eng.account_mappings.count(), 1)

    def test_unique_per_engagement_account_code(self):
        org = _org()
        eng = _engagement(org)
        AccountMapping.objects.create(engagement=eng, organization=org, account_code="1000")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AccountMapping.objects.create(engagement=eng, organization=org, account_code="1000")


# ── Deterministic category suggestions ────────────────────────────────────────
class SuggestCategoryTests(TestCase):
    def test_english_keywords(self):
        cat, conf = mapping_service.suggest_category("Cash at Bank", "1000")
        self.assertEqual(cat, AccountMapping.Category.CASH_AND_BANK)
        self.assertGreater(conf, Decimal("0"))
        self.assertEqual(mapping_service.suggest_category("Trade Receivables")[0],
                         AccountMapping.Category.ACCOUNTS_RECEIVABLE)
        self.assertEqual(mapping_service.suggest_category("Sales Revenue")[0],
                         AccountMapping.Category.REVENUE)
        self.assertEqual(mapping_service.suggest_category("Staff Salaries")[0],
                         AccountMapping.Category.PAYROLL_EXPENSE)
        self.assertEqual(mapping_service.suggest_category("VAT Payable")[0],
                         AccountMapping.Category.VAT_TAX)

    def test_arabic_keywords(self):
        self.assertEqual(mapping_service.suggest_category("النقدية والبنك")[0],
                         AccountMapping.Category.CASH_AND_BANK)
        self.assertEqual(mapping_service.suggest_category("ذمم مدينة - عملاء")[0],
                         AccountMapping.Category.ACCOUNTS_RECEIVABLE)
        self.assertEqual(mapping_service.suggest_category("الموردين")[0],
                         AccountMapping.Category.ACCOUNTS_PAYABLE)
        self.assertEqual(mapping_service.suggest_category("ضريبة القيمة المضافة")[0],
                         AccountMapping.Category.VAT_TAX)
        self.assertEqual(mapping_service.suggest_category("إيرادات المبيعات")[0],
                         AccountMapping.Category.REVENUE)
        self.assertEqual(mapping_service.suggest_category("رواتب الموظفين")[0],
                         AccountMapping.Category.PAYROLL_EXPENSE)

    def test_unknown_fallback(self):
        cat, conf = mapping_service.suggest_category("Zzz Miscellaneous 9999", "9999")
        self.assertEqual(cat, AccountMapping.Category.UNKNOWN)
        self.assertEqual(conf, Decimal("0.000"))


# ── generate_mappings_from_import ─────────────────────────────────────────────
class GenerateMappingsTests(TestCase):
    def setUp(self):
        self.org = _org()
        self.eng = _engagement(self.org)
        self.imp = TrialBalanceImport.objects.create(
            engagement=self.eng, organization=self.org, source_format="csv")
        import io
        tb_service.parse_and_validate(self.imp, io.BytesIO(CSV_BALANCED.encode("utf-8")))

    def test_creates_mappings_for_each_account(self):
        summary = mapping_service.generate_mappings_from_import(self.imp)
        self.assertEqual(summary["created"], 3)
        self.assertEqual(AccountMapping.objects.filter(engagement=self.eng).count(), 3)
        cash = AccountMapping.objects.get(engagement=self.eng, account_code="1000")
        self.assertEqual(cash.mapped_category, AccountMapping.Category.CASH_AND_BANK)
        self.assertEqual(cash.mapping_source, AccountMapping.Source.RULE_BASED)

    def test_preserves_existing_manual_mapping(self):
        # Auditor manually classifies 1000 as OTHER_ASSETS before generation.
        AccountMapping.objects.create(
            engagement=self.eng, organization=self.org, account_code="1000",
            mapped_category=AccountMapping.Category.OTHER_ASSETS,
            mapping_source=AccountMapping.Source.MANUAL,
        )
        summary = mapping_service.generate_mappings_from_import(self.imp)
        self.assertEqual(summary["created"], 2)  # 1000 skipped
        preserved = AccountMapping.objects.get(engagement=self.eng, account_code="1000")
        self.assertEqual(preserved.mapped_category, AccountMapping.Category.OTHER_ASSETS)
        self.assertEqual(preserved.mapping_source, AccountMapping.Source.MANUAL)

    def test_generate_endpoint_org_scoped(self):
        # A user from another org cannot generate mappings for our import.
        other_user = _user(_org("OrgB"), "b@e.com")
        client = APIClient(); client.force_authenticate(other_user)
        resp = client.post(_MAP_GEN, {"import_id": str(self.imp.id)}, format="json")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(AccountMapping.objects.filter(engagement=self.eng).count(), 0)

    def test_generate_endpoint_own_org(self):
        user = _user(self.org, "owner@e.com")
        client = APIClient(); client.force_authenticate(user)
        resp = client.post(_MAP_GEN, {"import_id": str(self.imp.id)}, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json()["created"], 3)


# ── Ledger isolation ──────────────────────────────────────────────────────────
class LedgerIsolationTests(TestCase):
    def test_no_writes_to_ledger(self):
        from apps.ledger.models import Account, JournalEntry, JournalLine
        acc, je, jl = (Account.objects.count(), JournalEntry.objects.count(),
                       JournalLine.objects.count())
        org = _org()
        eng = _engagement(org)
        imp = TrialBalanceImport.objects.create(engagement=eng, organization=org,
                                                source_format="csv")
        import io
        tb_service.parse_and_validate(imp, io.BytesIO(CSV_BALANCED.encode("utf-8")))
        mapping_service.generate_mappings_from_import(imp)
        self.assertEqual(Account.objects.count(), acc)
        self.assertEqual(JournalEntry.objects.count(), je)
        self.assertEqual(JournalLine.objects.count(), jl)
