"""
Migration: 0003_document_state_history
Adds the DocumentStateHistory model — immutable audit trail of Document state changes.
"""

import uuid
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0002_add_document_analysis_result"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="DocumentStateHistory",
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
                    "from_state",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("pending",      "Pending"),
                            ("processing",   "Processing"),
                            ("completed",    "Completed"),
                            ("failed",       "Failed"),
                            ("needs_review", "Needs Manual Review"),
                        ],
                        max_length=20,
                    ),
                ),
                (
                    "to_state",
                    models.CharField(
                        choices=[
                            ("pending",      "Pending"),
                            ("processing",   "Processing"),
                            ("completed",    "Completed"),
                            ("failed",       "Failed"),
                            ("needs_review", "Needs Manual Review"),
                        ],
                        max_length=20,
                    ),
                ),
                ("reason",   models.CharField(blank=True, max_length=500)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    "document",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="state_history",
                        to="documents.document",
                    ),
                ),
                (
                    "changed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="document_state_changes",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "document_state_history",
                "ordering": ["created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="documentstatehistory",
            index=models.Index(
                fields=["document", "created_at"],
                name="docstate_doc_time_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="documentstatehistory",
            index=models.Index(
                fields=["to_state", "created_at"],
                name="docstate_tostate_time_idx",
            ),
        ),
    ]
