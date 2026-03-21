import uuid

from django.db import models

from apps.rule_engine.models.audit_execution import AuditRun


class RiskScoreSummary(models.Model):
    """
    Denormalised risk snapshot for a single document.

    Updated at the end of every :model:`rule_engine.AuditRun` so that
    dashboards and list views can query risk data without touching the full
    result set.  Only one summary row exists per document (document_id is
    unique); it is created on first run and upserted on subsequent runs.
    """

    class RiskLevel(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        CRITICAL = "critical", "Critical"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    organization = models.ForeignKey(
        "authentication.Organization",
        on_delete=models.CASCADE,
        related_name="risk_summaries",
        db_index=True,
    )

    document_type = models.CharField(max_length=32)
    document_id = models.UUIDField(
        unique=True,
        db_index=True,
        help_text="UUID of the audited document in its own table.",
    )

    latest_audit_run = models.OneToOneField(
        AuditRun,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="risk_summary",
    )

    # Score and classification
    risk_score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text="Composite risk score (0 – 100).",
    )
    risk_level = models.CharField(
        max_length=16,
        choices=RiskLevel.choices,
        default=RiskLevel.LOW,
    )

    # Failure counters
    fraud_indicators = models.PositiveSmallIntegerField(
        default=0,
        help_text="Number of rules tagged as fraud indicators that failed.",
    )
    compliance_failures = models.PositiveSmallIntegerField(
        default=0,
        help_text="Number of compliance rules that failed.",
    )
    blocking_failures = models.PositiveSmallIntegerField(
        default=0,
        help_text="Number of failures on rules marked blocks_approval.",
    )

    # Workflow flags
    requires_manual_review = models.BooleanField(default=False)
    blocks_approval = models.BooleanField(default=False)

    # Detailed breakdown for reporting
    score_breakdown = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Dict keyed by rule category with per-category score contributions, "
            "e.g. {'data_integrity': 10.5, 'compliance': 5.0}."
        ),
    )
    top_failed_rules = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "Ordered list of dicts describing the highest-impact failures, "
            "each with keys: rule_code, severity, risk_contribution, explanation."
        ),
    )

    # Timestamp updated by auto_now so it always reflects the last calculation.
    last_calculated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "re_risk_score_summary"
        indexes = [
            models.Index(
                fields=["organization", "risk_level"],
                name="re_risk_org_level_idx",
            ),
            models.Index(
                fields=["blocks_approval"],
                name="re_risk_blocks_approval_idx",
            ),
        ]
        verbose_name = "Risk Score Summary"
        verbose_name_plural = "Risk Score Summaries"

    def __str__(self) -> str:
        return (
            f"Risk({self.document_type}/{self.document_id}) "
            f"score={self.risk_score} [{self.risk_level}]"
        )
