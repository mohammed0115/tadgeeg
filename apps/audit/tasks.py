"""
Audit App Celery Tasks

Scheduled tasks that run the Audit Rule Engine across existing data and
generate periodic audit summaries.

Scheduled tasks:
  run_weekly_audit_summary    — Monday 9:00 AM — org-wide summary of open audit cases
  audit_high_risk_documents   — Daily 3:00 AM  — re-audit recently uploaded high-risk docs
"""

import logging
import datetime

from celery import shared_task

logger = logging.getLogger("finai")


@shared_task(name="audit.run_weekly_audit_summary")
def run_weekly_audit_summary():
    """
    Generate a weekly summary of open audit cases for each active organisation.

    Logs key metrics:
      - Open case count
      - Critical / high / medium / low breakdown
      - Total escalated cases
      - Recently resolved cases
    """
    from apps.authentication.models import Organization
    from apps.audit.models import AuditCase
    from django.db.models import Count

    today    = datetime.date.today()
    week_ago = today - datetime.timedelta(days=7)
    summaries = []

    for org in Organization.objects.filter(is_active=True):
        try:
            open_cases = AuditCase.objects.filter(
                organization=org,
                status__in=[
                    AuditCase.CaseStatus.OPEN,
                    AuditCase.CaseStatus.IN_PROGRESS,
                    AuditCase.CaseStatus.UNDER_REVIEW,
                ],
            )
            breakdown = dict(
                open_cases.values("priority").annotate(cnt=Count("id")).values_list("priority", "cnt")
            )
            new_this_week = AuditCase.objects.filter(
                organization=org,
                created_at__date__gte=week_ago,
            ).count()
            resolved_this_week = AuditCase.objects.filter(
                organization=org,
                status=AuditCase.CaseStatus.RESOLVED,
                resolved_at__date__gte=week_ago,
            ).count()

            summary = {
                "org": org.name,
                "open_total": open_cases.count(),
                "breakdown": breakdown,
                "new_this_week": new_this_week,
                "resolved_this_week": resolved_this_week,
            }
            summaries.append(summary)

            logger.info(
                "[Task:audit_summary] org=%s open=%d new=%d resolved=%d",
                org.name,
                summary["open_total"],
                summary["new_this_week"],
                summary["resolved_this_week"],
            )
        except Exception as exc:
            logger.error("[Task:audit_summary] Failed for org %s: %s", org.name, exc)

    return {"organisations": len(summaries), "summaries": summaries}


@shared_task(
    bind=True,
    max_retries=1,
    name="audit.audit_high_risk_documents",
    time_limit=600,
)
def audit_high_risk_documents(self):
    """
    Daily task: re-run the Audit Rule Engine on documents uploaded in the last 24 hours
    that have a high or critical risk level, to catch any newly matching rules after
    vendor profiles and duplicate indices are updated.

    Only re-runs the AuditEngine (Stage 3) — does NOT re-OCR or re-call OpenAI.
    """
    from apps.documents.models import Document, DocumentAnalysisResult
    # Route through V2 pipeline via the legacy adapter (Prompt 1.3 migration).
    from apps.rule_engine.services.compatibility.legacy_audit_adapter import (
        LegacyAuditEngineAdapter,
    )

    yesterday = datetime.datetime.utcnow() - datetime.timedelta(hours=24)
    high_risk = DocumentAnalysisResult.objects.filter(
        risk_level__in=["high", "critical"],
        created_at__gte=yesterday,
    ).select_related("document__organization")

    audited = 0

    for ar in high_risk:
        doc = ar.document
        try:
            doc_dict = ar.analysis_data or {}
            engine = LegacyAuditEngineAdapter(organization_id=doc.organization_id)
            report = engine.evaluate(
                document=doc_dict,
                invoice_id=doc.pk,
                context={},
            )

            # Persist any newly-created audit cases for escalated findings
            if report.escalate:
                engine.save_audit_issues(report, invoice=None, created_by=None)

            # Store compact result snapshot on DocumentAnalysisResult
            ar.audit_report = {
                "audit_run_id": report.audit_run_id,
                "risk_score":   report.risk_score,
                "risk_level":   report.risk_level,
                "escalate":     report.escalate,
            }
            ar.save(update_fields=["audit_report", "updated_at"])
            audited += 1

            logger.info(
                "[Task:audit_high_risk] doc=%s risk=%s rules_failed=%d escalate=%s",
                doc.id, ar.risk_level, report.failed_count, report.escalate,
            )
        except Exception as exc:
            logger.error("[Task:audit_high_risk] Failed for doc %s: %s", doc.id, exc)

    logger.info("[Task:audit_high_risk] Complete. Audited %d high-risk documents.", audited)
    return {"audited": audited}


@shared_task(bind=True, max_retries=3, default_retry_delay=30, name="audit.generate_audit_session_summary")
def generate_audit_session_summary(self, session_id: str, language: str = "ar", use_ai: bool = False):
    """Generate and persist an executive summary for a specific audit session."""
    from apps.audit.models import AuditSession
    from apps.audit.services import AuditSessionSummaryService

    try:
        session = AuditSession.objects.get(pk=session_id)
        summary = AuditSessionSummaryService.generate_summary(session, language=language, use_ai=use_ai)
        context = dict(session.context or {})
        context.setdefault("executive_summary", {})[language] = summary
        session.context = context
        session.save(update_fields=["context", "updated_at"])
        return summary
    except Exception as exc:
        logger.error("[Task:audit_session_summary] session=%s failed: %s", session_id, exc)
        raise self.retry(exc=exc)


@shared_task(name="audit.monitor_stuck_audit_sessions")
def monitor_stuck_audit_sessions():
    """Lightweight periodic monitor for audit sessions stuck in processing states."""
    from django.utils import timezone
    from apps.audit.models import AuditSession

    threshold = timezone.now() - datetime.timedelta(minutes=30)
    stuck = AuditSession.objects.filter(
        status__in=[
            AuditSession.Status.EXTRACTING,
            AuditSession.Status.NORMALIZING,
            AuditSession.Status.VALIDATING,
        ],
        updated_at__lt=threshold,
    )

    count = stuck.count()
    logger.info("[Task:audit_monitor] stuck_sessions=%d", count)
    return {"stuck_sessions": count}
