"""Audit Readiness / Opinion Preparation Workpaper service (TADGEEG-FIN-AUDIT-5A).

Builds a non-final audit-readiness aid from the engagement's current SAD, the
management responses on its items, and proposed adjustments. It produces a
readiness conclusion and a *cautious* suggested opinion DIRECTION (always
"subject to auditor review") plus a legal disclaimer.

It NEVER issues a formal opinion, never calls the ISA-700 opinion service to
issue one, never uses AI, never modifies SAD/items/findings, and never writes to
``apps.ledger``. The final opinion belongs to the licensed auditor.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.audit.audit_difference_models import (
    AuditDifferenceItem,
    AuditDifferenceSummary,
    ProposedAuditAdjustment,
)
from apps.audit.audit_readiness_models import LEGAL_DISCLAIMER, AuditReadinessWorkpaper
from apps.audit.general_ledger_models import GeneralLedgerRiskFinding

_W = AuditReadinessWorkpaper
_RC = _W.ReadinessConclusion
_OD = _W.OpinionDirection
_MR = AuditDifferenceItem.ManagementResponse
_ZERO = Decimal("0")


class ReadinessError(Exception):
    """Raised when a readiness workpaper cannot be built (e.g. no SAD)."""


# Conclusion → cautious direction (always "subject to auditor review").
_DIRECTION = {
    _RC.NO_ACCEPTED_DIFFERENCES:       _OD.LIKELY_UNMODIFIED,
    _RC.DIFFERENCES_BELOW_MATERIALITY: _OD.LIKELY_UNMODIFIED,
    _RC.UNADJUSTED_NEED_EVALUATION:    _OD.POSSIBLE_MODIFIED,
    _RC.POSSIBLE_MATERIAL_IMPACT:      _OD.POSSIBLE_MODIFIED,
    _RC.INSUFFICIENT_EVIDENCE:         _OD.INSUFFICIENT_BASIS,
    _RC.NOT_ASSESSED:                  _OD.NO_DIRECTION,
}


def _conclude(*, accepted, needs_evidence, pending, uncorrected_total,
              profile_available, overall, trivial) -> str:
    if not profile_available:
        return _RC.NOT_ASSESSED
    if accepted == 0:
        return _RC.INSUFFICIENT_EVIDENCE if needs_evidence else _RC.NO_ACCEPTED_DIFFERENCES
    if needs_evidence:
        return _RC.INSUFFICIENT_EVIDENCE
    if overall is not None and uncorrected_total >= overall:
        return _RC.POSSIBLE_MATERIAL_IMPACT
    if pending or (trivial is not None and uncorrected_total > trivial):
        return _RC.UNADJUSTED_NEED_EVALUATION
    return _RC.DIFFERENCES_BELOW_MATERIALITY


def generate_for_engagement(engagement, *, actor=None) -> AuditReadinessWorkpaper:
    """Build (idempotently) the engagement's readiness workpaper from its SAD."""
    organization = engagement.organization

    summary = (AuditDifferenceSummary.objects
               .filter(engagement=engagement, organization=organization)
               .order_by("-created_at").first())
    if summary is None:
        raise ReadinessError(
            "no SAD summary for this engagement — recalculate the SAD first.")

    items = list(summary.items.all())
    by_response: dict[str, int] = defaultdict(int)
    adjusted_total = _ZERO
    for it in items:
        by_response[it.management_response_status] += 1
        if it.management_response_status == _MR.ADJUSTED:
            adjusted_total += abs(it.amount_impact)

    accepted = len(items)
    total_adjusted = by_response.get(_MR.ADJUSTED, 0)
    total_unadjusted = by_response.get(_MR.UNADJUSTED, 0)
    # "Pending" = response not yet concluded (not requested or still pending).
    total_pending = by_response.get(_MR.NOT_REQUESTED, 0) + by_response.get(_MR.PENDING, 0)

    # Open evidence requests on the engagement's GL findings (not yet accepted).
    total_needs_evidence = GeneralLedgerRiskFinding.objects.filter(
        engagement=engagement, organization=organization,
        status=GeneralLedgerRiskFinding.Status.NEEDS_EVIDENCE).count()

    total_abs = summary.total_absolute_impact or _ZERO
    uncorrected_total = total_abs - adjusted_total  # differences not adjusted
    if uncorrected_total < _ZERO:
        uncorrected_total = _ZERO

    overall = summary.overall_materiality
    performance = summary.performance_materiality
    trivial = summary.trivial_threshold
    profile_available = summary.conclusion_status != AuditDifferenceSummary.Conclusion.NOT_ASSESSED \
        and overall is not None

    conclusion = _conclude(
        accepted=accepted, needs_evidence=total_needs_evidence,
        pending=total_pending, uncorrected_total=uncorrected_total,
        profile_available=profile_available, overall=overall, trivial=trivial)
    direction = _DIRECTION.get(conclusion, _OD.NO_DIRECTION)

    # Proposed adjustments for this SAD (documentation only).
    adjustments = list(ProposedAuditAdjustment.objects.filter(summary=summary))
    adj_by_status: dict[str, int] = defaultdict(int)
    adj_total = _ZERO
    for a in adjustments:
        adj_by_status[a.status] += 1
        adj_total += abs(a.amount or _ZERO)

    conclusion_basis = {
        "sad_conclusion_status": summary.conclusion_status,
        "accepted_differences": accepted,
        "uncorrected_total": str(uncorrected_total),
        "adjusted_total": str(adjusted_total),
        "overall_materiality": str(overall) if overall is not None else None,
        "performance_materiality": str(performance) if performance is not None else None,
        "trivial_threshold": str(trivial) if trivial is not None else None,
        "open_needs_evidence_findings": total_needs_evidence,
        "pending_management_responses": total_pending,
        "note": "Readiness aid only. Not a formal audit opinion; the final "
                "opinion is the licensed auditor's professional judgment.",
    }

    now = timezone.now()
    with transaction.atomic():
        wp, _created = AuditReadinessWorkpaper.objects.get_or_create(
            engagement=engagement, organization=organization,
            defaults={"sad_summary": summary})
        wp.sad_summary = summary
        wp.status = _W.Status.AUDITOR_REVIEW_REQUIRED
        wp.readiness_conclusion = conclusion
        wp.suggested_opinion_direction = direction
        wp.total_accepted_differences = accepted
        wp.total_unadjusted_differences = total_unadjusted
        wp.total_adjusted_differences = total_adjusted
        wp.total_pending_management_response = total_pending
        wp.total_needs_evidence = total_needs_evidence
        wp.total_absolute_impact = total_abs
        wp.overall_materiality = overall
        wp.performance_materiality = performance
        wp.conclusion_basis = conclusion_basis
        wp.unadjusted_summary = {
            "count": total_unadjusted,
            "uncorrected_total": str(uncorrected_total),
        }
        wp.management_response_summary = {k: v for k, v in by_response.items()}
        wp.proposed_adjustment_summary = {
            "count": len(adjustments),
            "total": str(adj_total),
            "by_status": dict(adj_by_status),
        }
        wp.legal_disclaimer = LEGAL_DISCLAIMER
        wp.generated_by = actor if getattr(actor, "pk", None) else None
        wp.generated_at = now
        wp.save()
    return wp
