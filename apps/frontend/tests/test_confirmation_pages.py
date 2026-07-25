"""TADGEEG-FIN-AUDIT-9C — Confirmation frontend tests (auditor + public)."""
from __future__ import annotations

from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from apps.audit.confirmation_models import AuditConfirmationRequest
from apps.audit.engagement_models import AuditEngagement
from apps.audit.services import confirmation_request as cs
from apps.authentication.models import Organization, User
from apps.billing.choices import PlanCode
from apps.billing.models import Plan
from apps.billing.services.subscription_service import SubscriptionService

_C = AuditConfirmationRequest


def _activate_subscription(org):
    if not Plan.objects.filter(code=PlanCode.BUSINESS).exists():
        call_command("seed_billing_plans", stdout=StringIO())
    svc = SubscriptionService()
    svc.activate_subscription(
        svc.create_pending_paid_subscription(org, Plan.objects.get(code=PlanCode.BUSINESS)))


def _org(name="Acme"):
    org = Organization.objects.create(name=name, country=Organization.Country.SAUDI_ARABIA)
    _activate_subscription(org)
    return org


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


class AuditorPageTests(TestCase):
    def setUp(self):
        self.org = _org(); self.auditor = _auditor(self.org); self.eng = _eng(self.org)
        self.client.force_login(self.auditor)

    def _url(self, eng=None):
        return f"{reverse('frontend:confirmations')}?engagement={(eng or self.eng).id}"

    def test_login_required(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("frontend:confirmations")).status_code, 302)

    def test_junior_denied(self):
        self.client.force_login(_junior(self.org))
        self.assertEqual(self.client.get(reverse("frontend:confirmations")).status_code, 403)

    def test_create_and_send_and_record_and_reconcile(self):
        # create
        self.client.post(reverse("frontend:confirmations"), {
            "engagement": str(self.eng.id), "action": "create",
            "party_name": "Cust A", "recorded_amount": "1000",
            "confirmation_type": "receivable", "currency": "SAR", "tolerance": "0"})
        r = AuditConfirmationRequest.objects.get(engagement=self.eng)
        # send
        self.client.post(reverse("frontend:confirmations"), {
            "engagement": str(self.eng.id), "action": "send", "confirmation": str(r.id)})
        r.refresh_from_db(); self.assertEqual(r.status, _C.Status.SENT)
        # record
        self.client.post(reverse("frontend:confirmations"), {
            "engagement": str(self.eng.id), "action": "record",
            "confirmation": str(r.id), "confirmed_amount": "700"})
        r.refresh_from_db(); self.assertEqual(r.status, _C.Status.RESPONDED)
        # reconcile → discrepancy
        resp = self.client.post(reverse("frontend:confirmations"), {
            "engagement": str(self.eng.id), "action": "reconcile", "confirmation": str(r.id)})
        r.refresh_from_db(); self.assertEqual(r.status, _C.Status.DISCREPANCY)
        self.assertContains(resp, 'class="cstat discrepancy"')

    def test_secure_link_shown_when_sent(self):
        r = cs.create_confirmation(engagement=self.eng, actor=self.auditor,
                                   party_name="X", recorded_amount="10")
        cs.send(request=r, actor=self.auditor)
        resp = self.client.get(self._url())
        self.assertContains(resp, f"/confirm/{r.response_token}/")

    def test_cross_org_engagement_ignored(self):
        other = _eng(_org("OrgB"), code="B-1")
        resp = self.client.get(self._url(other))
        self.assertContains(resp, "Choose an engagement")


class PublicRespondTests(TestCase):
    def setUp(self):
        self.org = _org(); self.auditor = _auditor(self.org); self.eng = _eng(self.org)
        self.req = cs.create_confirmation(engagement=self.eng, actor=self.auditor,
                                          party_name="Bank Ltd", recorded_amount="5000")
        cs.send(request=self.req, actor=self.auditor)
        self.anon = Client()  # not logged in

    def _url(self, token=None):
        return reverse("frontend:confirmation_respond", args=[token or self.req.response_token])

    def test_anonymous_can_open_page(self):
        resp = self.anon.get(self._url())
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Balance Confirmation")
        self.assertContains(resp, "5000")

    def test_agree_records_recorded_amount(self):
        resp = self.anon.post(self._url(), {"agree": "1"})
        self.assertEqual(resp.status_code, 200)
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, _C.Status.RESPONDED)
        self.assertEqual(self.req.confirmed_amount, Decimal("5000"))

    def test_differ_records_entered_amount(self):
        resp = self.anon.post(self._url(), {"agree": "0", "confirmed_amount": "4800",
                                            "note": "we show less"})
        self.req.refresh_from_db()
        self.assertEqual(self.req.confirmed_amount, Decimal("4800"))
        self.assertContains(resp, "Thank you")

    def test_invalid_token_404(self):
        import uuid
        self.assertEqual(self.anon.get(self._url(uuid.uuid4())).status_code, 404)

    def test_already_responded_blocks_further(self):
        cs.record_response(request=self.req, confirmed_amount="5000")
        resp = self.anon.post(self._url(), {"agree": "1", "confirmed_amount": "1"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "already been responded")

    def test_public_response_no_ledger_write(self):
        from apps.ledger.models import Account, JournalEntry, JournalLine
        acc, je, jl = (Account.objects.count(), JournalEntry.objects.count(),
                       JournalLine.objects.count())
        self.anon.post(self._url(), {"agree": "1"})
        self.assertEqual(Account.objects.count(), acc)
        self.assertEqual(JournalEntry.objects.count(), je)
        self.assertEqual(JournalLine.objects.count(), jl)
