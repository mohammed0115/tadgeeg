"""Audit Readiness export service (TADGEEG-FIN-AUDIT-5D).

Renders an :class:`AuditReadinessWorkpaper` (5A) to safe, auditor-review-ready
output in JSON / HTML / PDF. Every export:

  * is a READ of the workpaper — it never modifies the workpaper, its SAD, items,
    findings, or proposed adjustments;
  * carries the legal disclaimer and is labelled "Audit Readiness Report /
    Opinion Preparation Draft — Suggested Direction Subject to Auditor Review";
  * never asserts a formal audit opinion ("in our opinion", "present fairly",
    "opinion issued", …) — the final opinion belongs to a licensed auditor;
  * never calls AI and never writes to ``apps.ledger``.

PDF rendering reuses the project's existing WeasyPrint infrastructure (already
used safely in ``apps.reports.views``); it is optional and degrades gracefully.
"""
from __future__ import annotations

from decimal import Decimal

from django.template.loader import render_to_string

from apps.audit.audit_readiness_models import (
    LEGAL_DISCLAIMER,
    AuditReadinessWorkpaper,
)
from apps.reports.services.isa700_opinion_service import (
    SAFE_DISCLAIMER_AR,
    SAFE_DISCLAIMER_EN,
    build_readiness_draft_from_workpaper,
)

_W = AuditReadinessWorkpaper

HTML_TEMPLATE = "audit/audit_readiness_report.html"

# Safe, non-formal-opinion labels for every export surface.
REPORT_TITLE_EN = "Audit Readiness Report — Opinion Preparation Draft"
REPORT_TITLE_AR = "تقرير جاهزية التدقيق — مسوّدة تحضير الرأي"
DIRECTION_BANNER_EN = "Suggested Direction — Subject to Auditor Review"
DIRECTION_BANNER_AR = "اتجاه مقترح — رهن مراجعة المدقّق"
FINAL_OPINION_NOTICE_EN = "Final Opinion Requires Licensed Auditor Approval"
FINAL_OPINION_NOTICE_AR = "الرأي النهائي يتطلب اعتماد مدقّق مرخّص"


class ReadinessExportError(Exception):
    """Raised when a workpaper cannot be exported."""


def _s(value):
    """JSON-safe scalar (Decimal → str, else passthrough)."""
    if isinstance(value, Decimal):
        return str(value)
    return value


def _display(instance, field):
    getter = getattr(instance, f"get_{field}_display", None)
    return getter() if callable(getter) else getattr(instance, field, None)


def build_export_payload(workpaper: AuditReadinessWorkpaper, *,
                         include_isa700_draft: bool = True,
                         include_evidence: bool = True) -> dict:
    """Build a structured, JSON-safe export payload for a readiness workpaper.

    Pure read: does not modify the workpaper or any source record.
    """
    if workpaper is None:
        raise ReadinessExportError("workpaper is required.")

    engagement = workpaper.engagement
    sad = workpaper.sad_summary

    generated_by = None
    if workpaper.generated_by_id:
        generated_by = {
            "id": workpaper.generated_by_id,
            "full_name": getattr(workpaper.generated_by, "full_name", None),
            "email": getattr(workpaper.generated_by, "email", None),
        }

    payload = {
        # ── Labelling (safe, non-formal-opinion) ──────────────────────────────
        "report_type": "audit_readiness_report",
        "report_title_en": REPORT_TITLE_EN,
        "report_title_ar": REPORT_TITLE_AR,
        "is_formal_opinion": False,
        "subject_to_auditor_review": True,
        "final_opinion_notice_en": FINAL_OPINION_NOTICE_EN,
        "final_opinion_notice_ar": FINAL_OPINION_NOTICE_AR,

        # ── Engagement info ───────────────────────────────────────────────────
        "engagement": {
            "id": str(engagement.id),
            "engagement_code": engagement.engagement_code,
            "title": engagement.title,
            "period_start": _s(engagement.period_start),
            "period_end": _s(engagement.period_end),
            "organization_id": workpaper.organization_id,
        },

        # ── Workpaper identity / provenance ───────────────────────────────────
        "workpaper": {
            "id": str(workpaper.id),
            "status": workpaper.status,
            "status_display": _display(workpaper, "status"),
            "generated_by": generated_by,
            "generated_at": _s(workpaper.generated_at),
            "created_at": _s(workpaper.created_at),
            "updated_at": _s(workpaper.updated_at),
        },

        # ── SAD summary snapshot ──────────────────────────────────────────────
        "sad_summary": {
            "id": str(sad.id),
            "conclusion_status": sad.conclusion_status,
            "conclusion_status_display": _display(sad, "conclusion_status"),
            "total_absolute_impact": _s(sad.total_absolute_impact),
            "exceeds_performance_materiality": sad.exceeds_performance_materiality,
            "exceeds_overall_materiality": sad.exceeds_overall_materiality,
        },

        # ── Readiness conclusion & suggested direction ────────────────────────
        "readiness_conclusion": workpaper.readiness_conclusion,
        "readiness_conclusion_display": _display(workpaper, "readiness_conclusion"),
        "suggested_direction": {
            "code": workpaper.suggested_opinion_direction,
            "label": _display(workpaper, "suggested_opinion_direction"),
            "banner_en": DIRECTION_BANNER_EN,
            "banner_ar": DIRECTION_BANNER_AR,
            "subject_to_auditor_review": True,
        },
        "conclusion_basis": workpaper.conclusion_basis,

        # ── Difference / response / adjustment summaries ──────────────────────
        "management_response_summary": workpaper.management_response_summary,
        "proposed_adjustment_summary": workpaper.proposed_adjustment_summary,
        "unadjusted_summary": workpaper.unadjusted_summary,
        "difference_counts": {
            "accepted": workpaper.total_accepted_differences,
            "adjusted": workpaper.total_adjusted_differences,
            "unadjusted": workpaper.total_unadjusted_differences,
            "pending_management_response": workpaper.total_pending_management_response,
            "needs_evidence": workpaper.total_needs_evidence,
            "total_absolute_impact": _s(workpaper.total_absolute_impact),
        },
        "open_evidence_requests": workpaper.total_needs_evidence,

        # ── Materiality snapshot ──────────────────────────────────────────────
        "materiality": {
            "overall": _s(workpaper.overall_materiality),
            "performance": _s(workpaper.performance_materiality),
        },

        # ── Required disclaimer (always present) ──────────────────────────────
        "disclaimer": workpaper.legal_disclaimer or LEGAL_DISCLAIMER,
        "disclaimer_en": SAFE_DISCLAIMER_EN,
        "disclaimer_ar": SAFE_DISCLAIMER_AR,
    }

    if include_isa700_draft:
        # Optional: hardened ISA-700 draft paragraph sourced from THIS workpaper.
        payload["isa700_draft"] = build_readiness_draft_from_workpaper(workpaper)

    if include_evidence:
        # TADGEEG-FIN-AUDIT-6D — evidence assurance + immutable evidence index.
        # INFORMATIONAL ONLY: this never feeds the readiness conclusion, which
        # is computed solely by the 5A service and is not touched here.
        from apps.audit.services import evidence_assurance as assurance
        payload["evidence_assurance"] = assurance.readiness_evidence_section(
            organization=workpaper.organization, engagement=engagement)
        payload["evidence_index"] = assurance.evidence_index(
            organization=workpaper.organization, engagement=engagement)

    return payload


def render_html(workpaper: AuditReadinessWorkpaper, *,
                include_isa700_draft: bool = True,
                include_evidence: bool = True) -> str:
    """Render the readiness workpaper to a safe, self-contained HTML document."""
    payload = build_export_payload(workpaper, include_isa700_draft=include_isa700_draft,
                                   include_evidence=include_evidence)
    return render_to_string(HTML_TEMPLATE, {"r": payload})


def render_pdf(workpaper: AuditReadinessWorkpaper, *, base_url: str = "",
               include_isa700_draft: bool = True,
               include_evidence: bool = True) -> bytes:
    """Render the readiness workpaper to PDF via the existing WeasyPrint infra.

    Raises :class:`ReadinessExportError` if WeasyPrint is unavailable so callers
    can fall back to HTML/JSON.
    """
    html_str = render_html(workpaper, include_isa700_draft=include_isa700_draft,
                           include_evidence=include_evidence)
    try:
        from weasyprint import HTML as WP_HTML
    except Exception as exc:  # pragma: no cover - depends on system libs
        raise ReadinessExportError(f"PDF export unavailable: {exc}") from exc
    return WP_HTML(string=html_str, base_url=base_url).write_pdf()
