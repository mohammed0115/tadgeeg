from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("audit", "0006_rename_audit_findi_organiz_716be4_idx_audit_findi_organiz_dafce2_idx_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("authentication", "0004_auditlog_retain_until"),
    ]

    operations = [
        migrations.CreateModel(
            name="CustomRuleDefinition",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=200)),
                ("description", models.TextField(blank=True)),
                ("standard", models.CharField(
                    choices=[
                        ("zatca", "ZATCA E-Invoicing"),
                        ("kpmg", "KPMG"),
                        ("deloitte", "Deloitte"),
                        ("pwc", "PwC"),
                        ("ey", "EY"),
                        ("custom", "Custom"),
                    ],
                    default="custom",
                    max_length=20,
                )),
                ("severity", models.CharField(
                    choices=[
                        ("critical", "Critical"),
                        ("high", "High"),
                        ("medium", "Medium"),
                        ("low", "Low"),
                    ],
                    default="medium",
                    max_length=10,
                )),
                ("condition_type", models.CharField(
                    choices=[
                        ("missing_field", "Field must not be empty"),
                        ("amount_threshold", "Amount above/below threshold"),
                        ("date_check", "Invoice date validation"),
                        ("duplicate_check", "Duplicate invoice number"),
                        ("pattern_match", "Field matches regex pattern"),
                    ],
                    max_length=30,
                )),
                ("condition_params", models.JSONField(default=dict)),
                ("remediation_suggestion", models.TextField(blank=True)),
                ("is_active", models.BooleanField(default=True)),
                ("version", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="custom_rules",
                        to="authentication.organization",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_rules",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "custom_rule_definitions",
                "ordering": ["name"],
                "unique_together": {("organization", "name")},
            },
        ),
    ]
