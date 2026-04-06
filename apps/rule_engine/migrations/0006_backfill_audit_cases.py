"""
Migration 0006: Backfill legacy AuditCase records into AuditRun + AuditResult.

Prompt 2.5 — Data Migration (historical records).

What it does (forward)
----------------------
  Iterates over apps.audit.AuditCase records that have no corresponding
  AuditRun (i.e. they were created by the old AuditEngine, not by V2).
  For each case it creates:

    AuditRun   (status=COMPLETED, engine_version="legacy_backfill")
    AuditResult (one row per case, status derived from AuditCase.status)

  No AuditEvidence rows are created — the original data is not structured
  enough to reconstruct evidence; the audit_report JSON is stored in raw_output.

What it does (backward)
-----------------------
  Deletes all AuditRun records whose engine_version == "legacy_backfill".
  This cascades to AuditResult and AuditRunV2Metadata automatically.

Safety notes
------------
  - Runs in batches of BATCH_SIZE to avoid long-running transactions.
  - Skips AuditCase rows whose related Document / Organization cannot be resolved.
  - Safe to run multiple times: uses get_or_create with a stable lookup key.
  - Back up the database before running in production.
"""

from django.db import migrations


BATCH_SIZE = 500
ENGINE_VERSION = "legacy_backfill"


def _severity_to_status(severity: str) -> str:
    """Map AuditCase severity to AuditResult status string."""
    if severity in ("critical", "high"):
        return "fail"
    if severity == "medium":
        return "warning"
    return "pass"


def forward(apps, schema_editor):
    AuditCase   = apps.get_model("audit", "AuditCase")
    AuditRun    = apps.get_model("rule_engine", "AuditRun")
    AuditResult = apps.get_model("rule_engine", "AuditResult")

    from django.utils import timezone
    import uuid

    total = 0
    offset = 0

    while True:
        batch = list(
            AuditCase.objects.select_related("organization")
            .filter(is_deleted=False)
            .order_by("created_at")[offset : offset + BATCH_SIZE]
        )
        if not batch:
            break

        for case in batch:
            # Resolve document_id — try invoice FK first, then generic document
            doc_id = (
                getattr(case, "invoice_id", None)
                or getattr(case, "document_id", None)
            )
            if not doc_id:
                continue

            org_id = getattr(case, "organization_id", None)
            if not org_id:
                continue

            # AuditRun — one per AuditCase (engine_version flags as backfill)
            run, created = AuditRun.objects.get_or_create(
                document_id=doc_id,
                document_type="sales_invoice",
                organization_id=org_id,
                engine_version=ENGINE_VERSION,
                triggered_by="manual",
                defaults={
                    "status": "completed",
                    "total_rules": 1,
                    "failed_rules": 1 if case.severity in ("critical", "high") else 0,
                    "passed_rules":  0 if case.severity in ("critical", "high") else 1,
                    "warning_rules": 1 if case.severity == "medium" else 0,
                    "risk_score":    75 if case.severity == "critical" else (
                                     50 if case.severity == "high" else (
                                     25 if case.severity == "medium" else 5)),
                    "risk_level": case.severity if case.severity in (
                        "critical", "high", "medium", "low") else "low",
                    "requires_manual_review": case.severity in ("critical", "high"),
                    "blocks_approval": case.severity == "critical",
                    "started_at":   case.created_at,
                    "completed_at": case.updated_at or case.created_at,
                    "error_log":    [{"type": "legacy_backfill", "case_id": str(case.id)}],
                },
            )

            if not created:
                # Already backfilled — skip AuditResult creation
                continue

            # Resolve a RuleAssignment — use any active system-level assignment
            assignment = (
                apps.get_model("rule_engine", "RuleAssignment")
                .objects.filter(organization=None, status="active")
                .order_by("?")  # random pick; just needs a valid FK
                .first()
            )
            if not assignment:
                continue

            AuditResult.objects.create(
                audit_run=run,
                rule_assignment=assignment,
                rule_code="LEGACY-CASE",
                rule_version=1,
                applied_severity=case.severity or "medium",
                blocks_approval=case.severity == "critical",
                status=_severity_to_status(case.severity or "medium"),
                explanation=getattr(case, "title", "") or "Backfilled from legacy AuditCase",
                explanation_ar=getattr(case, "title_ar", "") or "مُرحَّل من حالة التدقيق القديمة",
                risk_contribution=0.5 if case.severity in ("critical", "high") else 0.2,
                raw_output={
                    "source": "legacy_backfill",
                    "case_id": str(case.id),
                    "case_type": getattr(case, "case_type", ""),
                    "original_severity": case.severity,
                    "original_status": getattr(case, "status", ""),
                },
            )
            total += 1

        offset += BATCH_SIZE

    print(f"[0006_backfill] Backfilled {total} AuditCase records → AuditRun + AuditResult")


def backward(apps, schema_editor):
    AuditRun = apps.get_model("rule_engine", "AuditRun")
    deleted, _ = AuditRun.objects.filter(engine_version=ENGINE_VERSION).delete()
    print(f"[0006_backfill] Rolled back {deleted} backfilled AuditRun records")


class Migration(migrations.Migration):

    dependencies = [
        ("rule_engine", "0005_audit_run_v2_metadata"),
        ("audit", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(forward, backward, atomic=False),
    ]
