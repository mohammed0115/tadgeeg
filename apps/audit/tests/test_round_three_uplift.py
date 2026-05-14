"""Round-three uplift tests — Enterprise Audit Platform readiness.

Covers everything added in the "fix all" pass following the BIG4-style
audit-platform review:

  • apps/erp connector registry + base contract
  • apps/erp sync ingestion (creates Invoice rows from RemoteRecord)
  • ISA 200 risk decomposition (assess + plan_detection_risk + residual)
  • AuditEngagement model (ISA 300)
  • ActivityLog append-only + hash chain
  • EvidenceAccess chain-of-custody
  • Trusted Timestamping (RFC 3161) — mock + verify
  • FinancialDocument bridge over Invoice / Transaction / JournalEntry
  • AuditCase no longer soft-deletable
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings


# ─── ERP ───────────────────────────────────────────────────────────────────
class ERPConnectorRegistryTests(TestCase):
    def test_known_provider_resolves(self):
        from apps.erp.connectors.registry import get_connector
        cls = get_connector("sap")
        self.assertEqual(cls.provider, "sap")

    def test_unknown_provider_raises(self):
        from apps.erp.connectors.registry import (
            get_connector, UnknownProviderError,
        )
        with self.assertRaises(UnknownProviderError):
            get_connector("brand-x")

    def test_known_providers_list(self):
        from apps.erp.connectors.registry import known_providers
        names = known_providers()
        for expected in ("sap", "oracle", "odoo", "dynamics",
                         "quickbooks", "netsuite"):
            self.assertIn(expected, names)


class ERPConnectorStubFetchTests(TestCase):
    def test_sap_mock_yields_records(self):
        from apps.erp.connectors.sap import SAPConnector
        from apps.erp.connectors.base import ConnectionConfig
        c = SAPConnector(ConnectionConfig(
            organization_id="org-1", provider="sap",
            environment="mock", base_url="", credentials={},
        ))
        c.authenticate()
        records = list(c.fetch_records())
        self.assertTrue(records)
        self.assertEqual(records[0].kind, "invoice")
        self.assertEqual(records[0].source_system, "sap")

    def test_oracle_push_decision_in_mock(self):
        from apps.erp.connectors.oracle import OracleConnector
        from apps.erp.connectors.base import ConnectionConfig, PushDecision
        c = OracleConnector(ConnectionConfig(
            organization_id="org-1", provider="oracle",
            environment="mock", base_url="", credentials={},
        ))
        c.authenticate()
        out = c.push_decision(PushDecision(
            invoice_external_id="ORA-INV-2000",
            decision="approved", risk_score=20, audit_findings=[],
            decided_by="user-1", decided_at=datetime.now(timezone.utc),
        ))
        self.assertTrue(out.success)


class ERPIngestionTests(TestCase):
    def setUp(self):
        from apps.billing.tests._factories import make_org
        from apps.erp.models import ERPConnection
        self.org = make_org()
        self.conn = ERPConnection.objects.create(
            organization=self.org,
            provider=ERPConnection.Provider.SAP,
            environment=ERPConnection.Environment.MOCK,
            credentials={},
        )

    def test_ingestion_creates_invoices(self):
        from apps.erp.sync.ingestion import run_ingestion
        from apps.invoices.models import Invoice
        from apps.erp.models import SyncRun
        run = run_ingestion(self.conn)
        self.assertEqual(run.status, SyncRun.Status.COMPLETED)
        self.assertGreater(run.records_imported, 0)
        # Idempotent — re-running yields zero new rows.
        before = Invoice.objects.filter(organization=self.org).count()
        run2 = run_ingestion(self.conn)
        after  = Invoice.objects.filter(organization=self.org).count()
        self.assertEqual(after, before)
        self.assertEqual(run2.status, SyncRun.Status.COMPLETED)

    def test_paused_connection_refuses_sync(self):
        from apps.erp.sync.ingestion import run_ingestion
        from apps.erp.models import ERPConnection
        self.conn.status = ERPConnection.Status.PAUSED
        self.conn.save()
        with self.assertRaises(RuntimeError):
            run_ingestion(self.conn)


class EncryptedCredentialsTests(TestCase):
    def test_credentials_roundtrip(self):
        from apps.billing.tests._factories import make_org
        from apps.erp.models import ERPConnection
        org = make_org()
        conn = ERPConnection.objects.create(
            organization=org,
            provider=ERPConnection.Provider.ORACLE,
            environment=ERPConnection.Environment.SANDBOX,
            credentials={"client_id": "ABC123", "client_secret": "ssh-secret"},
        )
        # Round-trip via the DB.
        conn.refresh_from_db()
        self.assertEqual(conn.credentials["client_id"], "ABC123")
        self.assertEqual(conn.credentials["client_secret"], "ssh-secret")


# ─── ISA 200 — Risk decomposition ──────────────────────────────────────────
class RiskDecompositionTests(TestCase):
    def test_assess_zero_inputs_is_zero_risk(self):
        from apps.audit.services.risk_decomposition import (
            RiskAssessmentInputs, assess,
        )
        out = assess(RiskAssessmentInputs())
        # Zero IR drivers and zero control-strength drivers => CR = 100,
        # DR = 100. Audit risk = 0 * 100% * 100% = 0.
        self.assertEqual(out.inherent_risk, 0)
        self.assertEqual(out.control_risk, 100)
        self.assertEqual(out.detection_risk, 100)

    def test_high_inherent_and_weak_controls_high_audit_risk(self):
        from apps.audit.services.risk_decomposition import (
            RiskAssessmentInputs, assess,
        )
        out = assess(RiskAssessmentInputs(
            industry_volatility=25, complexity_of_transactions=25,
            susceptibility_to_fraud=25, related_party_density=25,
            # weak controls (all zeros) → CR = 100
            # moderate audit work
            sample_extent=10, procedure_persuasiveness=10,
            timing_of_procedures=10, staff_competence=10,
        ))
        self.assertEqual(out.inherent_risk, 100)
        self.assertEqual(out.control_risk, 100)
        # DR = 100 - (10+10+10+10) = 60
        self.assertEqual(out.detection_risk, 60)
        # AR = 1.0 * 1.0 * 0.6 = 0.6 → far above 5% target
        self.assertGreater(out.audit_risk, Decimal("0.5"))
        self.assertFalse(out.on_target)

    def test_plan_detection_risk_solves_for_target(self):
        from apps.audit.services.risk_decomposition import plan_detection_risk
        # Target 5%, IR 50%, CR 50% → DR should be 20% so 0.5*0.5*0.2=0.05.
        dr = plan_detection_risk(
            inherent_risk=50, control_risk=50,
            target_audit_risk=Decimal("0.05"),
        )
        self.assertEqual(dr, 20)

    def test_residual_risk_formula(self):
        from apps.audit.services.risk_decomposition import residual_risk
        # IR=80, controls 75% effective → residual = 80 * 0.25 = 20.
        self.assertEqual(residual_risk(80, 75), 20.00)


# ─── AuditEngagement (ISA 300) ─────────────────────────────────────────────
class AuditEngagementTests(TestCase):
    def test_engagement_create_and_string(self):
        from apps.billing.tests._factories import make_org
        from apps.audit.models import AuditEngagement
        from datetime import date
        org = make_org()
        eng = AuditEngagement.objects.create(
            organization=org,
            engagement_code="AUD-2026-001",
            title="FY2026 statutory audit",
            engagement_type=AuditEngagement.EngagementType.FINANCIAL_STATEMENT,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 12, 31),
        )
        self.assertEqual(eng.stage, AuditEngagement.Stage.ACCEPTANCE)
        self.assertIn("AUD-2026-001", str(eng))

    def test_engagement_code_unique_per_org(self):
        from apps.billing.tests._factories import make_org
        from apps.audit.models import AuditEngagement
        from django.db import IntegrityError, transaction
        from datetime import date
        org = make_org()
        AuditEngagement.objects.create(
            organization=org, engagement_code="DUP-001",
            title="A", period_start=date(2026, 1, 1),
            period_end=date(2026, 12, 31),
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AuditEngagement.objects.create(
                    organization=org, engagement_code="DUP-001",
                    title="B", period_start=date(2026, 1, 1),
                    period_end=date(2026, 12, 31),
                )


# ─── ActivityLog hash chain ────────────────────────────────────────────────
class ActivityLogChainTests(TestCase):
    def setUp(self):
        from apps.billing.tests._factories import make_org
        self.org = make_org()

    def test_chain_hash_present_on_save(self):
        from apps.activity_logs.models import ActivityLog
        log = ActivityLog.objects.create(
            organization=self.org,
            action=ActivityLog.Action.AUDIT_STARTED,
            entity_type="invoice",
            entity_id="abc",
        )
        self.assertEqual(len(log.chain_hash), 64)
        self.assertEqual(log.previous_hash, "")

    def test_chain_links_consecutive_rows(self):
        from apps.activity_logs.models import ActivityLog
        a = ActivityLog.objects.create(
            organization=self.org,
            action=ActivityLog.Action.AUDIT_STARTED,
        )
        b = ActivityLog.objects.create(
            organization=self.org,
            action=ActivityLog.Action.AUDIT_COMPLETED,
        )
        self.assertEqual(b.previous_hash, a.chain_hash)
        self.assertNotEqual(a.chain_hash, b.chain_hash)

    def test_append_only_rejects_save_on_existing(self):
        from apps.activity_logs.models import ActivityLog
        log = ActivityLog.objects.create(
            organization=self.org,
            action=ActivityLog.Action.AUDIT_STARTED,
        )
        log.description = "tampered"
        with self.assertRaises(ValueError):
            log.save()


# ─── EvidenceAccess chain-of-custody ───────────────────────────────────────
class EvidenceAccessTests(TestCase):
    def setUp(self):
        from apps.billing.tests._factories import make_org
        self.org = make_org()

    def test_chain_hash_per_row(self):
        from apps.activity_logs.models import EvidenceAccess
        ea = EvidenceAccess.objects.create(
            organization=self.org,
            evidence_kind="document",
            evidence_id="doc-1",
            evidence_sha="a" * 64,
            action=EvidenceAccess.Action.VIEWED,
            ip_address="10.0.0.1",
        )
        self.assertEqual(len(ea.chain_hash), 64)

    def test_chain_links_consecutive(self):
        from apps.activity_logs.models import EvidenceAccess
        a = EvidenceAccess.objects.create(
            organization=self.org,
            evidence_kind="document", evidence_id="d",
            action=EvidenceAccess.Action.VIEWED,
        )
        b = EvidenceAccess.objects.create(
            organization=self.org,
            evidence_kind="document", evidence_id="d",
            action=EvidenceAccess.Action.DOWNLOADED,
        )
        self.assertEqual(b.previous_hash, a.chain_hash)


# ─── Trusted Timestamping (RFC 3161) ───────────────────────────────────────
@override_settings(MOCK_TSA_RESPONSE=True)
class TimestampingTests(TestCase):
    def test_mock_token_is_deterministic_per_hash(self):
        from core.security.timestamping import issue_timestamp
        sha = "0" * 64
        a = issue_timestamp(sha, authority="freetsa")
        b = issue_timestamp(sha, authority="freetsa")
        self.assertEqual(a.token_b64, b.token_b64)
        self.assertEqual(a.content_sha256, sha)
        self.assertTrue(a.authority.endswith("-mock"))

    def test_verify_token_structural(self):
        from core.security.timestamping import issue_timestamp, verify_timestamp
        ts = issue_timestamp("a" * 64)
        self.assertTrue(verify_timestamp(ts))

    def test_unknown_authority_raises(self):
        from core.security.timestamping import issue_timestamp, TSAError
        with self.assertRaises(TSAError):
            issue_timestamp("a" * 64, authority="brand-x")


# ─── FinancialDocument bridge ──────────────────────────────────────────────
class FinancialDocumentBridgeTests(TestCase):
    def test_adapts_invoice(self):
        from apps.billing.tests._factories import make_org
        from apps.invoices.models import Invoice
        from core.audit.financial_document import as_financial_document
        org = make_org()
        inv = Invoice.objects.create(
            organization=org,
            original_filename="x.pdf",
            invoice_number="INV-1",
            vendor_name="Acme",
            currency="SAR",
            total_amount=Decimal("1000.00"),
            vat_amount=Decimal("150.00"),
        )
        fd = as_financial_document(inv)
        self.assertEqual(fd.kind, "invoice")
        self.assertEqual(fd.amount, Decimal("1000.00"))
        self.assertEqual(fd.vendor_name, "Acme")

    def test_unknown_type_raises(self):
        from core.audit.financial_document import as_financial_document
        class Random:
            pk = 1
        with self.assertRaises(TypeError):
            as_financial_document(Random())


# ─── AuditCase no soft-delete ──────────────────────────────────────────────
class AuditCaseHardenedTests(TestCase):
    def test_audit_case_no_longer_inherits_soft_delete(self):
        from apps.audit.models import AuditCase
        from core.mixins import SoftDeleteModel
        # AuditCase explicitly DOES NOT inherit SoftDeleteModel anymore
        # (ISA 230 retention). Legacy is_deleted / deleted_at fields kept
        # for migration compatibility but excluded from editing.
        self.assertFalse(issubclass(AuditCase, SoftDeleteModel))
        # Verify is_deleted is uneditable (editable=False).
        f = AuditCase._meta.get_field("is_deleted")
        self.assertFalse(f.editable)


# ─── Deprecated orchestrator fails loudly ──────────────────────────────────
class DeprecatedOrchestratorTests(TestCase):
    def test_instantiating_raises(self):
        from apps.audit_engine.services.orchestrator import AuditOrchestrator
        with self.assertRaises(RuntimeError):
            AuditOrchestrator()


# ─── Reconciliation diff types ─────────────────────────────────────────────
class ReconciliationTests(TestCase):
    def setUp(self):
        from apps.billing.tests._factories import make_org
        from apps.erp.models import ERPConnection
        from apps.invoices.models import Invoice
        self.org = make_org()
        self.conn = ERPConnection.objects.create(
            organization=self.org,
            provider=ERPConnection.Provider.SAP,
            environment=ERPConnection.Environment.MOCK,
        )
        # Create a Tadgeeg invoice that the ERP stub does NOT have →
        # should produce a "missing_in_erp" diff.
        from datetime import date
        Invoice.objects.create(
            organization=self.org,
            original_filename="legacy.pdf",
            external_source="sap",
            external_id="ORPHAN-SAP-INV",
            vendor_name="Ghost",
            total_amount=Decimal("999"),
            currency="SAR",
            invoice_date=date(2026, 1, 10),
        )

    def test_reconcile_detects_missing_in_erp(self):
        from apps.erp.sync.reconciliation import reconcile_window
        from apps.erp.models import ReconciliationDiff
        from datetime import datetime, timezone
        result = reconcile_window(
            self.conn,
            since=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        self.assertGreater(result["counts"]["missing_in_erp"], 0)
        self.assertGreater(
            ReconciliationDiff.objects.filter(
                organization=self.org, diff_type="missing_in_erp",
            ).count(),
            0,
        )
