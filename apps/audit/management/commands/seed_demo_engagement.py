"""Seed a fully-populated demo audit engagement (TADGEEG).

Builds one ``AuditEngagement`` with linked risks, procedures, findings, issues,
a report and a team member — entirely through the existing deterministic
services — so the audit workflow is demonstrable end-to-end from the UI without
importing real data. Idempotent per (organization, engagement_code): re-running
is a no-op unless ``--force`` recreates the demo engagement.

Deterministic, organization-scoped, advisory. No ledger writes.
"""
from __future__ import annotations

from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.audit.assessed_risk_models import AssessedRisk
from apps.audit.control_deficiency_models import AuditControlDeficiency
from apps.audit.engagement_models import AuditEngagement
from apps.audit.procedure_models import AuditProcedure
from apps.audit.services import assessed_risk as ar
from apps.audit.services import audit_issue as ai
from apps.audit.services import audit_procedure as ap
from apps.audit.services import engagement_member as em
from apps.audit.services import management_letter as ml
from apps.audit.services import report_builder as rb
from apps.authentication.models import User

_R = AssessedRisk
_P = AuditProcedure
_Cls = AuditControlDeficiency.Classification
_Area = AuditControlDeficiency.Area
_CODE = "DEMO-FY25"


class Command(BaseCommand):
    help = "Seed a fully-populated demo audit engagement for the demo user's organization."

    def add_arguments(self, parser):
        parser.add_argument("--email", default="demo@finai.sa",
                            help="Email of an auditor whose organization gets the demo engagement.")
        parser.add_argument("--force", action="store_true",
                            help="Delete and recreate the demo engagement if it already exists.")

    def handle(self, *args, **opts):
        actor = User.objects.filter(email=opts["email"]).first()
        if actor is None:
            raise CommandError(
                f"No user {opts['email']!r}. Run create_demo_user first.")
        org = getattr(actor, "organization", None)
        if org is None:
            raise CommandError(f"User {opts['email']!r} has no organization.")

        existing = AuditEngagement.objects.filter(
            organization=org, engagement_code=_CODE).first()
        if existing is not None:
            if not opts["force"]:
                self.stdout.write(self.style.WARNING(
                    f"Demo engagement {_CODE} already exists (id={existing.id}). "
                    "Use --force to recreate."))
                return
            existing.delete()
            self.stdout.write(self.style.WARNING(f"Deleted existing {_CODE}."))

        eng = AuditEngagement.objects.create(
            organization=org, engagement_code=_CODE,
            title="Demo Trading Co. — FY2025 financial-statement audit",
            description="Illustrative engagement seeded for demonstration.",
            engagement_type=AuditEngagement.EngagementType.FINANCIAL_STATEMENT,
            period_start=date(2025, 1, 1), period_end=date(2025, 12, 31),
            stage=AuditEngagement.Stage.FIELDWORK,
            created_by=actor)

        # ── Assessed risks (ISA 315) + responsive procedures (ISA 330) ──
        risks = []
        risk_specs = [
            dict(title="Revenue recognition — cut-off", fs_area="revenue",
                 assertion=_R.Assertion.CUTOFF, inherent_risk=_R.InherentRisk.SIGNIFICANT,
                 control_risk=_R.ControlRisk.MEDIUM, is_significant=True, is_fraud_risk=True,
                 description="Risk that revenue is recorded in the wrong period near year-end."),
            dict(title="Completeness of trade payables", fs_area="payables",
                 assertion=_R.Assertion.COMPLETENESS, inherent_risk=_R.InherentRisk.HIGH,
                 control_risk=_R.ControlRisk.MEDIUM, is_significant=False, is_fraud_risk=False,
                 description="Unrecorded liabilities at period end."),
            dict(title="Inventory valuation — obsolescence", fs_area="inventory",
                 assertion=_R.Assertion.VALUATION, inherent_risk=_R.InherentRisk.MEDIUM,
                 control_risk=_R.ControlRisk.HIGH, is_significant=False, is_fraud_risk=False,
                 description="Slow-moving inventory may be carried above NRV."),
        ]
        for spec in risk_specs:
            risks.append(ar.create_risk(engagement=eng, actor=actor, **spec))

        proc_specs = [
            (0, "Cut-off testing of sales around year-end", _P.Nature.TEST_OF_DETAILS,
             _P.Timing.YEAR_END, _P.Extent.INCREASED),
            (0, "Substantive analytical review of monthly revenue", _P.Nature.SUBSTANTIVE_ANALYTICAL,
             _P.Timing.YEAR_END, _P.Extent.STANDARD),
            (1, "Search for unrecorded liabilities", _P.Nature.TEST_OF_DETAILS,
             _P.Timing.SUBSEQUENT, _P.Extent.STANDARD),
            (2, "NRV testing of aged inventory lines", _P.Nature.TEST_OF_DETAILS,
             _P.Timing.YEAR_END, _P.Extent.INCREASED),
        ]
        for ridx, title, nature, timing, extent in proc_specs:
            ap.create_procedure(engagement=eng, actor=actor, title=title,
                                assessed_risk=risks[ridx], nature=nature,
                                timing=timing, extent=extent)

        # ── Control deficiencies (ISA 265) — feed findings register + letter ──
        d1 = ml.create_deficiency(
            engagement=eng, actor=actor, classification=_Cls.SIGNIFICANT_DEFICIENCY,
            area=_Area.REVENUE, title="Manual revenue cut-off control not evidenced",
            description="Period-end cut-off review is performed but not documented.",
            potential_effect="Revenue could be misstated across period boundary.",
            recommendation="Formalize and evidence the month-end cut-off review.")
        # Link a deficiency to a risk so the register shows a traced finding.
        d1.assessed_risk = risks[0]
        d1.save(update_fields=["assessed_risk", "updated_at"])
        ml.create_deficiency(
            engagement=eng, actor=actor, classification=_Cls.OTHER_DEFICIENCY,
            area=_Area.INVENTORY, title="Inventory obsolescence review is ad-hoc",
            description="No periodic NRV assessment schedule exists.",
            recommendation="Introduce a quarterly obsolescence review.")

        # ── Issues (remediation → closure loop) ──
        ai.create_issue(engagement=eng, actor=actor, severity="high",
                        title="Evidence cut-off control operating effectiveness",
                        owner="Financial Controller",
                        due_date=timezone.now().date() + timedelta(days=14),
                        remediation_plan="Collect sign-off logs for Q4 cut-off reviews.")
        ai.create_issue(engagement=eng, actor=actor, severity="critical",
                        title="Overdue: confirm year-end bank balances",
                        owner="Treasury",
                        due_date=timezone.now().date() - timedelta(days=5))
        closed = ai.create_issue(engagement=eng, actor=actor, severity="low",
                                 title="Minor GL account mapping cleanup", owner="Accounting")
        ai.set_status(issue=closed, actor=actor, status="closed",
                      note="Mapping corrected and re-imported.")

        # ── Engagement report (ISA 700-safe draft) ──
        rb.create_report(engagement=eng, actor=actor,
                         title="Audit results report — Demo Trading Co. FY2025")

        # ── Team (ISA 220) ──
        em.assign(engagement=eng, actor=actor, user=actor,
                  role="partner", responsibilities="Engagement partner sign-off")

        self.stdout.write(self.style.SUCCESS(
            f"✅ Seeded demo engagement {_CODE} (id={eng.id}) in org {org.name!r}:"))
        self.stdout.write(
            f"   {len(risks)} risks · {len(proc_specs)} procedures · 2 deficiencies · "
            "3 issues · 1 report · 1 team member")
        self.stdout.write(f"   Open at: /audit/engagements/{eng.id}/")
