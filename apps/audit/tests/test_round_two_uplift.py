"""Round-two enterprise uplift tests.

Covers everything added in the "push to 10/10" pass:
  • AI Safety: prompts, redaction, model registry, budget, runtime
  • ISA 240 fraud response
  • ISA 300 planning
  • ISA 330 risk responses
  • Generic SoD on JournalEntry posting
  • WORM attestation
  • Zakat calculator
  • SOCPA chart-of-accounts overlay
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings


# ─── AI Safety ──────────────────────────────────────────────────────────────
class PromptRegistryTests(TestCase):
    def setUp(self):
        from apps.ai_safety import prompts
        prompts.reset_registry_for_tests()

    def test_register_and_get(self):
        from apps.ai_safety.prompts import register, get
        tpl = register(name="t.one", version=1, body="hello {name}")
        self.assertEqual(tpl.version, 1)
        self.assertEqual(len(tpl.sha256), 64)
        out = get("t.one").render(name="world")
        self.assertEqual(out, "hello world")

    def test_re_registering_same_body_is_ok(self):
        from apps.ai_safety.prompts import register
        a = register(name="t.idem", version=1, body="same")
        b = register(name="t.idem", version=1, body="same")
        self.assertEqual(a.sha256, b.sha256)

    def test_re_registering_different_body_raises(self):
        from apps.ai_safety.prompts import register, PromptDriftError
        register(name="t.drift", version=1, body="v1")
        with self.assertRaises(PromptDriftError):
            register(name="t.drift", version=1, body="v1 plus changes")

    def test_get_latest_when_version_omitted(self):
        from apps.ai_safety.prompts import register, get
        register(name="t.multi", version=1, body="v1")
        register(name="t.multi", version=2, body="v2")
        register(name="t.multi", version=3, body="v3")
        self.assertEqual(get("t.multi").version, 3)
        self.assertEqual(get("t.multi", 2).version, 2)


class RedactionTests(TestCase):
    def test_redacts_saudi_hawiya(self):
        from apps.ai_safety.redaction import redact
        out = redact("ID 1012345678 belongs to John")
        self.assertIn("[REDACTED]", out)
        self.assertNotIn("1012345678", out)

    def test_redacts_iqama(self):
        from apps.ai_safety.redaction import redact
        out = redact("Iqama: 2098765432")
        self.assertIn("[REDACTED]", out)

    def test_redacts_iban(self):
        from apps.ai_safety.redaction import redact
        out = redact("Send to SA0380000000608010167519")
        self.assertNotIn("SA0380000000608010167519", out)

    def test_redacts_credit_card_luhn(self):
        from apps.ai_safety.redaction import redact
        # 4111 1111 1111 1111 is a textbook valid PAN
        out = redact("Card 4111 1111 1111 1111 charged")
        self.assertIn("[REDACTED]", out)

    def test_leaves_random_digit_strings_alone(self):
        from apps.ai_safety.redaction import redact
        # Invoice number, not a Luhn-valid PAN, not Saudi-ID-shaped.
        out = redact("Invoice number 9876543212")
        # 10 digits starting with 9 — not Hawiya (must start with 1)
        # and not a Luhn PAN.
        self.assertIn("9876543212", out)

    def test_walks_nested_structures(self):
        from apps.ai_safety.redaction import redact
        out = redact({"a": ["Iqama 2012345678", "ok"], "b": "fine"})
        self.assertNotIn("2012345678", str(out))
        self.assertEqual(out["b"], "fine")


class ModelRegistryTests(TestCase):
    def test_known_model_returns_spec(self):
        from apps.ai_safety.models_registry import get_model
        spec = get_model("claude-opus-4-7")
        self.assertEqual(spec.provider, "anthropic")
        self.assertGreater(spec.context_window, 100_000)

    def test_unknown_model_raises(self):
        from apps.ai_safety.models_registry import get_model, ModelNotApprovedError
        with self.assertRaises(ModelNotApprovedError):
            get_model("gpt-9-nonexistent")

    def test_cost_calculation(self):
        from apps.ai_safety.models_registry import get_model
        spec = get_model("claude-haiku-4-5")
        cost = spec.cost(input_tokens=1000, output_tokens=500)
        # haiku: 0.0008 / 1k input + 0.004 / 1k output
        self.assertEqual(cost, Decimal("0.0008") + Decimal("0.002"))


@override_settings(
    AI_BUDGET_DAILY_USD=Decimal("10"),
    AI_BUDGET_MONTHLY_USD=Decimal("100"),
)
class BudgetTests(TestCase):
    def setUp(self):
        from apps.billing.tests._factories import make_org
        self.org = make_org()

    def test_within_budget_passes(self):
        from apps.ai_safety.budget import assert_within_budget
        # Should not raise:
        assert_within_budget(self.org, projected_cost=Decimal("1"))

    def test_exceeds_daily_raises(self):
        from apps.ai_safety.budget import (
            assert_within_budget, record_call, BudgetExceededError,
        )
        record_call(self.org, model="claude-opus-4-7",
                    input_tokens=0, output_tokens=0, cost=Decimal("9"))
        with self.assertRaises(BudgetExceededError) as ctx:
            assert_within_budget(self.org, projected_cost=Decimal("5"))
        self.assertEqual(ctx.exception.scope, "daily")

    def test_records_and_summary(self):
        from apps.ai_safety.budget import record_call, summary
        record_call(self.org, model="claude-opus-4-7",
                    input_tokens=100, output_tokens=50, cost=Decimal("0.05"))
        s = summary(self.org)
        self.assertEqual(Decimal(s["daily"]["spent"]), Decimal("0.05"))


@override_settings(
    AI_BUDGET_DAILY_USD=Decimal("100"),
    AI_BUDGET_MONTHLY_USD=Decimal("1000"),
)
class RuntimeFacadeTests(TestCase):
    def setUp(self):
        from apps.billing.tests._factories import make_org
        from apps.ai_safety import prompts, runtime
        prompts.reset_registry_for_tests()
        prompts.register(name="t.run", version=1,
                         body="Tell me about {topic}")
        self.org = make_org()
        # Fake backend records what was sent.
        self.calls = []

        def backend(model, prompt, max_out):
            self.calls.append((model, prompt, max_out))
            return ("ok", 10, 5)

        runtime.set_backend(backend)

    def test_call_goes_through_facade_and_records_cost(self):
        from apps.ai_safety.runtime import call_model
        text, meta = call_model(
            organization=self.org,
            prompt_name="t.run",
            prompt_kwargs={"topic": "Iqama 2012345678"},
            model="claude-haiku-4-5",
            max_output_tokens=100,
        )
        self.assertEqual(text, "ok")
        # PII redacted before going to the backend.
        sent_prompt = self.calls[0][1]
        self.assertNotIn("2012345678", sent_prompt)
        self.assertGreater(meta.cost_usd, Decimal("0"))


# ─── ISA 240 / 300 / 330 ────────────────────────────────────────────────────
class ISA240Tests(TestCase):
    def test_response_plan_includes_mgmt_override_always(self):
        from apps.audit.services.isa240_fraud_response import (
            assess_fraud_responses,
        )
        plan = assess_fraud_responses([])
        # Even with no specific risks, §32 procedures are MANDATORY.
        names = {p.name for p in plan.mgmt_override_procedures}
        self.assertIn("journal_entry_testing", names)
        self.assertIn("estimates_bias_review", names)
        self.assertIn("significant_unusual_transactions", names)

    def test_specific_risk_drives_specific_procedures(self):
        from apps.audit.services.isa240_fraud_response import (
            FraudRiskFactor, assess_fraud_responses,
        )
        plan = assess_fraud_responses([
            FraudRiskFactor(
                name="duplicate-billing-vendor-X",
                description="Vendor X has 3 duplicate invoices",
                severity="high",
                detected_by="duplicate",
            ),
        ])
        names = {p.name for p in plan.procedures}
        self.assertIn("vouch_to_original", names)
        self.assertIn("vendor_confirmation", names)
        self.assertEqual(plan.overall_severity, "high")


class ISA300Tests(TestCase):
    def test_strategy_for_listed_first_year_subsidiary(self):
        from apps.audit.services.isa300_planning import (
            EngagementContext, build_audit_strategy, build_audit_plan,
        )
        ctx = EngagementContext(
            organization_name="Acme PLC",
            reporting_period="FY2026",
            industry="manufacturing",
            revenue_base=Decimal("1000000000"),
            is_listed=True,
            is_first_year=True,
            has_subsidiaries=True,
        )
        strat = build_audit_strategy(ctx)
        self.assertIn("Profit before tax", strat.materiality_benchmark)
        self.assertIn("EQR partner", strat.resourcing)
        self.assertIn("Opening balances", strat.direction)
        self.assertIn("Component-auditor coordination", strat.direction)

        plan = build_audit_plan(strat)
        proc_names = {p.name for p in plan.procedures}
        self.assertIn("Journal-entry testing (ISA 240 §32)", proc_names)
        self.assertIn("Going-concern review (ISA 570)", proc_names)


class ISA330Tests(TestCase):
    def test_significant_risk_gets_substantive_year_end(self):
        from apps.audit.services.isa330_risk_responses import (
            AssessedRisk, map_responses,
        )
        rows = map_responses([
            AssessedRisk(
                name="management_override",
                assertion="occurrence",
                inherent_risk="high",
                control_risk="medium",
                is_significant_risk=True,
                is_fraud_risk=True,
            ),
        ])
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertIn("substantive", r.nature)
        self.assertIn("year-end", r.timing)
        self.assertIn("ISA 330 §21", r.isa330_paras)

    def test_low_risk_allows_controls_reliance(self):
        from apps.audit.services.isa330_risk_responses import (
            AssessedRisk, map_responses,
        )
        rows = map_responses([
            AssessedRisk(
                name="payroll_accuracy",
                assertion="accuracy",
                inherent_risk="low",
                control_risk="low",
            ),
        ])
        self.assertEqual(rows[0].extent, "reduced")
        self.assertIn("controls", rows[0].nature)


# ─── SoD on JournalEntry posting ────────────────────────────────────────────
class JournalEntrySoDTests(TestCase):
    def setUp(self):
        from apps.billing.tests._factories import make_org
        from apps.ledger.services import ensure_default_accounts
        User = get_user_model()
        self.org = make_org()
        ensure_default_accounts(self.org)
        self.maker = User.objects.create_user(
            email="maker@example.com", password="x",
            full_name="Maker", role="admin", organization=self.org,
        )
        self.approver = User.objects.create_user(
            email="approver@example.com", password="x",
            full_name="Approver", role="admin", organization=self.org,
        )

    def _make_draft(self):
        from apps.ledger.sod_posting import create_draft_entry
        from apps.ledger.models import JournalEntry
        return create_draft_entry(
            organization=self.org,
            entry_date=date.today(),
            description="Test manual entry",
            lines=[
                {"account_code": "1200", "debit": "100", "description": "AR"},
                {"account_code": "4100", "credit": "100", "description": "Rev"},
            ],
            source=JournalEntry.Source.MANUAL,
            created_by=self.maker,
        )

    def test_maker_cannot_post_their_own_manual_entry(self):
        from apps.ledger.sod_posting import post_with_sod
        from core.audit.sod import SoDViolation
        entry = self._make_draft()
        with self.assertRaises(SoDViolation):
            post_with_sod(entry, by_user=self.maker)

    def test_different_user_can_post(self):
        from apps.ledger.sod_posting import post_with_sod
        from apps.ledger.models import JournalEntry
        entry = self._make_draft()
        posted = post_with_sod(entry, by_user=self.approver)
        self.assertEqual(posted.status, JournalEntry.Status.POSTED)
        self.assertEqual(posted.posted_by_id, self.approver.id)

    def test_cannot_post_already_posted(self):
        from apps.ledger.sod_posting import post_with_sod
        entry = self._make_draft()
        post_with_sod(entry, by_user=self.approver)
        with self.assertRaises(ValueError):
            post_with_sod(entry, by_user=self.approver)


# ─── WORM ────────────────────────────────────────────────────────────────────
class WORMTests(TestCase):
    def test_attestation_round_trip(self):
        from apps.documents.services.worm import (
            WORMAttestation, _seal, verify_attestation,
        )
        raw = WORMAttestation(
            object_kind="document",
            object_id="doc-1",
            content_sha256="a" * 64,
            sealed_at="2026-05-13T12:00:00",
            sealed_by="system",
        )
        sealed = _seal(raw)
        self.assertEqual(len(sealed.manifest_sha256), 64)
        self.assertTrue(verify_attestation(sealed))

    def test_tampered_attestation_fails_verify(self):
        from apps.documents.services.worm import (
            WORMAttestation, _seal, verify_attestation,
        )
        raw = WORMAttestation(
            object_kind="document", object_id="d", content_sha256="b"*64,
            sealed_at="2026-05-13T00:00:00", sealed_by="system",
        )
        sealed = _seal(raw)
        tampered = WORMAttestation(
            object_kind="document", object_id="d", content_sha256="c"*64,
            sealed_at="2026-05-13T00:00:00", sealed_by="system",
            manifest_sha256=sealed.manifest_sha256,   # old hash, new content
        )
        self.assertFalse(verify_attestation(tampered))


# ─── Zakat ───────────────────────────────────────────────────────────────────
class ZakatTests(TestCase):
    def test_positive_base_2_5pct(self):
        from apps.audit.services.zakat import ZakatInputs, compute_zakat
        a = compute_zakat(ZakatInputs(
            paid_up_capital=Decimal("10000000"),
            retained_earnings=Decimal("2000000"),
            long_term_liabilities=Decimal("3000000"),
            fixed_assets_net=Decimal("5000000"),
            adjusted_profit=Decimal("1500000"),
        ))
        # additions = 10M + 2M + 3M + 1.5M = 16.5M
        # deductions = 5M
        # base = 11.5M
        self.assertEqual(a.zakat_base, Decimal("11500000"))
        self.assertEqual(a.zakat_due, (Decimal("11500000") * Decimal("0.025")).quantize(Decimal("0.01")))

    def test_profit_floor_kicks_in_when_base_is_lower(self):
        from apps.audit.services.zakat import ZakatInputs, compute_zakat
        a = compute_zakat(ZakatInputs(
            paid_up_capital=Decimal("1000000"),
            fixed_assets_net=Decimal("3000000"),   # huge deduction
            adjusted_profit=Decimal("500000"),
        ))
        # raw_base = 1M + 500k − 3M = −1.5M, below profit, floor=500k
        self.assertTrue(a.profit_floor_applied)
        self.assertEqual(a.zakat_base, Decimal("500000"))


# ─── SOCPA Chart ────────────────────────────────────────────────────────────
class SOCPAChartTests(TestCase):
    def test_overlay_adds_zakat_eosi_wht_accounts(self):
        from apps.billing.tests._factories import make_org
        from apps.ledger.socpa_coa import ensure_socpa_chart
        from apps.ledger.models import Account
        org = make_org()
        result = ensure_socpa_chart(org)
        self.assertGreater(result["socpa_added"], 0)
        codes = set(Account.objects.filter(organization=org).values_list("code", flat=True))
        # SOCPA-mandatory line items present.
        self.assertIn("2400", codes)   # EOSI
        self.assertIn("2500", codes)   # WHT
        self.assertIn("2600", codes)   # Zakat payable
        self.assertIn("5500", codes)   # Zakat expense

    def test_idempotent_no_duplicates_on_second_run(self):
        from apps.billing.tests._factories import make_org
        from apps.ledger.socpa_coa import ensure_socpa_chart
        org = make_org()
        first = ensure_socpa_chart(org)
        second = ensure_socpa_chart(org)
        self.assertEqual(second["socpa_added"], 0)
        self.assertEqual(first["total"], second["total"])


# ─── Management command ────────────────────────────────────────────────────
class AuditVerifyAllCommandTests(TestCase):
    def test_runs_clean_on_empty_db(self):
        from django.core.management import call_command
        from io import StringIO
        out = StringIO()
        # No documents, no journal entries, no orgs → all checks pass.
        try:
            call_command(
                "audit_verify_all", "--skip", "chains", stdout=out,
            )
        except SystemExit as e:
            self.fail(f"audit_verify_all exited {e.code} on empty db; output: {out.getvalue()}")
