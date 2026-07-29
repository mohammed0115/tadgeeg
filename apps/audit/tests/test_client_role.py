"""TADGEEG-G4 — first-class CLIENT role: locked out of auditor surfaces."""
from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from apps.audit.engagement_models import AuditEngagement
from apps.audit.services import evidence_request as ev
from apps.authentication.models import Organization, User


def _org(name="Acme"):
    return Organization.objects.create(name=name, country=Organization.Country.SAUDI_ARABIA)


def _auditor(org, email="auditor@e.com"):
    return User.objects.create_user(
        email=email, password="StrongPass123!", full_name="Aud Itor",
        role=User.Role.SENIOR_AUDITOR, organization=org)


def _client(org, email="client@e.com"):
    return User.objects.create_user(
        email=email, password="StrongPass123!", full_name="Client Co",
        role=User.Role.CLIENT, organization=org)


def _eng(org, code="AUD-1"):
    return AuditEngagement.objects.create(
        organization=org, engagement_code=code, title="FY25",
        period_start="2025-01-01", period_end="2025-12-31")


class RoleTests(TestCase):
    def setUp(self):
        self.org = _org(); self.client_user = _client(self.org)

    def test_is_client_and_all_capabilities_false(self):
        u = self.client_user
        self.assertTrue(u.is_client)
        for cap in ("manage_organization", "approve_invoices", "review_findings",
                    "view_executive_dashboard", "edit_invoice_data"):
            self.assertFalse(u.has_role_capability(cap), cap)
        self.assertFalse(u.can_manage_users)
        self.assertFalse(u.can_view_all_data)
        self.assertFalse(u.can_generate_reports)
        self.assertEqual(u.effective_role, "client")

    def test_is_auditor_false(self):
        from apps.audit.services.evidence_lifecycle import is_auditor
        self.assertFalse(is_auditor(self.client_user))


class ApiLockoutTests(TestCase):
    def setUp(self):
        self.org = _org(); self.client_user = _client(self.org)
        self.api = APIClient(); self.api.force_authenticate(self.client_user)

    def test_client_denied_auditor_endpoints(self):
        # Every auditor-only surface must 403 for a client.
        for url in ("/api/v1/audit/assessed-risks/",
                    "/api/v1/audit/procedures/",
                    "/api/v1/audit/substantive-items/",
                    "/api/v1/audit/control-deficiencies/"):
            self.assertEqual(self.api.get(url).status_code, 403, url)


class ClientHomeRoutingTests(TestCase):
    """G4.2 — a client's home is the evidence portal, not the auditor dashboard."""

    def setUp(self):
        from io import StringIO
        from django.core.management import call_command
        from apps.billing.choices import PlanCode
        from apps.billing.models import Plan
        from apps.billing.services.subscription_service import SubscriptionService
        self.org = _org()
        if not Plan.objects.filter(code=PlanCode.BUSINESS).exists():
            call_command("seed_billing_plans", stdout=StringIO())
        svc = SubscriptionService()
        svc.activate_subscription(
            svc.create_pending_paid_subscription(
                self.org, Plan.objects.get(code=PlanCode.BUSINESS)))
        self.auditor = _auditor(self.org)
        self.client_user = _client(self.org)

    def test_client_redirected_to_portal(self):
        from django.urls import reverse
        self.client.force_login(self.client_user)
        resp = self.client.get("/dashboard/")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("frontend:client_evidence_list"))

    def test_auditor_not_redirected(self):
        self.client.force_login(self.auditor)
        resp = self.client.get("/dashboard/")
        self.assertEqual(resp.status_code, 200)


class PortalAccessTests(TestCase):
    def setUp(self):
        self.org = _org(); self.auditor = _auditor(self.org)
        self.client_user = _client(self.org)
        self.other_client = _client(self.org, "other@e.com")
        self.eng = _eng(self.org)

    def test_client_sees_only_own_assigned_requests(self):
        # A request assigned to client_user (needs a valid target -> use a
        # substantive item so the evidence request is valid).
        from apps.audit.services import substantive_testing as st
        item = st.create_item(engagement=self.eng, actor=self.auditor,
                              area="other", book_value="10")
        req = ev.create_evidence_request(
            engagement=self.eng, actor=self.auditor, title="Please send support",
            substantive_item=item, assigned_client_user=self.client_user)
        # The client can see it via the FK-scoped portal query.
        from apps.audit.evidence_models import AuditEvidenceRequest
        mine = AuditEvidenceRequest.objects.filter(
            organization=self.org, assigned_client_user=self.client_user)
        self.assertEqual(mine.count(), 1)
        self.assertEqual(mine.first().id, req.id)
        # The other client sees none.
        theirs = AuditEvidenceRequest.objects.filter(
            organization=self.org, assigned_client_user=self.other_client)
        self.assertEqual(theirs.count(), 0)
