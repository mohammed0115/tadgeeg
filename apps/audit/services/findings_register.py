"""Unified findings register (TADGEEG-G2.3).

A read-only aggregation that presents the two ``apps.audit`` finding types under
one normalized shape, so an auditor sees a single findings list per engagement:

  * ``GeneralLedgerRiskFinding`` (2B) — machine-suggested GL risk findings.
  * ``AuditControlDeficiency`` (9B) — internal-control deficiencies (ISA 265).

This is additive and non-destructive: it does NOT merge the underlying models
(that is a later, migration-gated step). It normalizes on read and exposes each
finding's link to its ``AssessedRisk`` (G2.3), so the register participates in
the traceability chain. No ledger writes.
"""
from __future__ import annotations

from apps.audit.control_deficiency_models import AuditControlDeficiency
from apps.audit.general_ledger_models import GeneralLedgerRiskFinding

# Rank GL finding severities + deficiency classifications onto one scale.
_GL_SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}
_DEF_CLASS_RANK = {"material_weakness": 4, "significant_deficiency": 3,
                   "other_deficiency": 2}


def _gl_row(f: GeneralLedgerRiskFinding) -> dict:
    return {
        "source": "gl_finding",
        # GeneralLedgerRiskFinding fields are risk_code / risk_title /
        # risk_description (there is no `reference` / `description`).
        "id": str(f.id),
        "reference": getattr(f, "risk_code", "") or str(f.id)[:8],
        "title": (getattr(f, "risk_title", "") or getattr(f, "risk_description", "")
                  or "GL risk finding")[:160],
        "severity": f.severity,
        "severity_rank": _GL_SEVERITY_RANK.get(f.severity, 0),
        "status": f.status,
        "assessed_risk_id": str(f.assessed_risk_id) if f.assessed_risk_id else None,
        "created_at": f.created_at,
    }


def _def_row(d: AuditControlDeficiency) -> dict:
    return {
        "source": "control_deficiency",
        "id": str(d.id),
        "reference": d.reference or str(d.id)[:8],
        "title": (d.title or "Control deficiency")[:160],
        "severity": d.classification,
        "severity_rank": _DEF_CLASS_RANK.get(d.classification, 0),
        "status": d.status,
        "assessed_risk_id": str(d.assessed_risk_id) if d.assessed_risk_id else None,
        "created_at": d.created_at,
    }


def list_findings(*, organization, engagement=None, source=None, limit=1000) -> list[dict]:
    """Normalized, severity-sorted findings across both audit finding types."""
    out: list[dict] = []
    if source in (None, "gl_finding"):
        gl = GeneralLedgerRiskFinding.objects.filter(organization=organization)
        if engagement is not None:
            gl = gl.filter(engagement=engagement)
        out.extend(_gl_row(f) for f in gl.select_related("assessed_risk")[:limit])
    if source in (None, "control_deficiency"):
        de = AuditControlDeficiency.objects.filter(organization=organization)
        if engagement is not None:
            de = de.filter(engagement=engagement)
        out.extend(_def_row(d) for d in de.select_related("assessed_risk")[:limit])
    out.sort(key=lambda r: (-r["severity_rank"], r["created_at"] or 0), reverse=False)
    # (severity desc already via -rank; keep newest first within same severity)
    out.sort(key=lambda r: r["severity_rank"], reverse=True)
    return out[:limit]


def summary(*, organization, engagement=None) -> dict:
    """Counts by source + how many are linked to an assessed risk."""
    rows = list_findings(organization=organization, engagement=engagement)
    linked = sum(1 for r in rows if r["assessed_risk_id"])
    return {
        "total": len(rows),
        "gl_findings": sum(1 for r in rows if r["source"] == "gl_finding"),
        "control_deficiencies": sum(1 for r in rows if r["source"] == "control_deficiency"),
        "linked_to_risk": linked,
        "unlinked": len(rows) - linked,
    }
