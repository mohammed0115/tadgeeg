"""Engagement report builder (TADGEEG-G6).

Assemble a versioned report snapshot from the traceability spine. ISA 700-safe:
communicates facts + a disclaimer, never an opinion. No ledger writes.
"""
from __future__ import annotations

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.report_models import EngagementReport

_R = EngagementReport
_St = _R.Status
_VALID_STATUS = {s.value for s in _St}

REPORT_DISCLAIMER = (
    "This report communicates the results of audit procedures performed and "
    "matters identified. It does not constitute an audit opinion under ISA 700 "
    "and does not state whether the financial statements present fairly, in all "
    "material respects, the financial position of the entity."
)


class ReportBuilderError(Exception):
    """Invalid input or scoping violation."""


def build_content(engagement) -> dict:
    """Assemble the report body from the linked engagement data (facts only)."""
    org = engagement.organization
    from apps.audit.services import assessed_risk as ar
    from apps.audit.services import audit_procedure as ap
    from apps.audit.services import audit_issue as ai
    from apps.audit.services import findings_register as fr

    def _safe(fn, default):
        try:
            return fn()
        except Exception:  # noqa: BLE001 - a report section must never 500
            return default

    risks = _safe(lambda: ar.summary(organization=org, engagement=engagement), {})
    procedures = _safe(lambda: ap.summary(organization=org, engagement=engagement), {})
    findings = _safe(lambda: fr.summary(organization=org, engagement=engagement), {})
    issues = _safe(lambda: ai.summary(organization=org, engagement=engagement), {})
    finding_rows = _safe(
        lambda: fr.list_findings(organization=org, engagement=engagement, limit=200), [])

    content = {
        "engagement_code": engagement.engagement_code,
        "engagement_title": engagement.title,
        "stage": engagement.stage,
        "executive_summary": {
            "assessed_risks": risks.get("total", 0),
            "significant_risks": risks.get("significant", 0),
            "procedures": procedures.get("total", 0),
            "findings": findings.get("total", 0),
            "open_issues": issues.get("open", 0),
            "overdue_issues": issues.get("overdue", 0),
        },
        "risks": risks,
        "procedures": procedures,
        "findings": findings,
        "findings_detail": finding_rows,
        "issues": issues,
        "not_an_opinion": True,
        "disclaimer": REPORT_DISCLAIMER,
    }
    # Guarantee a JSON-safe snapshot (finding rows carry datetimes/Decimals).
    import json
    from django.core.serializers.json import DjangoJSONEncoder
    return json.loads(json.dumps(content, cls=DjangoJSONEncoder))


def _next_reference(organization) -> str:
    count = EngagementReport.objects.filter(organization=organization).count()
    return f"REP-{count + 1:05d}"


def create_report(*, engagement, actor, title="") -> EngagementReport:
    """Create a DRAFT report (version 1) with freshly assembled content."""
    obj = EngagementReport(
        engagement=engagement, organization=engagement.organization,
        title=(title or f"Audit report — {engagement.engagement_code}")[:255],
        version=1, status=_St.DRAFT, content=build_content(engagement),
        not_an_opinion=True,
        created_by=actor if getattr(actor, "pk", None) else None)
    obj.full_clean(exclude=["created_by", "reference"])
    with transaction.atomic():
        for attempt in range(5):
            obj.reference = _next_reference(engagement.organization)
            try:
                with transaction.atomic():
                    obj.save()
                break
            except IntegrityError:
                if attempt == 4:
                    raise
    return obj


def new_version(*, report, actor) -> EngagementReport:
    """Supersede a report with a freshly-assembled next version (DRAFT)."""
    latest = (EngagementReport.objects.filter(engagement=report.engagement)
              .order_by("-version").first())
    next_v = (latest.version if latest else report.version) + 1
    obj = EngagementReport(
        engagement=report.engagement, organization=report.organization,
        title=report.title, version=next_v, status=_St.DRAFT,
        content=build_content(report.engagement), not_an_opinion=True,
        reference=_next_reference(report.organization),
        created_by=actor if getattr(actor, "pk", None) else None)
    obj.save()
    return obj


def set_status(*, report, actor, status) -> EngagementReport:
    if status not in _VALID_STATUS:
        raise ReportBuilderError(f"invalid status: {status!r}")
    report.status = status
    fields = ["status", "updated_at"]
    if status == _St.FINAL and report.finalized_at is None:
        report.finalized_at = timezone.now()
        fields.append("finalized_at")
    report.save(update_fields=fields)
    return report


def list_reports(*, engagement, limit=100):
    return list(EngagementReport.objects.filter(engagement=engagement)
                .select_related("created_by")[:limit])
