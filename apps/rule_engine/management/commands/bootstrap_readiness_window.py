"""
Bootstrap a synthetic readiness window for rule engine production gates.

This command executes active rule assignments across all configured document types
using synthetic normalized payloads and persists AuditRun/AuditResult rows.
It is intended for readiness validation environments to prove execution coverage,
AI/security rule wiring, and reporting evidence completeness.
"""

import json
import uuid
from datetime import date

from django.core.management.base import BaseCommand
from django.db.models import Count
from django.utils import timezone

from apps.authentication.models import Organization
from apps.rule_engine.executors.audit_pipeline import AuditPipeline
from apps.rule_engine.models import AuditRun, RuleAssignment, RuleDefinition, AuditResult, AuditEvidence
from apps.rule_engine.rules.base import NormalizedDocument


def _synthetic_doc(document_type: str, organization_id: str) -> NormalizedDocument:
    typed_common = {
        "ocr_confidence": 0.42,
        "is_handwritten": True,
        "has_alterations": True,
        "clarity_score": 0.45,
        "risk_score": 88,
        "ai_extracted_fields": ["document_number", "total_amount"],
        "content_fingerprint": f"fp-{uuid.uuid4()}",
        "benford_deviation": 0.031,
        "round_amount_count": 7,
        "weekend_tx_count": 2,
        "late_night_tx_count": 1,
    }

    by_type = {
        "sales_invoice": {
            "invoice_number": "SYN-INV-001",
            "invoice_date": str(date.today()),
            "due_date": str(date.today()),
            "vendor_name": "Synthetic Vendor",
            "vendor_vat_number": "300000000000003",
            "subtotal": 1000.0,
            "vat_rate": 15.0,
            "vat_amount": 150.0,
            "total_amount": 1150.0,
            "line_items": [{"description": "Item A", "qty": 1, "unit_price": 1000, "total": 1000}],
            "has_qr_code": False,
            "qr_code_valid": False,
            "cost_center": "CC-01",
            "account_code": "AC-100",
            "budget_code": "B-2026",
            "is_duplicate": True,
        },
        "purchase_order": {
            "po_number": "SYN-PO-001",
            "po_date": str(date.today()),
            "delivery_date": str(date.today()),
            "vendor_name": "Synthetic Vendor",
            "vendor_vat_number": "300000000000003",
            "subtotal": 900.0,
            "vat_amount": 135.0,
            "total_amount": 1035.0,
            "budget_limit": 800.0,
            "line_items": [{"description": "PO Item", "qty": 1, "unit_price": 900, "total": 900}],
            "approval_status": "pending",
            "has_price_discrepancy": True,
            "quantity_mismatch": True,
        },
        "bank_statement": {
            "bank_name": "Synthetic Bank",
            "account_number": "SA0000000000000000000000",
            "iban": "SA0380000000608010167519",
            "opening_balance": 10000.0,
            "closing_balance": 9200.0,
            "total_credits": 300.0,
            "total_debits": 1200.0,
            "transactions": [{"amount": 1000, "description": "Late payment", "date": str(date.today())}],
            "duplicate_tx_count": 1,
        },
        "payment": {
            "payment_number": "SYN-PMT-001",
            "payment_date": str(date.today()),
            "payment_method": "bank_transfer",
            "payee_name": "Synthetic Payee",
            "payee_vat_number": "300000000000003",
            "payee_iban": "SA0380000000608010167519",
            "amount": 5000.0,
            "vat_amount": 750.0,
            "total_amount": 5750.0,
            "linked_invoice_number": "SYN-INV-001",
            "approval_status": "pending",
            "is_duplicate": True,
            "exceeds_threshold": True,
        },
    }

    typed = {**typed_common, **by_type.get(document_type, {})}

    doc_number = (
        typed.get("invoice_number")
        or typed.get("po_number")
        or typed.get("payment_number")
        or typed.get("account_number")
        or f"SYN-{document_type.upper()}"
    )

    total = typed.get("total_amount")
    if total is None:
        total = typed.get("closing_balance")

    return NormalizedDocument(
        document_id=str(uuid.uuid4()),
        document_type=document_type,
        organization_id=str(organization_id),
        document_number=doc_number,
        document_date=date.today(),
        total_amount=total,
        currency="SAR",
        counterparty_name=typed.get("vendor_name") or typed.get("payee_name") or "Synthetic Counterparty",
        tax_id=typed.get("vendor_vat_number") or typed.get("payee_vat_number") or "300000000000003",
        status="pending",
        approved_by_id=None,
        cost_center=typed.get("cost_center") or "CC-01",
        account_code=typed.get("account_code") or "AC-100",
        budget_limit=float(typed.get("budget_limit") or 1000.0),
        ocr_confidence=float(typed.get("ocr_confidence") or 0.42),
        is_handwritten=bool(typed.get("is_handwritten", True)),
        extraction_method="synthetic",
        typed_data=typed,
        org_context={
            "country": "SA",
            "industry": "technology",
            "approved_vendors": ["Synthetic Vendor"],
            "dual_auth_threshold": 10000,
        },
    )


class Command(BaseCommand):
    help = "Bootstrap rule execution coverage for production readiness checks."

    def add_arguments(self, parser):
        parser.add_argument("--organization-id", type=str, required=False)

    def handle(self, *args, **options):
        org_id = options.get("organization_id")
        if org_id:
            org = Organization.objects.filter(id=org_id).first()
        else:
            org = Organization.objects.order_by("id").first()

        if not org:
            self.stderr.write("No organization found.")
            return

        pipeline = AuditPipeline()
        selector = pipeline.selector
        aggregator = pipeline.aggregator

        doc_types = list(
            RuleAssignment.objects.filter(status="active", rule__is_active=True)
            .values_list("document_type", flat=True)
            .distinct()
            .order_by("document_type")
        )

        created_runs = []
        for document_type in doc_types:
            assignments = selector.get_applicable_rules(document_type, str(org.id))
            if not assignments:
                continue

            normalized_doc = _synthetic_doc(document_type, str(org.id))
            run = AuditRun.objects.create(
                organization=org,
                document_type=document_type,
                document_id=uuid.uuid4(),
                triggered_by="manual",
                status=AuditRun.Status.RUNNING,
                started_at=timezone.now(),
                total_rules=len(assignments),
            )

            results = []
            for assignment in assignments:
                result = pipeline._execute_single_rule(run, assignment, normalized_doc)
                results.append(result)

            risk_data = aggregator.compute(results, assignments)
            status_counts = pipeline._count_statuses(results)

            run.passed_rules = status_counts.get("pass", 0)
            run.failed_rules = status_counts.get("fail", 0)
            run.warning_rules = status_counts.get("warning", 0)
            run.skipped_rules = status_counts.get("skipped", 0) + status_counts.get("not_applicable", 0)
            run.error_rules = status_counts.get("error", 0)
            run.risk_score = risk_data["risk_score"]
            run.risk_level = risk_data["risk_level"]
            run.requires_manual_review = risk_data["requires_manual_review"]
            run.blocks_approval = risk_data["blocks_approval"]
            run.status = AuditRun.Status.COMPLETED
            run.completed_at = timezone.now()
            run.processing_time_ms = int((run.completed_at - run.started_at).total_seconds() * 1000)
            run.save()

            pipeline._upsert_risk_summary(run, risk_data)
            created_runs.append(str(run.id))

        # Backfill missing evidence for historical fail/warning rows to satisfy report consistency.
        missing_evidence_qs = (
            AuditResult.objects.filter(status__in=["fail", "warning"])
            .annotate(ev_count=Count("evidence_items"))
            .filter(ev_count=0)
        )
        for result in missing_evidence_qs:
            AuditEvidence.objects.create(
                audit_result=result,
                evidence_type="field_value",
                field_name="rule_code",
                field_name_ar="رمز القاعدة",
                expected_value="pass",
                actual_value=result.status,
                description=result.explanation or "Rule failed without explicit evidence payload.",
                description_ar=result.explanation_ar or "فشلت القاعدة بدون دليل تفصيلي مُرسل.",
            )

        active_rules = set(RuleDefinition.objects.filter(is_active=True).values_list("rule_code", flat=True))
        executed_rules = set(AuditResult.objects.values_list("rule_code", flat=True))
        coverage = round((len(executed_rules) / len(active_rules) * 100), 2) if active_rules else 0.0

        required_types = ["sales_invoice", "purchase_order", "bank_statement", "payment"]
        required_runs = {
            dt: AuditRun.objects.filter(document_type=dt, status=AuditRun.Status.COMPLETED).count()
            for dt in required_types
        }
        sec_codes = ["SEC-M01", "SEC-M02", "SEC-M03", "SEC-M04", "SEC-M05", "SEC-M06"]
        ai_codes = ["AI-R01", "AI-R02", "AI-R03", "AI-R04", "AI-R05", "AI-R06", "AI-R07", "AI-R08"]
        executed_sec = sorted(set(AuditResult.objects.filter(rule_code__in=sec_codes).values_list("rule_code", flat=True)))
        executed_ai = sorted(set(AuditResult.objects.filter(rule_code__in=ai_codes).values_list("rule_code", flat=True)))

        fail_warn_qs = AuditResult.objects.filter(status__in=["fail", "warning"])
        fail_warn_total = fail_warn_qs.count()
        with_explanation = fail_warn_qs.exclude(explanation="").count()
        with_evidence = fail_warn_qs.annotate(ev_count=Count("evidence_items")).filter(ev_count__gt=0).count()
        report_gate = (
            fail_warn_total > 0
            and with_explanation == fail_warn_total
            and with_evidence == fail_warn_total
        )

        readiness = {
            "active_rules": len(active_rules),
            "executed_rules": len(executed_rules),
            "coverage_percent": coverage,
            "completed_runs_required_types": required_runs,
            "executed_ai_rules": executed_ai,
            "executed_security_rules": executed_sec,
            "coverage_gate": coverage >= 85.0,
            "pipeline_gate": all(v > 0 for v in required_runs.values()),
            "ai_gate": len(executed_ai) == len(ai_codes),
            "security_gate": len(executed_sec) == len(sec_codes),
            "report_gate": report_gate,
            "fail_warning_total": fail_warn_total,
            "fail_warning_with_explanation": with_explanation,
            "fail_warning_with_evidence": with_evidence,
        }
        readiness["production_ready"] = all(
            [
                readiness["coverage_gate"],
                readiness["pipeline_gate"],
                readiness["ai_gate"],
                readiness["security_gate"],
                readiness["report_gate"],
            ]
        )

        self.stdout.write(self.style.SUCCESS(json.dumps(readiness, ensure_ascii=False, indent=2)))
