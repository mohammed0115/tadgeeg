"""SAD recalculation service (TADGEEG-FIN-AUDIT-4A).

Rebuilds one engagement-level Summary of Audit Differences from the **accepted**
GL risk findings (status == accepted only). Candidate / dismissed /
needs_evidence / escalated findings are excluded — only a human-accepted
difference accumulates.

Reuses the existing materiality resolver (3A) for engagement thresholds. It does
not modify findings, never uses AI, and never writes to ``apps.ledger``.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.audit_difference_models import (
    AuditDifferenceItem,
    AuditDifferenceSummary,
)
from apps.audit.general_ledger_models import GeneralLedgerRiskFinding
from apps.audit.services.gl_finding_materiality import resolve_materiality

_ZERO = Decimal("0")
_Concl = AuditDifferenceSummary.Conclusion


def _conclude(total_abs: Decimal, profile, has_accepted: bool) -> str:
    if not has_accepted:
        return _Concl.NO_ACCEPTED_DIFFERENCES
    if profile is None:
        return _Concl.NOT_ASSESSED
    if total_abs <= profile["trivial"]:
        return _Concl.BELOW_TRIVIAL
    if total_abs < profile["performance"]:
        return _Concl.BELOW_PERFORMANCE
    if total_abs < profile["overall"]:
        return _Concl.ABOVE_PERFORMANCE
    return _Concl.ABOVE_OVERALL


def recalculate_for_engagement(engagement, *, actor=None) -> AuditDifferenceSummary:
    """Rebuild the engagement's SAD from accepted GL findings. Idempotent.

    Keeps a single current summary per engagement; its items are deleted and
    recreated on each recalculation so re-running yields the same result.
    """
    organization = engagement.organization

    accepted = list(
        GeneralLedgerRiskFinding.objects
        .filter(engagement=engagement, organization=organization,
                status=GeneralLedgerRiskFinding.Status.ACCEPTED)
        .select_related("row")
    )

    profile = resolve_materiality(engagement)

    total_gross = _ZERO
    total_debit = _ZERO
    total_credit = _ZERO
    total_abs = _ZERO
    by_category: dict[str, Decimal] = defaultdict(lambda: _ZERO)
    by_account: dict[str, Decimal] = defaultdict(lambda: _ZERO)

    item_rows = []
    for f in accepted:
        amount = f.amount_impact or _ZERO
        debit = credit = _ZERO
        if f.row_id:
            debit = f.row.debit or _ZERO
            credit = f.row.credit or _ZERO
        total_gross += amount
        total_debit += debit
        total_credit += credit
        total_abs += abs(amount)
        if f.mapped_category:
            by_category[f.mapped_category] += abs(amount)
        if f.account_code:
            by_account[f.account_code] += abs(amount)

        above_trivial = above_perf = above_overall = False
        if profile is not None:
            above_trivial = abs(amount) > profile["trivial"]
            above_perf = abs(amount) >= profile["performance"]
            above_overall = abs(amount) >= profile["overall"]

        item_rows.append(dict(
            finding=f, amount=amount, debit=debit, credit=credit,
            above_trivial=above_trivial, above_perf=above_perf,
            above_overall=above_overall))

    conclusion = _conclude(total_abs, profile, bool(accepted))

    snapshot = {
        "accepted_findings": len(accepted),
        "total_gross_misstatement": str(total_gross),
        "total_absolute_impact": str(total_abs),
        "materiality_available": profile is not None,
        "overall_materiality": str(profile["overall"]) if profile else None,
        "performance_materiality": str(profile["performance"]) if profile else None,
        "trivial_threshold": str(profile["trivial"]) if profile else None,
        "conclusion_status": conclusion,
        "note": "Accepted audit differences requiring auditor evaluation. "
                "Not a final audit opinion; financial statements are not "
                "asserted to be misstated.",
    }

    now = timezone.now()
    with transaction.atomic():
        summary, _ = AuditDifferenceSummary.objects.get_or_create(
            engagement=engagement, organization=organization)
        summary.source_scope = AuditDifferenceSummary.SourceScope.GENERAL_LEDGER
        summary.status = AuditDifferenceSummary.Status.RECALCULATED
        summary.total_accepted_findings = len(accepted)
        summary.total_gross_misstatement = total_gross
        summary.total_debit_impact = total_debit
        summary.total_credit_impact = total_credit
        summary.total_absolute_impact = total_abs
        summary.overall_materiality = profile["overall"] if profile else None
        summary.performance_materiality = profile["performance"] if profile else None
        summary.trivial_threshold = profile["trivial"] if profile else None
        summary.materiality_basis = profile["basis"] if profile else ""
        summary.exceeds_performance_materiality = (
            profile is not None and total_abs >= profile["performance"])
        summary.exceeds_overall_materiality = (
            profile is not None and total_abs >= profile["overall"])
        summary.conclusion_status = conclusion
        summary.summary_by_category = {k: str(v) for k, v in by_category.items()}
        summary.summary_by_account = {k: str(v) for k, v in by_account.items()}
        summary.calculation_snapshot = snapshot
        summary.calculated_by = actor if getattr(actor, "pk", None) else None
        summary.calculated_at = now
        summary.save()

        # Idempotent rebuild of items.
        summary.items.all().delete()
        AuditDifferenceItem.objects.bulk_create([
            AuditDifferenceItem(
                summary=summary, engagement=engagement, organization=organization,
                source_type=AuditDifferenceItem.SourceType.GL_RISK_FINDING,
                gl_finding=r["finding"],
                account_code=r["finding"].account_code,
                account_name=r["finding"].account_name,
                mapped_category=r["finding"].mapped_category,
                finding_risk_code=r["finding"].risk_code,
                finding_title=r["finding"].risk_title,
                amount_impact=r["amount"], debit_impact=r["debit"],
                credit_impact=r["credit"],
                materiality_status=r["finding"].materiality_status,
                materiality_adjusted_severity=r["finding"].materiality_adjusted_severity,
                is_above_trivial=r["above_trivial"],
                is_above_performance_materiality=r["above_perf"],
                is_above_overall_materiality=r["above_overall"],
                evidence_snapshot={
                    "finding_id": str(r["finding"].id),
                    "score": r["finding"].score,
                    "severity": r["finding"].severity,
                },
            )
            for r in item_rows
        ])

    return summary


def recalculate_for_import(gl_import, *, actor=None) -> AuditDifferenceSummary:
    """Convenience entrypoint: recalc the SAD for the import's engagement."""
    if gl_import.engagement.organization_id != gl_import.organization_id:
        raise ValidationError("cross-tenant SAD recalculation denied.")
    return recalculate_for_engagement(gl_import.engagement, actor=actor)
