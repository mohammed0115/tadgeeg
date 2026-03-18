"""Compatibility analytics service used by tests and legacy callers."""

from __future__ import annotations

from datetime import timedelta

from django.db import models
from django.db.models import Avg, Count
from django.utils import timezone

from apps.audit.models import AuditFinding, AuditSession
from apps.invoices.models import Invoice, InvoiceBatch


class AuditAnalyticsService:
    """Provide small, machine-readable org analytics without depending on view code."""

    def __init__(self, organization):
        self.organization = organization

    def organization_summary(self, *, days: int = 30) -> dict:
        window_start = timezone.now() - timedelta(days=days)

        invoices = Invoice.objects.filter(
            organization=self.organization,
            created_at__gte=window_start,
        )
        sessions = AuditSession.objects.filter(
            organization=self.organization,
            created_at__gte=window_start,
        )
        batches = InvoiceBatch.objects.filter(
            organization=self.organization,
            created_at__gte=window_start,
        )
        open_findings = AuditFinding.objects.filter(
            organization=self.organization,
            status=AuditFinding.Status.OPEN,
        )

        risk_rollup = invoices.aggregate(
            avg_score=Avg("risk_score"),
            high_risk=Count("id", filter=models.Q(risk_level__in=["high", "critical"])),
        )

        return {
            "documents": {
                "total_uploaded": invoices.count(),
                "recent_batches": batches.count(),
                "recent_sessions": sessions.count(),
            },
            "findings": {
                "open_total": open_findings.count(),
                "critical_open": open_findings.filter(severity=AuditFinding.Severity.CRITICAL).count(),
            },
            "risk": {
                "average_score": float(risk_rollup["avg_score"] or 0.0),
                "high_risk_total": risk_rollup["high_risk"] or 0,
            },
        }
