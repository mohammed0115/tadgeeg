"""
Audit App Celery Tasks

Scheduled tasks that run the Audit Rule Engine across existing data and
generate periodic audit summaries.

Scheduled tasks:
  run_weekly_audit_summary    — Monday 9:00 AM — org-wide summary of open audit cases
  audit_high_risk_documents   — Daily 3:00 AM  — re-audit recently uploaded high-risk docs

On-demand tasks (called from upload views):
  process_audit_session       — Advance a session through the state machine
  generate_session_summary    — Build AI executive summary for a completed session
  retry_session_failed_docs   — Retry failed documents inside a session
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
                    AuditCase.Status.OPEN,
                    AuditCase.Status.IN_PROGRESS,
                    AuditCase.Status.UNDER_REVIEW,
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
                status=AuditCase.Status.RESOLVED,
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
    from apps.audit.audit_engine import AuditEngine
    from core.services.pipeline import _serialise_audit_report

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
            context = {
                "duplicate_result": {
                    "duplicate_score": ar.duplicate_score,
                    "is_duplicate":    ar.is_duplicate,
                    "duplicate_reasons": doc_dict.get("duplicate_reasons", []),
                },
                "compliance_result": {
                    "compliance_score": ar.compliance_score,
                    "vat_valid":        doc_dict.get("vat_valid", True),
                    "issues":           doc_dict.get("compliance_issues", []),
                    "missing_fields":   doc_dict.get("missing_fields", []),
                },
            }
            engine = AuditEngine(organization_id=doc.organization_id)
            report = engine.evaluate(document=doc_dict, context=context)

            # Persist any newly-created audit cases for escalated findings
            if report.escalate:
                engine.save_audit_issues(report, invoice=None, created_by=None)

            ar.audit_report = _serialise_audit_report(report)
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


# ── Session tasks ──────────────────────────────────────────────────────────────

@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    name="audit.process_audit_session",
    time_limit=900,
)
def process_audit_session(self, session_id: str, language: str = "ar"):
    """
    Drive an AuditSession through its state machine after all documents
    have been submitted for processing.

    Called by the upload view once all per-document tasks are dispatched.

    Steps:
      RECEIVED → EXTRACTING → NORMALIZING → VALIDATING → COMPLETED/REVIEW_REQUIRED
    """
    from .models import AuditSession
    from .session_service import AuditSessionService, InvalidStateTransition

    try:
        session = AuditSession.objects.get(pk=session_id)
    except AuditSession.DoesNotExist:
        logger.error("[Task:process_session] Session %s not found", session_id)
        return {"error": "session_not_found"}

    if session.is_terminal:
        logger.info("[Task:process_session] Session %s already terminal (%s)", session_id, session.state)
        return {"state": session.state}

    svc = AuditSessionService(session)

    try:
        # Walk through intermediate states
        for next_state in [
            AuditSession.State.EXTRACTING,
            AuditSession.State.NORMALIZING,
            AuditSession.State.VALIDATING,
        ]:
            if session.can_transition_to(next_state):
                svc.transition(next_state)
                session = svc.session

        # Attempt final completion
        svc.maybe_complete()

        # Generate AI summary if session is done
        if session.state in (AuditSession.State.COMPLETED, AuditSession.State.REVIEW_REQUIRED):
            generate_session_summary.delay(session_id=session_id, language=language)

    except InvalidStateTransition as exc:
        logger.warning("[Task:process_session] Transition error for %s: %s", session_id, exc)
    except Exception as exc:
        logger.exception("[Task:process_session] Unhandled error for %s: %s", session_id, exc)
        try:
            svc.transition(AuditSession.State.FAILED)
        except Exception:
            pass
        raise self.retry(exc=exc)

    session.refresh_from_db()
    return {"session_id": session_id, "state": session.state, "progress": session.progress_pct}


@shared_task(
    bind=True,
    max_retries=1,
    name="audit.generate_session_summary",
    time_limit=120,
)
def generate_session_summary(self, session_id: str, language: str = "ar"):
    """
    Generate and persist an AI executive summary for an AuditSession.
    Called automatically when a session reaches COMPLETED or REVIEW_REQUIRED.
    """
    from .models import AuditSession
    from .session_service import AuditSessionService

    try:
        session = AuditSession.objects.get(pk=session_id)
    except AuditSession.DoesNotExist:
        logger.error("[Task:session_summary] Session %s not found", session_id)
        return

    try:
        svc = AuditSessionService(session)
        narrative = svc.generate_executive_summary(language=language)
        logger.info(
            "[Task:session_summary] Generated summary for session %s (%d sections)",
            session_id, len(narrative),
        )
        return {"session_id": session_id, "sections": len(narrative)}
    except Exception as exc:
        logger.exception("[Task:session_summary] Failed for %s: %s", session_id, exc)
        raise self.retry(exc=exc)


@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    name="audit.retry_session_failed_docs",
    time_limit=600,
)
def retry_session_failed_docs(self, session_id: str):
    """
    Retry all failed invoices that belong to a given AuditSession.
    Resets the session's failed_count and re-dispatches processing.
    """
    from .models import AuditSession
    from apps.invoices.models import Invoice

    try:
        session = AuditSession.objects.get(pk=session_id)
    except AuditSession.DoesNotExist:
        return {"error": "not_found"}

    # Find failed invoices linked to this session's batch
    failed_invoices = Invoice.objects.filter(
        batch__audit_session=session,
        status__in=["failed", "error"],
    )

    retried = 0
    for inv in failed_invoices:
        try:
            inv.status = "pending"
            inv.save(update_fields=["status", "updated_at"])
            retried += 1
        except Exception as exc:
            logger.error("[Task:retry_failed] Invoice %s error: %s", inv.id, exc)

    logger.info(
        "[Task:retry_failed] Session %s — retried %d invoices",
        session_id, retried,
    )
    return {"session_id": session_id, "retried": retried}
