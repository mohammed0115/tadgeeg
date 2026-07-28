"""TADGEEG-G0 — engagement audit-trail wiring into the ActivityLog hash chain."""
from __future__ import annotations

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.activity_logs.models import ActivityLog
from apps.audit.engagement_models import AuditEngagement
from apps.audit.services import audit_trail
from apps.authentication.models import Organization, User
from apps.billing.choices import PlanCode
from apps.billing.models import Plan
from apps.billing.services.subscription_service import SubscriptionService

_Act = ActivityLog.Action


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


def _eng(org, code="AUD-1"):
    return AuditEngagement.objects.create(
        organization=org, engagement_code=code, title="FY25",
        period_start="2025-01-01", period_end="2025-12-31")


class ServiceTests(TestCase):
    def setUp(self):
        self.org = _org(); self.auditor = _auditor(self.org); self.eng = _eng(self.org)

    def test_record_stage_change_writes_chained_row(self):
        row = audit_trail.record_stage_change(
            engagement=self.eng, actor=self.auditor,
            old_stage="acceptance", new_stage="planning")
        self.assertIsNotNone(row)
        self.assertEqual(row.action, _Act.ENGAGEMENT_STAGE_CHANGED)
        self.assertEqual(row.entity_type, "audit_engagement")
        self.assertEqual(row.entity_id, str(self.eng.pk))
        self.assertEqual(row.organization_id, self.org.id)
        self.assertEqual(row.metadata["old_stage"], "acceptance")
        self.assertEqual(row.metadata["new_stage"], "planning")
        # Tamper-evident: the chain hash is computed on save.
        self.assertTrue(row.chain_hash)

    def test_chain_links_successive_events(self):
        a = audit_trail.record_stage_change(engagement=self.eng, actor=self.auditor,
                                            old_stage="acceptance", new_stage="planning")
        b = audit_trail.record_stage_change(engagement=self.eng, actor=self.auditor,
                                            old_stage="planning", new_stage="fieldwork")
        self.assertEqual(b.previous_hash, a.chain_hash)

    def test_record_tolerates_unusual_input_without_raising(self):
        # The helper must never raise into its caller. ActivityLog.save() does
        # not run choices validation, so an unusual action is stored rather than
        # rejected — the guarantee we assert is simply "no exception escapes".
        try:
            audit_trail.record(organization=None, actor=self.auditor,
                               action="unusual_action", entity_type="x")
        except Exception as exc:  # noqa: BLE001
            self.fail(f"record() must not raise, but raised: {exc}")

    def test_record_report_issued(self):
        row = audit_trail.record_report_issued(
            engagement=self.eng, actor=self.auditor,
            report_kind="readiness_workpaper", reference="wp-123")
        self.assertEqual(row.action, _Act.REPORT_GENERATED)
        self.assertEqual(row.entity_type, "readiness_workpaper")
        self.assertEqual(row.entity_id, "wp-123")
        self.assertEqual(row.metadata["report_kind"], "readiness_workpaper")

    def test_finding_status_helper_shape(self):
        class _F:  # minimal duck-typed finding
            pk = "f-1"; reference = "GL-1"; organization = self.org
        row = audit_trail.record_finding_status_change(
            finding=_F(), actor=self.auditor,
            old_status="candidate", new_status="accepted", reason="reviewed")
        self.assertEqual(row.action, _Act.FINDING_STATUS_CHANGED)
        self.assertEqual(row.entity_id, "f-1")
        self.assertEqual(row.metadata["new_status"], "accepted")


class WorkspaceIntegrationTests(TestCase):
    def setUp(self):
        self.org = _org(); self.auditor = _auditor(self.org); self.eng = _eng(self.org)
        self.client.force_login(self.auditor)

    def _url(self):
        from django.urls import reverse
        return reverse("frontend:engagement_workspace", args=[self.eng.id])

    def test_set_stage_writes_audit_event(self):
        before = ActivityLog.objects.filter(action=_Act.ENGAGEMENT_STAGE_CHANGED).count()
        self.client.post(self._url(), {"action": "set_stage", "stage": "planning"})
        self.eng.refresh_from_db()
        self.assertEqual(self.eng.stage, "planning")
        rows = ActivityLog.objects.filter(action=_Act.ENGAGEMENT_STAGE_CHANGED)
        self.assertEqual(rows.count(), before + 1)
        self.assertEqual(rows.latest("created_at").entity_id, str(self.eng.pk))

    def test_setting_same_stage_writes_no_event(self):
        # Engagement starts at 'acceptance'; setting it again is a no-op for the trail.
        self.client.post(self._url(), {"action": "set_stage", "stage": self.eng.stage})
        self.assertEqual(
            ActivityLog.objects.filter(action=_Act.ENGAGEMENT_STAGE_CHANGED).count(), 0)
