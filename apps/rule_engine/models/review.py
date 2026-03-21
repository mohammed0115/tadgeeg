import uuid

from django.db import models

from apps.rule_engine.models.audit_execution import AuditResult


class ManualReviewDecision(models.Model):
    """
    Captures a human reviewer's decision on a flagged
    :model:`rule_engine.AuditResult`.

    Each AuditResult can have at most one ManualReviewDecision (OneToOne).
    If a reviewer wants to re-evaluate, the existing decision should be
    updated in place rather than creating a new one.
    """

    class Decision(models.TextChoices):
        CONFIRMED = "confirmed", "Confirmed"
        DISMISSED = "dismissed", "Dismissed"
        ESCALATED = "escalated", "Escalated"
        DEFERRED = "deferred", "Deferred"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    audit_result = models.OneToOneField(
        AuditResult,
        on_delete=models.CASCADE,
        related_name="manual_review",
    )
    reviewer = models.ForeignKey(
        "authentication.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="review_decisions",
    )

    decision = models.CharField(max_length=16, choices=Decision.choices)
    notes = models.TextField(
        blank=True,
        help_text="Free-text notes justifying the reviewer's decision.",
    )

    reviewed_at = models.DateTimeField(auto_now_add=True)

    # False-positive tracking
    is_false_positive = models.BooleanField(
        default=False,
        help_text=(
            "True when the reviewer determines the rule fired incorrectly "
            "for this document.  Used for rule quality reporting."
        ),
    )
    false_positive_reason = models.TextField(
        blank=True,
        help_text="Reason the reviewer considers this a false positive.",
    )

    class Meta:
        db_table = "re_manual_review_decision"
        verbose_name = "Manual Review Decision"
        verbose_name_plural = "Manual Review Decisions"

    def __str__(self) -> str:
        reviewer_label = (
            self.reviewer.get_full_name() if self.reviewer else "unknown"
        )
        return (
            f"Review({self.audit_result.rule_code}) → "
            f"{self.decision} by {reviewer_label}"
        )
