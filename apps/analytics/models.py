import uuid

from django.db import models

from apps.authentication.models import Organization, User


class NLQueryHistory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="nl_query_history")
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="nl_query_history")
    query = models.TextField()
    interpretation = models.TextField(blank=True)
    filters = models.JSONField(default=dict)
    excludes = models.JSONField(default=dict)
    order_by = models.JSONField(default=list)
    result_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "analytics_nl_query_history"
        ordering = ["-created_at"]

    def __str__(self):
        return self.query[:80]


class BenchmarkParticipation(models.Model):
    """Whether an organisation contributes to anonymous cross-tenant benchmarks.

    A row per organisation, `opted_in` defaulting to False. The default is the
    feature: benchmarking reads other customers' data, so participation has to
    be something someone chose, not something they failed to turn off.

    Who and when are recorded because "we never agreed to that" is a question
    that gets asked, and an unanswerable version of it is a contractual
    problem rather than a support one.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.OneToOneField(
        Organization, on_delete=models.CASCADE, related_name="benchmark_participation",
    )
    opted_in = models.BooleanField(
        default=False,
        help_text="False until someone with authority turns it on. Never defaulted True.",
    )
    opted_in_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="benchmark_opt_ins",
    )
    opted_in_at = models.DateTimeField(null=True, blank=True)
    opted_out_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Kept after opting out — the history of consent is the record.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "analytics_benchmark_participation"

    def __str__(self):
        return f"{self.organization} — {'in' if self.opted_in else 'out'}"
