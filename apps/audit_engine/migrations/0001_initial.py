import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("storage_management", "0001_initial"),
        ("authentication", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AuditJob",
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
                    "audit_type",
                    models.CharField(
                        choices=[
                            ("generic_audit", "Generic Audit"),
                            ("financial_audit", "Financial Audit"),
                            ("compliance_check", "Compliance Check"),
                            ("document_validation", "Document Validation"),
                        ],
                        default="generic_audit",
                        max_length=30,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("queued", "Queued"),
                            ("running", "Running"),
                            ("completed", "Completed"),
                            ("failed", "Failed"),
                            ("canceled", "Canceled"),
                        ],
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("failed_at", models.DateTimeField(blank=True, null=True)),
                ("error_message", models.TextField(blank=True)),
                (
                    "processing_time_ms",
                    models.PositiveIntegerField(blank=True, null=True),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "audit_file",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="audit_jobs",
                        to="storage_management.auditfile",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_audit_jobs",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="audit_jobs",
                        to="authentication.organization",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="AuditResult",
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
                ("overall_score", models.FloatField(default=100.0)),
                (
                    "risk_level",
                    models.CharField(
                        choices=[
                            ("low", "Low"),
                            ("medium", "Medium"),
                            ("high", "High"),
                            ("critical", "Critical"),
                        ],
                        default="low",
                        max_length=10,
                    ),
                ),
                ("summary", models.TextField(blank=True)),
                ("extracted_text", models.TextField(blank=True)),
                ("extracted_entities", models.JSONField(default=dict)),
                ("model_used", models.CharField(blank=True, max_length=100)),
                ("tokens_used", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "audit_job",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="result",
                        to="audit_engine.auditjob",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="AuditIssue",
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
                ("issue_code", models.CharField(blank=True, max_length=50)),
                (
                    "issue_type",
                    models.CharField(
                        choices=[
                            ("missing_field", "Missing Field"),
                            ("invalid_structure", "Invalid Structure"),
                            ("suspicious_value", "Suspicious Value"),
                            ("duplicate", "Duplicate"),
                            ("empty_section", "Empty Section"),
                            ("metadata_inconsistency", "Metadata Inconsistency"),
                            ("weak_completeness", "Weak Completeness"),
                            ("unsupported_format", "Unsupported Format"),
                            ("rule_violation", "Rule Violation"),
                        ],
                        max_length=30,
                    ),
                ),
                (
                    "severity",
                    models.CharField(
                        choices=[
                            ("low", "Low"),
                            ("medium", "Medium"),
                            ("high", "High"),
                            ("critical", "Critical"),
                        ],
                        max_length=10,
                    ),
                ),
                ("title", models.CharField(max_length=255)),
                ("description", models.TextField(blank=True)),
                ("page_number", models.PositiveIntegerField(blank=True, null=True)),
                ("row_reference", models.CharField(blank=True, max_length=100)),
                ("suggested_fix", models.TextField(blank=True)),
                ("confidence_score", models.FloatField(default=1.0)),
                ("metadata", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "audit_result",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="issues",
                        to="audit_engine.auditresult",
                    ),
                ),
            ],
            options={
                "ordering": ["severity"],
            },
        ),
        migrations.CreateModel(
            name="AIAnalysisLog",
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
                ("model_name", models.CharField(blank=True, max_length=100)),
                (
                    "provider_name",
                    models.CharField(blank=True, default="openai", max_length=50),
                ),
                (
                    "prompt_version",
                    models.CharField(blank=True, default="1.0", max_length=20),
                ),
                ("input_tokens", models.PositiveIntegerField(default=0)),
                ("output_tokens", models.PositiveIntegerField(default=0)),
                ("total_tokens", models.PositiveIntegerField(default=0)),
                ("latency_ms", models.PositiveIntegerField(default=0)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("success", "Success"),
                            ("failed", "Failed"),
                            ("skipped", "Skipped"),
                        ],
                        default="success",
                        max_length=20,
                    ),
                ),
                ("response", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "audit_file",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="ai_logs",
                        to="storage_management.auditfile",
                    ),
                ),
                (
                    "audit_job",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="ai_logs",
                        to="audit_engine.auditjob",
                    ),
                ),
            ],
            options={
                "verbose_name": "AI Analysis Log",
                "verbose_name_plural": "AI Analysis Logs",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="auditjob",
            index=models.Index(
                fields=["organization", "status"],
                name="audit_engin_organiz_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="auditjob",
            index=models.Index(
                fields=["audit_file"],
                name="audit_engin_audit_f_idx",
            ),
        ),
    ]
