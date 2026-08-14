"""Selectors for the audit decision attached to an invoice response."""

from django.db.models import (
    BooleanField,
    Exists,
    IntegerField,
    OuterRef,
    Subquery,
    Value,
)
from django.db.models.functions import Coalesce

from apps.rule_engine.models import RiskScoreSummary


def with_audit_decision(queryset):
    """Annotate invoices with the approval decision used by the approval gate.

    A missing RiskScoreSummary remains explicitly blocked as ``not_audited``;
    callers must not infer approval safety from the denormalised Invoice score.
    The correlated subqueries keep list serialization at a fixed query count.
    """
    summaries = RiskScoreSummary.objects.filter(
        document_id=OuterRef("pk"),
        organization_id=OuterRef("organization_id"),
    ).order_by("-last_calculated_at")
    return queryset.annotate(
        _audit_summary_present=Exists(summaries),
        _audit_blocks_approval=Coalesce(
            Subquery(summaries.values("blocks_approval")[:1]),
            Value(True), output_field=BooleanField(),
        ),
        _audit_blocking_failures=Coalesce(
            Subquery(summaries.values("blocking_failures")[:1]),
            Value(0), output_field=IntegerField(),
        ),
        _audit_requires_manual_review=Coalesce(
            Subquery(summaries.values("requires_manual_review")[:1]),
            Value(False), output_field=BooleanField(),
        ),
    )
