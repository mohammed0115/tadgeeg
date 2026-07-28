"""TADGEEG-FIN-AUDIT-9F — Evidence linkage tests.

An evidence request (6A) can now target a substantive-test item (9D) or an
external confirmation (9C) in addition to a GL finding / SAD item. Tests cover
the widened ``clean()`` rule, the two ``request_evidence`` helpers, org-scoping,
and that no ledger write occurs.
"""
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.audit.confirmation_models import AuditConfirmationRequest
from apps.audit.engagement_models import AuditEngagement
from apps.audit.evidence_models import AuditEvidenceRequest
from apps.audit.services import confirmation_request as cs
from apps.audit.services import substantive_testing as st
from apps.authentication.models import Organization, User

_ER = AuditEvidenceRequest


def _org(name="Acme"):
    return Organization.objects.create(name=name, country=Organization.Country.SAUDI_ARABIA)


def _auditor(org, email="auditor@e.com"):
    return User.objects.create_user(
        email=email, password="StrongPass123!", full_name="Aud Itor",
        role=User.Role.SENIOR_AUDITOR, organization=org)


def _eng(org, code="AUD-1"):
    return AuditEngagement.objects.create(
        organization=org, engagement_code=code, title="FY25",
        period_start="2025-01-01", period_end="2025-12-31")


class Base(TestCase):
    def setUp(self):
        self.org = _org(); self.auditor = _auditor(self.org); self.eng = _eng(self.org)

    def _variance_item(self):
        return st.create_item(
            engagement=self.eng, actor=self.auditor,
            area=st.SubstantiveTestItem.Area.INVENTORY, book_value="400",
            inputs={"quantity": "30", "unit_cost": "12.5"})  # 400 vs 375 → variance

    def _discrepancy_conf(self):
        c = cs.create_confirmation(
            engagement=self.eng, actor=self.auditor, party_name="Bank X",
            recorded_amount="1000", confirmation_type="bank", tolerance="0")
        cs.send(request=c, actor=self.auditor)
        cs.record_response(request=c, actor=self.auditor, confirmed_amount="900")
        cs.reconcile(request=c, actor=self.auditor)  # 1000 vs 900 → discrepancy
        return c


# ── Widened clean() rule ─────────────────────────────────────────────────────
class CleanRuleTests(Base):
    def test_substantive_only_target_is_valid(self):
        item = self._variance_item()
        req = AuditEvidenceRequest(engagement=self.eng, organization=self.org,
                                   substantive_item=item, title="Support")
        req.full_clean(exclude=["requested_by", "assigned_to",
                                "assigned_client_user", "request_number"])  # no raise

    def test_confirmation_only_target_is_valid(self):
        conf = self._discrepancy_conf()
        req = AuditEvidenceRequest(engagement=self.eng, organization=self.org,
                                   confirmation_request=conf, title="Support")
        req.full_clean(exclude=["requested_by", "assigned_to",
                                "assigned_client_user", "request_number"])  # no raise

    def test_no_target_still_rejected(self):
        req = AuditEvidenceRequest(engagement=self.eng, organization=self.org,
                                   title="Support")
        with self.assertRaises(ValidationError):
            req.full_clean(exclude=["requested_by", "assigned_to",
                                    "assigned_client_user", "request_number"])

    def test_cross_org_substantive_rejected(self):
        other = _eng(_org("OrgB"), code="B-1")
        foreign = st.create_item(engagement=other, actor=_auditor(other.organization, "o@e.com"),
                                 area=st.SubstantiveTestItem.Area.OTHER, book_value="1")
        req = AuditEvidenceRequest(engagement=self.eng, organization=self.org,
                                   substantive_item=foreign, title="X")
        with self.assertRaises(ValidationError):
            req.full_clean(exclude=["requested_by", "assigned_to",
                                    "assigned_client_user", "request_number"])


# ── request_evidence helpers ─────────────────────────────────────────────────
class RequestEvidenceTests(Base):
    def test_substantive_variance_raises_linked_request(self):
        item = self._variance_item()
        req = st.request_evidence(item=item, actor=self.auditor)
        self.assertEqual(req.substantive_item_id, item.id)
        self.assertEqual(req.organization_id, self.org.id)
        self.assertEqual(req.priority, _ER.Priority.HIGH)      # variance → high
        self.assertEqual(req.request_reason, _ER.RequestReason.SUPPORTING_DOCUMENT)
        self.assertEqual(item.evidence_requests.count(), 1)

    def test_confirmation_discrepancy_raises_linked_request(self):
        conf = self._discrepancy_conf()
        req = cs.request_evidence(request=conf, actor=self.auditor)
        self.assertEqual(req.confirmation_request_id, conf.id)
        self.assertEqual(req.priority, _ER.Priority.HIGH)      # discrepancy → high
        self.assertEqual(req.request_reason, _ER.RequestReason.BANK_SUPPORT)  # bank type
        self.assertEqual(conf.evidence_requests.count(), 1)


# ── No ledger writes ─────────────────────────────────────────────────────────
class NoLedgerTests(Base):
    def test_linkage_never_writes_to_ledger(self):
        from apps.ledger.models import Account, JournalEntry, JournalLine
        acc, je, jl = (Account.objects.count(), JournalEntry.objects.count(),
                       JournalLine.objects.count())
        st.request_evidence(item=self._variance_item(), actor=self.auditor)
        cs.request_evidence(request=self._discrepancy_conf(), actor=self.auditor)
        self.assertEqual(Account.objects.count(), acc)
        self.assertEqual(JournalEntry.objects.count(), je)
        self.assertEqual(JournalLine.objects.count(), jl)
