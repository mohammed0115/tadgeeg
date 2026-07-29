"""Tests for the seed_demo_engagement management command (TADGEEG demo data)."""
from __future__ import annotations

from io import StringIO

from django.core.management import CommandError, call_command
from django.test import TestCase

from apps.audit.control_deficiency_models import AuditControlDeficiency
from apps.audit.engagement_models import AuditEngagement
from apps.audit.issue_models import AuditIssue
from apps.audit.member_models import EngagementMember
from apps.audit.report_models import EngagementReport
from apps.authentication.models import Organization, User


def _demo_user():
    org = Organization.objects.create(
        name="Demo Audit Firm", country=Organization.Country.SAUDI_ARABIA)
    return User.objects.create_user(
        email="demo@finai.sa", password="DemoDashboard123!", full_name="Demo",
        role=User.Role.SENIOR_AUDITOR, organization=org)


class SeedDemoEngagementTests(TestCase):
    def test_seeds_full_engagement(self):
        user = _demo_user()
        call_command("seed_demo_engagement", stdout=StringIO())
        eng = AuditEngagement.objects.get(
            organization=user.organization, engagement_code="DEMO-FY25")
        self.assertEqual(eng.assessed_risks.count(), 3)
        self.assertEqual(AuditControlDeficiency.objects.filter(engagement=eng).count(), 2)
        self.assertEqual(AuditIssue.objects.filter(engagement=eng).count(), 3)
        self.assertEqual(EngagementReport.objects.filter(engagement=eng).count(), 1)
        self.assertEqual(EngagementMember.objects.filter(engagement=eng, is_active=True).count(), 1)
        # A closed issue exists (the loop end-state) and one deficiency is risk-linked.
        self.assertTrue(AuditIssue.objects.filter(engagement=eng, status="closed").exists())
        self.assertTrue(AuditControlDeficiency.objects.filter(
            engagement=eng, assessed_risk__isnull=False).exists())

    def test_idempotent_without_force(self):
        _demo_user()
        call_command("seed_demo_engagement", stdout=StringIO())
        call_command("seed_demo_engagement", stdout=StringIO())  # no-op
        self.assertEqual(AuditEngagement.objects.filter(engagement_code="DEMO-FY25").count(), 1)
        self.assertEqual(AuditIssue.objects.count(), 3)

    def test_force_recreates(self):
        _demo_user()
        call_command("seed_demo_engagement", stdout=StringIO())
        first = AuditEngagement.objects.get(engagement_code="DEMO-FY25").id
        call_command("seed_demo_engagement", "--force", stdout=StringIO())
        second = AuditEngagement.objects.get(engagement_code="DEMO-FY25").id
        self.assertNotEqual(first, second)
        self.assertEqual(AuditIssue.objects.count(), 3)

    def test_missing_user_errors(self):
        with self.assertRaises(CommandError):
            call_command("seed_demo_engagement", email="nobody@x.com", stdout=StringIO())
