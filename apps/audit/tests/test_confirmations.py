"""TADGEEG-FIN-AUDIT-9C — External Confirmations tests (service + API)."""
from __future__ import annotations

from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.audit.confirmation_models import AuditConfirmationRequest
from apps.audit.engagement_models import AuditEngagement
from apps.audit.services import confirmation_request as cs
from apps.authentication.models import Organization, User

_C = AuditConfirmationRequest
_S = _C.Status


def _org(name="Acme"):
    return Organization.objects.create(name=name, country=Organization.Country.SAUDI_ARABIA)


def _auditor(org, email="auditor@e.com"):
    return User.objects.create_user(
        email=email, password="StrongPass123!", full_name="Aud Itor",
        role=User.Role.SENIOR_AUDITOR, organization=org)


def _junior(org, email="junior@e.com"):
    return User.objects.create_user(
        email=email, password="StrongPass123!", full_name="Jun Ior",
        role=User.Role.JUNIOR_AUDITOR, organization=org)


def _eng(org, code="AUD-1"):
    return AuditEngagement.objects.create(
        organization=org, engagement_code=code, title="FY25",
        period_start="2025-01-01", period_end="2025-12-31")


class Base(TestCase):
    def setUp(self):
        self.org = _org(); self.auditor = _auditor(self.org); self.eng = _eng(self.org)

    def _make(self, recorded="1000", tolerance="0", **kw):
        return cs.create_confirmation(
            engagement=self.eng, actor=self.auditor, party_name="Customer A",
            recorded_amount=recorded, tolerance=tolerance, **kw)


class ServiceTests(Base):
    def test_create_defaults_and_numbering(self):
        r1 = self._make(); r2 = self._make()
        self.assertEqual(r1.status, _S.DRAFT)
        self.assertEqual(r1.request_number, "CNF-00001")
        self.assertEqual(r2.request_number, "CNF-00002")
        self.assertIsNotNone(r1.response_token)

    def test_full_matched_flow(self):
        r = self._make(recorded="1000", tolerance="0")
        cs.send(request=r, actor=self.auditor)
        self.assertEqual(r.status, _S.SENT)
        cs.record_response(request=r, confirmed_amount="1000")
        self.assertEqual(r.status, _S.RESPONDED)
        self.assertEqual(r.difference, Decimal("0"))
        cs.reconcile(request=r, actor=self.auditor)
        self.assertEqual(r.status, _S.MATCHED)

    def test_discrepancy_flow(self):
        r = self._make(recorded="1000", tolerance="10")
        cs.send(request=r, actor=self.auditor)
        cs.record_response(request=r, confirmed_amount="800")  # diff 200 > tol 10
        cs.reconcile(request=r, actor=self.auditor)
        self.assertEqual(r.status, _S.DISCREPANCY)
        self.assertEqual(r.difference, Decimal("200"))
        self.assertFalse(r.is_within_tolerance)

    def test_within_tolerance_matches(self):
        r = self._make(recorded="1000", tolerance="50")
        cs.send(request=r, actor=self.auditor)
        cs.record_response(request=r, confirmed_amount="970")  # diff 30 <= 50
        cs.reconcile(request=r, actor=self.auditor)
        self.assertEqual(r.status, _S.MATCHED)

    def test_no_reply(self):
        r = self._make()
        cs.send(request=r, actor=self.auditor)
        cs.mark_no_reply(request=r, actor=self.auditor)
        self.assertEqual(r.status, _S.NO_REPLY)

    def test_cancel(self):
        r = self._make()
        cs.cancel(request=r, actor=self.auditor)
        self.assertEqual(r.status, _S.CANCELLED)

    def test_invalid_transitions(self):
        r = self._make()
        with self.assertRaises(cs.ConfirmationError):
            cs.record_response(request=r, confirmed_amount="1")  # not sent yet
        with self.assertRaises(cs.ConfirmationError):
            cs.reconcile(request=r, actor=self.auditor)          # not responded
        cs.send(request=r, actor=self.auditor)
        cs.mark_no_reply(request=r, actor=self.auditor)
        with self.assertRaises(cs.ConfirmationError):
            cs.cancel(request=r, actor=self.auditor)             # final

    def test_status_counts(self):
        m = self._make(); cs.send(request=m, actor=self.auditor)
        cs.record_response(request=m, confirmed_amount="1000")
        cs.reconcile(request=m, actor=self.auditor)
        self._make()  # draft
        counts = cs.status_counts(organization=self.org, engagement=self.eng)
        self.assertEqual(counts["matched"], 1)
        self.assertEqual(counts["draft"], 1)
        self.assertEqual(counts["total"], 2)


class ApiTests(Base):
    def setUp(self):
        super().setUp()
        self.api = APIClient(); self.api.force_authenticate(self.auditor)

    def test_create_list_detail(self):
        resp = self.api.post("/api/v1/audit/confirmations/", {
            "engagement": str(self.eng.id), "party_name": "Cust",
            "recorded_amount": "5000", "confirmation_type": "receivable"}, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        cid = resp.json()["id"]
        self.assertTrue(self.api.get("/api/v1/audit/confirmations/").json())
        self.assertEqual(self.api.get(f"/api/v1/audit/confirmations/{cid}/").status_code, 200)

    def test_action_flow(self):
        r = self._make(recorded="1000")
        base = f"/api/v1/audit/confirmations/{r.id}/"
        self.assertEqual(self.api.post(base + "send/", {}, format="json").status_code, 200)
        rec = self.api.post(base + "record/", {"confirmed_amount": "900"}, format="json")
        self.assertEqual(rec.json()["status"], "responded")
        rc = self.api.post(base + "reconcile/", {}, format="json")
        self.assertEqual(rc.json()["status"], "discrepancy")

    def test_junior_denied(self):
        api = APIClient(); api.force_authenticate(_junior(self.org))
        self.assertEqual(api.get("/api/v1/audit/confirmations/").status_code, 403)

    def test_cross_org_404(self):
        other = _eng(_org("OrgB"), code="B-1")
        oa = _auditor(other.organization, "o@e.com")
        foreign = cs.create_confirmation(engagement=other, actor=oa,
                                         party_name="X", recorded_amount="1")
        self.assertEqual(self.api.get(
            f"/api/v1/audit/confirmations/{foreign.id}/").status_code, 404)


class LedgerIsolationTests(Base):
    def test_confirmation_flow_never_writes_to_ledger(self):
        from apps.ledger.models import Account, JournalEntry, JournalLine
        acc, je, jl = (Account.objects.count(), JournalEntry.objects.count(),
                       JournalLine.objects.count())
        r = self._make(recorded="1000")
        cs.send(request=r, actor=self.auditor)
        cs.record_response(request=r, confirmed_amount="500")
        cs.reconcile(request=r, actor=self.auditor)
        self.assertEqual(Account.objects.count(), acc)
        self.assertEqual(JournalEntry.objects.count(), je)
        self.assertEqual(JournalLine.objects.count(), jl)
