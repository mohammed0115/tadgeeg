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
    """Assemble a complete report body from the linked engagement data.

    A missing source is not represented as an empty section: an auditor cannot
    distinguish an actual zero from a failed query in that form.  The caller
    must resolve the source failure before it can create or version a report.
    """
    org = engagement.organization
    from apps.audit.services import assessed_risk as ar
    from apps.audit.services import audit_procedure as ap
    from apps.audit.services import audit_issue as ai
    from apps.audit.services import findings_register as fr

    def _required(section, fn):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - preserve the source cause
            raise ReportBuilderError(
                f"Unable to assemble required report section: {section}."
            ) from exc

    risks = _required("assessed_risks", lambda: ar.summary(organization=org, engagement=engagement))
    procedures = _required("procedures", lambda: ap.summary(organization=org, engagement=engagement))
    findings = _required("findings", lambda: fr.summary(organization=org, engagement=engagement))
    issues = _required("issues", lambda: ai.summary(organization=org, engagement=engagement))
    finding_rows = _required(
        "findings_detail",
        lambda: fr.list_findings(organization=org, engagement=engagement, limit=200),
    )

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


_ALLOWED_TRANSITIONS = {
    _St.DRAFT: {_St.IN_REVIEW},
    _St.IN_REVIEW: {_St.DRAFT, _St.FINAL},
    _St.FINAL: set(),
    _St.ARCHIVED: set(),
}


def _require_final_signoffs(report) -> None:
    """Require independent review and partner approval before finalization."""
    from apps.audit.services import signoff
    from apps.audit.signoff_models import EngagementSignoff

    artifact_type = "engagement_report"
    artifact_id = str(report.pk)
    required_roles = (EngagementSignoff.Role.REVIEWER, EngagementSignoff.Role.PARTNER)
    rows = signoff.signoffs_for(
        engagement=report.engagement,
        artifact_type=artifact_type,
        artifact_id=artifact_id,
    )
    signers = {
        row.role: row.signed_by_id
        for row in rows
        if row.role in required_roles and row.signed_by_id is not None
    }
    missing = [role.value for role in required_roles if role not in signers]
    if missing:
        raise ReportBuilderError(
            "Cannot finalize report without required sign-offs: " + ", ".join(missing)
        )
    if signers[EngagementSignoff.Role.REVIEWER] == signers[EngagementSignoff.Role.PARTNER]:
        raise ReportBuilderError("Reviewer and partner sign-offs must be independent.")


def set_status(*, report, actor, status) -> EngagementReport:
    if status not in _VALID_STATUS:
        raise ReportBuilderError(f"invalid status: {status!r}")
    if status == report.status:
        return report
    if status not in _ALLOWED_TRANSITIONS[report.status]:
        raise ReportBuilderError(
            f"invalid report transition: {report.status!r} -> {status!r}"
        )
    if status == _St.FINAL:
        _require_final_signoffs(report)

    report.status = status
    fields = ["status", "updated_at"]
    if status == _St.FINAL:
        report.finalized_at = timezone.now()
        fields.append("finalized_at")
    report.save(update_fields=fields)
    return report


def list_reports(*, engagement, limit=100):
    return list(EngagementReport.objects.filter(engagement=engagement)
                .select_related("created_by")[:limit])
