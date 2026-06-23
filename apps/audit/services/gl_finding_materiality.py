"""Materiality classification for GL candidate findings (TADGEEG-FIN-AUDIT-3A).

Classifies each ``GeneralLedgerRiskFinding`` against engagement-level materiality
(ISA 320/450) and records a *separate* materiality-adjusted score/severity while
**preserving** the original deterministic 2B ``score``/``severity``.

It reuses the existing materiality calculator (``apps.audit.services.materiality``)
and the existing ``AuditEngagement.materiality`` JSON field as the engagement
profile — no materiality logic is duplicated, no new profile model is added.
Nothing is written to the ledger; finding ``status`` is never changed; findings
remain candidates.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.general_ledger_models import (
    GeneralLedgerImport,
    GeneralLedgerRiskFinding,
)
from apps.audit.services import materiality as materiality_service

_F = GeneralLedgerRiskFinding
_MS = _F.MaterialityStatus
_Sev = _F.Severity

# Severity ordering for capping/derivation.
_SEV_ORDER = [_Sev.LOW, _Sev.MEDIUM, _Sev.HIGH, _Sev.CRITICAL]
# Risk codes/categories that keep elevated severity even on small amounts.
_SENSITIVE_CODES = {"GL-RISK-SENSITIVE", "GL-RISK-UNBALANCED", "GL-RISK-DUP"}


def _dec(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _severity_for(score: int) -> str:
    if score <= 30:
        return _Sev.LOW
    if score <= 60:
        return _Sev.MEDIUM
    if score <= 80:
        return _Sev.HIGH
    return _Sev.CRITICAL


def resolve_materiality(engagement, override: dict | None = None) -> dict | None:
    """Return a normalised materiality profile or None if unavailable.

    Source order: explicit ``override`` → ``engagement.materiality`` JSON.
    Accepts both this module's keys and the materiality service's ``to_dict``
    keys (overall_materiality / performance_materiality / clearly_trivial).
    """
    raw = override if override else (engagement.materiality or {})
    if not raw:
        return None
    overall = _dec(raw.get("overall") or raw.get("overall_materiality"))
    performance = _dec(raw.get("performance") or raw.get("performance_materiality"))
    trivial = _dec(raw.get("trivial_threshold") or raw.get("clearly_trivial")
                   or raw.get("trivial"))
    if not overall or overall <= 0:
        return None
    # Sensible fallbacks if only overall is supplied.
    if not performance or performance <= 0:
        performance = (overall * Decimal("0.75")).quantize(Decimal("0.01"))
    if trivial is None or trivial < 0:
        trivial = (overall * Decimal("0.05")).quantize(Decimal("0.01"))
    return {
        "overall": overall,
        "performance": performance,
        "trivial": trivial,
        "basis": str(raw.get("basis") or raw.get("benchmark") or raw.get("benchmark_basis") or ""),
        "currency": str(raw.get("currency") or ""),
    }


def compute_from_benchmark(*, benchmark_amount, benchmark_key="profit_before_tax", **kwargs) -> dict:
    """Compute a materiality profile via the existing service (no duplication)."""
    result = materiality_service.calculate(
        benchmark_amount=benchmark_amount, benchmark_key=benchmark_key, **kwargs)
    return result.to_dict()


def _classify(amount, profile) -> str:
    if amount is None or amount <= 0:
        return _MS.UNKNOWN_AMOUNT
    if amount <= profile["trivial"]:
        return _MS.TRIVIAL
    if amount < profile["performance"]:
        return _MS.BELOW_PERFORMANCE
    if amount < profile["overall"]:
        return _MS.ABOVE_PERFORMANCE
    return _MS.ABOVE_OVERALL


def _adjust(original_score, original_severity, status, *, sensitive: bool):
    """Return (adjusted_score, adjusted_severity), deterministic, capped 0..100."""
    score = int(original_score)
    if status in (_MS.NOT_ASSESSED, _MS.UNKNOWN_AMOUNT):
        return score, original_severity
    if status == _MS.ABOVE_OVERALL:
        score = min(100, score + 25)
    elif status == _MS.ABOVE_PERFORMANCE:
        score = min(100, score + 12)
    elif status == _MS.BELOW_PERFORMANCE:
        score = score  # no change
    elif status == _MS.TRIVIAL:
        # Trivial amounts cap severity at medium (score ≤ 60) — UNLESS the
        # original was critical, or it is a sensitive code (then keep ≤ high).
        if original_severity == _Sev.CRITICAL:
            pass
        elif sensitive:
            score = min(score, 80)  # keep up to "high"
        else:
            score = min(score, 60)  # cap at "medium"
    return score, _severity_for(score)


def _ratio(amount, denom):
    if amount is None or denom is None or denom <= 0:
        return None
    return (amount / denom).quantize(Decimal("0.0001"))


def _apply_to_queryset(findings, profile, snapshot) -> dict:
    now = timezone.now()
    by_status: dict[str, int] = {}
    by_adj_severity: dict[str, int] = {}
    updated = []
    for f in findings:
        amount = f.amount_impact
        if profile is None:
            status = _MS.NOT_ASSESSED
            adj_score, adj_sev = int(f.score), f.severity
            f.materiality_overall = None
            f.materiality_performance = None
            f.materiality_trivial_threshold = None
            f.amount_to_overall_materiality_ratio = None
            f.amount_to_performance_materiality_ratio = None
            f.materiality_basis = ""
        else:
            status = _classify(amount, profile)
            sensitive = f.risk_code in _SENSITIVE_CODES
            adj_score, adj_sev = _adjust(f.score, f.severity, status, sensitive=sensitive)
            f.materiality_overall = profile["overall"]
            f.materiality_performance = profile["performance"]
            f.materiality_trivial_threshold = profile["trivial"]
            f.materiality_basis = profile["basis"]
            f.amount_to_overall_materiality_ratio = _ratio(amount, profile["overall"])
            f.amount_to_performance_materiality_ratio = _ratio(amount, profile["performance"])

        f.materiality_status = status
        f.materiality_adjusted_score = adj_score
        f.materiality_adjusted_severity = adj_sev
        f.materiality_assessed_at = now
        f.materiality_snapshot = snapshot
        # NOTE: original score/severity and `status` are intentionally untouched.
        updated.append(f)
        by_status[status] = by_status.get(status, 0) + 1
        by_adj_severity[adj_sev] = by_adj_severity.get(adj_sev, 0) + 1

    with transaction.atomic():
        GeneralLedgerRiskFinding.objects.bulk_update(updated, [
            "materiality_status", "materiality_basis", "materiality_overall",
            "materiality_performance", "materiality_trivial_threshold",
            "amount_to_overall_materiality_ratio",
            "amount_to_performance_materiality_ratio",
            "materiality_adjusted_score", "materiality_adjusted_severity",
            "materiality_assessed_at", "materiality_snapshot",
        ])

    return {
        "assessed": len(updated),
        "materiality_available": profile is not None,
        "by_materiality_status": by_status,
        "by_adjusted_severity": by_adj_severity,
    }


def apply_materiality_to_import(gl_import: GeneralLedgerImport, *,
                                materiality: dict | None = None,
                                benchmark_amount=None, benchmark_key="profit_before_tax",
                                persist_profile: bool = True, **calc_kwargs) -> dict:
    """Classify all risk findings of one GL import against materiality.

    Materiality source order:
      1. ``benchmark_amount`` → compute via the materiality service (and, if
         ``persist_profile``, store it on ``engagement.materiality``);
      2. explicit ``materiality`` dict override;
      3. existing ``engagement.materiality``.
    Idempotent: re-running recomputes the same values. Findings' ``status`` and
    original score/severity are preserved.
    """
    if gl_import.engagement.organization_id != gl_import.organization_id:
        raise ValidationError("cross-tenant materiality apply denied.")

    engagement = gl_import.engagement
    profile_dict = None
    if benchmark_amount is not None:
        computed = compute_from_benchmark(
            benchmark_amount=benchmark_amount, benchmark_key=benchmark_key, **calc_kwargs)
        if persist_profile:
            engagement.materiality = computed
            engagement.save(update_fields=["materiality", "updated_at"])
        profile_dict = computed
    elif materiality is not None:
        profile_dict = materiality

    profile = resolve_materiality(engagement, override=profile_dict)
    snapshot = profile_dict if profile_dict is not None else (engagement.materiality or {})

    findings = list(gl_import.risk_findings.all())
    summary = _apply_to_queryset(findings, profile, snapshot)
    summary["import_id"] = str(gl_import.id)
    return summary
