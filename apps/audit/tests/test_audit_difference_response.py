"""TADGEEG-FIN-AUDIT-4B — Management response + proposed adjustment tests.

Covers response transitions/finality/note rules + trail, proposed-adjustment
validation (amount, accounts, disclosure_only), org scoping (service + API),
cross-org denial, and no ledger writes.
"""
from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.test import APIClient

from apps.audit.models import (
    AuditDifferenceItem,
    AuditDifferenceItemResponse,
    AuditDifferenceSummary,
    AuditEngagement,
    GeneralLedgerImport,
    GeneralLedgerRiskFinding,
    ProposedAuditAdjustment,
)
from apps.audit.services import audit_difference_response as resp
from apps.audit.services import audit_difference_summary as sad
from apps.audit.services import proposed_audit_adjustment as adj
from apps.authentication.models import Organization, User

_MR = AuditDifferenceItem.ManagementResponse
_AT = ProposedAuditAdjustment.Type
PROFILE = {"overall_materiality": 100000, "performance_materiality": 75000,
           "clearly_trivial": 5000, "currency": "SAR"}


def _org(name="Acme"):
    return Organization.objects.create(name=name, country=Organization.Country.SAUDI_ARABIA)


def _user(org, email="a@e.com"):
    return User.objects.create_user(email=email, password="StrongPass123!",
                                    full_name="T", role=User.Role.ADMIN, organization=org)


def _eng(org, code="AUD-1"):
    return AuditEngagement.objects.create(
        organization=org, engagement_code=code, title="FY25",
        period_start="2025-01-01", period_end="2025-12-31", materiality=PROFILE)


def _item(org, eng, amount=30000):
    """Create an accepted GL finding and build the SAD so an item exists."""
    imp = GeneralLedgerImport.objects.create(
        engagement=eng, organization=org, source_format="csv")
    GeneralLedgerRiskFinding.objects.create(
        engagement=eng, organization=org, general_ledger_import=imp,
        risk_code="GL-RISK-DESC", risk_title="t",
        risk_category=GeneralLedgerRiskFinding.Category.OTHER,
        severity=GeneralLedgerRiskFinding.Severity.MEDIUM, score=50,
        amount_impact=Decimal(str(amount)), account_code="6000",
        status=GeneralLedgerRiskFinding.Status.ACCEPTED)
    summary = sad.recalculate_for_engagement(eng)
    return summary.items.first()


class ResponseTransitionTests(TestCase):
    def setUp(self):
        self.org = _org(); self.user = _user(self.org); self.eng = _eng(self.org)
        self.item = _item(self.org, self.eng)

    def test_not_requested_to_pending(self):
        resp.record_response(self.item, actor=self.user, to_status=_MR.PENDING)
        self.item.refresh_from_db()
        self.assertEqual(self.item.management_response_status, _MR.PENDING)
        self.assertEqual(self.item.responses.count(), 1)

    def test_pending_to_agreed(self):
        self.item.management_response_status = _MR.PENDING
        self.item.save(update_fields=["management_response_status"])
        resp.record_response(self.item, actor=self.user, to_status=_MR.AGREED)
        self.item.refresh_from_db()
        self.assertEqual(self.item.management_response_status, _MR.AGREED)

    def test_pending_to_disagreed_requires_note(self):
        self.item.management_response_status = _MR.PENDING
        self.item.save(update_fields=["management_response_status"])
        with self.assertRaises(resp.ManagementResponseError):
            resp.record_response(self.item, actor=self.user, to_status=_MR.DISAGREED)
        resp.record_response(self.item, actor=self.user, to_status=_MR.DISAGREED,
                             response_note="Management disputes the entry")
        self.item.refresh_from_db()
        self.assertEqual(self.item.management_response_status, _MR.DISAGREED)

    def test_agreed_to_adjusted_requires_note(self):
        self.item.management_response_status = _MR.AGREED
        self.item.save(update_fields=["management_response_status"])
        with self.assertRaises(resp.ManagementResponseError):
            resp.record_response(self.item, actor=self.user, to_status=_MR.ADJUSTED)
        resp.record_response(self.item, actor=self.user, to_status=_MR.ADJUSTED,
                             response_note="Client posted correction")
        self.item.refresh_from_db()
        self.assertEqual(self.item.management_response_status, _MR.ADJUSTED)

    def test_agreed_to_unadjusted_requires_note(self):
        self.item.management_response_status = _MR.AGREED
        self.item.save(update_fields=["management_response_status"])
        resp.record_response(self.item, actor=self.user, to_status=_MR.UNADJUSTED,
                             response_note="Immaterial, left unadjusted")
        self.item.refresh_from_db()
        self.assertEqual(self.item.management_response_status, _MR.UNADJUSTED)

    def test_disagreed_to_unadjusted(self):
        self.item.management_response_status = _MR.DISAGREED
        self.item.save(update_fields=["management_response_status"])
        resp.record_response(self.item, actor=self.user, to_status=_MR.UNADJUSTED,
                             response_note="No adjustment agreed")
        self.item.refresh_from_db()
        self.assertEqual(self.item.management_response_status, _MR.UNADJUSTED)

    def test_adjusted_is_final(self):
        self.item.management_response_status = _MR.ADJUSTED
        self.item.save(update_fields=["management_response_status"])
        with self.assertRaises(resp.ManagementResponseError):
            resp.record_response(self.item, actor=self.user, to_status=_MR.UNADJUSTED,
                                 response_note="x")

    def test_unadjusted_is_final(self):
        self.item.management_response_status = _MR.UNADJUSTED
        self.item.save(update_fields=["management_response_status"])
        with self.assertRaises(resp.ManagementResponseError):
            resp.record_response(self.item, actor=self.user, to_status=_MR.AGREED)

    def test_invalid_transition_rejected(self):
        # not_requested → agreed is not allowed (must go through pending).
        with self.assertRaises(resp.ManagementResponseError):
            resp.record_response(self.item, actor=self.user, to_status=_MR.AGREED)

    def test_one_trail_row_per_transition(self):
        resp.record_response(self.item, actor=self.user, to_status=_MR.PENDING)
        resp.record_response(self.item, actor=self.user, to_status=_MR.AGREED)
        self.assertEqual(self.item.responses.count(), 2)
        self.assertEqual(self.item.responses.first().to_status, _MR.AGREED)

    def test_cross_tenant_actor_denied(self):
        outsider = _user(_org("B"), "b@e.com")
        with self.assertRaises(resp.ManagementResponseError):
            resp.record_response(self.item, actor=outsider, to_status=_MR.PENDING)
        self.item.refresh_from_db()
        self.assertEqual(self.item.management_response_status, _MR.NOT_REQUESTED)

    def test_response_clean_cross_tenant(self):
        r = AuditDifferenceItemResponse(
            item=self.item, summary=self.item.summary, engagement=self.eng,
            organization=_org("B"), from_status=_MR.NOT_REQUESTED, to_status=_MR.PENDING)
        with self.assertRaises(ValidationError):
            r.clean()


class ProposedAdjustmentTests(TestCase):
    def setUp(self):
        self.org = _org(); self.user = _user(self.org); self.eng = _eng(self.org)
        self.item = _item(self.org, self.eng)

    def test_create_normal_adjustment(self):
        a = adj.create_or_update_adjustment(
            self.item, actor=self.user, adjustment_type=_AT.CORRECTION,
            amount="5000", debit_account_code="5200", credit_account_code="2100",
            currency="SAR")
        self.assertEqual(a.amount, Decimal("5000.0000"))
        self.assertEqual(a.status, ProposedAuditAdjustment.Status.PROPOSED)
        self.assertEqual(self.item.proposed_adjustments.count(), 1)

    def test_amount_must_be_positive(self):
        with self.assertRaises(adj.ProposedAdjustmentError):
            adj.create_or_update_adjustment(
                self.item, actor=self.user, adjustment_type=_AT.CORRECTION,
                amount="0", debit_account_code="5200", credit_account_code="2100")

    def test_normal_requires_debit_credit(self):
        with self.assertRaises(adj.ProposedAdjustmentError):
            adj.create_or_update_adjustment(
                self.item, actor=self.user, adjustment_type=_AT.ACCRUAL,
                amount="100", debit_account_code="", credit_account_code="")

    def test_disclosure_only_no_accounts_needed(self):
        a = adj.create_or_update_adjustment(
            self.item, actor=self.user, adjustment_type=_AT.DISCLOSURE_ONLY,
            amount="100", description="Disclose contingency")
        self.assertEqual(a.adjustment_type, _AT.DISCLOSURE_ONLY)

    def test_invalid_type_rejected(self):
        with self.assertRaises(adj.ProposedAdjustmentError):
            adj.create_or_update_adjustment(
                self.item, actor=self.user, adjustment_type="bogus", amount="100")

    def test_cross_tenant_denied(self):
        outsider = _user(_org("B"), "b@e.com")
        with self.assertRaises(adj.ProposedAdjustmentError):
            adj.create_or_update_adjustment(
                self.item, actor=outsider, adjustment_type=_AT.CORRECTION,
                amount="100", debit_account_code="1", credit_account_code="2")

    def test_linked_to_same_engagement_org_summary(self):
        a = adj.create_or_update_adjustment(
            self.item, actor=self.user, adjustment_type=_AT.RECLASSIFICATION,
            amount="100", debit_account_code="1", credit_account_code="2")
        self.assertEqual(a.engagement_id, self.eng.id)
        self.assertEqual(a.organization_id, self.org.id)
        self.assertEqual(a.summary_id, self.item.summary_id)

    def test_update_existing(self):
        a = adj.create_or_update_adjustment(
            self.item, actor=self.user, adjustment_type=_AT.CORRECTION,
            amount="100", debit_account_code="1", credit_account_code="2")
        a2 = adj.create_or_update_adjustment(
            self.item, actor=self.user, adjustment_type=_AT.CORRECTION,
            amount="200", debit_account_code="1", credit_account_code="2",
            adjustment_id=a.id)
        self.assertEqual(a.id, a2.id)
        self.assertEqual(a2.amount, Decimal("200.0000"))
        self.assertEqual(self.item.proposed_adjustments.count(), 1)


class ApiTests(TestCase):
    def setUp(self):
        self.org = _org("OrgA"); self.user = _user(self.org); self.eng = _eng(self.org)
        self.item = _item(self.org, self.eng)
        self.client = APIClient(); self.client.force_authenticate(self.user)

    def test_management_response_and_list(self):
        url = f"/api/v1/audit/sad/items/{self.item.id}/management-response/"
        r = self.client.post(url, {"status": "pending"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["item"]["management_response_status"], "pending")
        lst = self.client.get(f"/api/v1/audit/sad/items/{self.item.id}/responses/")
        self.assertEqual(lst.status_code, 200)
        self.assertEqual(len(lst.json()), 1)

    def test_management_response_missing_note_400(self):
        self.item.management_response_status = _MR.PENDING
        self.item.save(update_fields=["management_response_status"])
        url = f"/api/v1/audit/sad/items/{self.item.id}/management-response/"
        r = self.client.post(url, {"status": "disagreed"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_proposed_adjustment_and_list(self):
        url = f"/api/v1/audit/sad/items/{self.item.id}/proposed-adjustment/"
        r = self.client.post(url, {
            "adjustment_type": "correction", "amount": "5000",
            "debit_account_code": "5200", "credit_account_code": "2100",
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        lst = self.client.get(f"/api/v1/audit/sad/items/{self.item.id}/proposed-adjustments/")
        self.assertEqual(lst.status_code, 200)
        self.assertEqual(len(lst.json()), 1)

    def test_cross_org_response_denied(self):
        other_org = _org("OrgB")
        other_item = _item(other_org, _eng(other_org, code="OTHER-1"))
        # other_item belongs to a different org; our user can't touch it.
        url = f"/api/v1/audit/sad/items/{other_item.id}/management-response/"
        r = self.client.post(url, {"status": "pending"}, format="json")
        self.assertEqual(r.status_code, 404)


class LedgerIsolationTests(TestCase):
    def test_no_writes_to_ledger(self):
        from apps.ledger.models import Account, JournalEntry, JournalLine
        acc, je, jl = (Account.objects.count(), JournalEntry.objects.count(),
                       JournalLine.objects.count())
        org = _org(); user = _user(org); eng = _eng(org)
        item = _item(org, eng)
        resp.record_response(item, actor=user, to_status=_MR.PENDING)
        adj.create_or_update_adjustment(
            item, actor=user, adjustment_type=_AT.CORRECTION, amount="5000",
            debit_account_code="5200", credit_account_code="2100")
        self.assertEqual(Account.objects.count(), acc)
        self.assertEqual(JournalEntry.objects.count(), je)
        self.assertEqual(JournalLine.objects.count(), jl)
