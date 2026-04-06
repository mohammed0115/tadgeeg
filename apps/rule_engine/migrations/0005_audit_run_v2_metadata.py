"""
Migration: add AuditRunV2Metadata table (re_audit_run_v2_meta).

This model stores V2-pipeline-specific outputs (AI insights, decision,
context enrichment) as a OneToOne extension of AuditRun so the core
run table remains unchanged and V1 runs are unaffected.
"""
import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rule_engine", "0004_alter_ruleassignment_document_type"),
    ]

    operations = [
        migrations.CreateModel(
            name="AuditRunV2Metadata",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "audit_run",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="v2_metadata",
                        to="rule_engine.auditrun",
                    ),
                ),
                (
                    "ai_insights",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text=(
                            "Structured output from AIEngineStage: anomaly_signals, "
                            "narrative, confidence, recommended_action, ai_provider."
                        ),
                    ),
                ),
                (
                    "decision",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text=(
                            "Final decision: action, confidence, auto_action, "
                            "escalate_to, reasoning, blocking_rules."
                        ),
                    ),
                ),
                (
                    "context_summary",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text=(
                            "Serialised PipelineContext.to_meta_dict(): pipeline_version, "
                            "fingerprint, stage_timings, vendor/history/erp context."
                        ),
                    ),
                ),
                (
                    "stage_timings",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text="Elapsed milliseconds per stage: {stage_name: ms}.",
                    ),
                ),
                (
                    "stage_errors",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text=(
                            "Errors swallowed by non-critical stages: "
                            "{stage_name: error_str}."
                        ),
                    ),
                ),
                (
                    "stages_skipped",
                    models.JSONField(
                        blank=True,
                        default=list,
                        help_text="Stage names skipped during this run.",
                    ),
                ),
                (
                    "pipeline_version",
                    models.CharField(
                        default="3.0",
                        help_text="AuditPipelineV2 version at time of execution.",
                        max_length=16,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Audit Run V2 Metadata",
                "verbose_name_plural": "Audit Run V2 Metadata",
                "db_table": "re_audit_run_v2_meta",
            },
        ),
    ]
