"""
Celery tasks for async invoice audit report generation.

Usage (from a view):
    from apps.reports.tasks import generate_invoice_audit_report
    task = generate_invoice_audit_report.delay(
        org_id=str(org.id),
        user_id=str(request.user.id),
        date_from="2025-01-01",
        date_to="2025-12-31",
        language="ar",
    )
    # Returns task.id so client can track via Celery
"""
import logging
from celery import shared_task

logger = logging.getLogger("finai")


@shared_task(
    bind=True,
    name="reports.generate_invoice_audit_report",
    max_retries=2,
    default_retry_delay=60,
    time_limit=300,
    soft_time_limit=270,
)
def generate_invoice_audit_report(
    self,
    org_id: str,
    user_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    language: str = "ar",
) -> dict:
    """
    Async: build InvoiceAuditReport for org_id and persist to the DB.

    Args:
        org_id:    UUID str of the target Organization.
        user_id:   UUID str of the requesting User (audit trail). Optional.
        date_from: ISO date "YYYY-MM-DD". Optional.
        date_to:   ISO date "YYYY-MM-DD". Optional.
        language:  "ar" or "en".

    Returns:
        {"report_id": "<uuid>", "status": "success"}
    """
    from datetime import date as date_type
    from apps.authentication.models import Organization, User
    from apps.reports.models import Report
    from apps.reports.services.invoice_audit_service import InvoiceAuditReportService

    try:
        org = Organization.objects.get(id=org_id)
    except Organization.DoesNotExist:
        logger.error("generate_invoice_audit_report: org %s not found", org_id)
        raise

    user = None
    if user_id:
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            logger.warning(
                "generate_invoice_audit_report: user %s not found, continuing without user",
                user_id,
            )

    parsed_from = date_type.fromisoformat(date_from) if date_from else None
    parsed_to   = date_type.fromisoformat(date_to)   if date_to   else None

    try:
        svc  = InvoiceAuditReportService(org, user)
        data = svc.build(date_from=parsed_from, date_to=parsed_to, language=language)

        report_obj = Report.objects.create(
            organization=org,
            generated_by=user,
            title=data["report_header"]["title"],
            report_type="invoice_audit",
            language=language,
            period_from=date_from or "",
            period_to=date_to   or "",
            data=data,
            narrative={},
        )
        data["report_header"]["report_id"] = str(report_obj.id)
        report_obj.data = data
        report_obj.save(update_fields=["data"])

        logger.info(
            "generate_invoice_audit_report: created report %s for org %s",
            report_obj.id, org_id,
        )
        return {"report_id": str(report_obj.id), "status": "success"}

    except Exception as exc:
        logger.exception(
            "generate_invoice_audit_report failed for org %s: %s", org_id, exc
        )
        raise self.retry(exc=exc)


# ─── Async PDF rendering ───────────────────────────────────────────────────────
# Large reports (30-60 pages) take 5-15 s through WeasyPrint, which can exceed
# the gunicorn worker timeout. The sync `ReportPDFView` caches the result, so
# repeat downloads are free — but the FIRST render still blocks. This task
# primes the cache from a worker so a client can request the same URL after
# the task completes and get an instant cache hit.

@shared_task(
    bind=True,
    name="reports.render_report_pdf",
    max_retries=2,
    default_retry_delay=30,
    time_limit=300,
    soft_time_limit=270,
)
def render_report_pdf(self, report_id: str, language: str = "ar") -> dict:
    """Render a Report row to PDF and prime the PDF cache.

    The HTTP layer can poll Celery's AsyncResult by task_id; once `status` is
    `"done"` here, GET `/api/v1/reports/<report_id>/pdf/` hits the warm
    cache and returns instantly.

    Returns:
        {"report_id": str, "language": str, "status": "done", "bytes": int}
    """
    from django.template.loader import render_to_string
    from apps.reports.models import Report
    from apps.reports.views import (
        _render_report_pdf_cached, _build_invoice_audit_report_ui,
    )

    try:
        report = Report.objects.select_related("organization").get(pk=report_id)
    except Report.DoesNotExist:
        logger.error("render_report_pdf: report %s not found", report_id)
        return {"report_id": report_id, "status": "missing"}

    template_name = (
        "reports/invoice_audit_report_pdf.html"
        if report.report_type == "invoice_audit"
        else "reports/report_pdf.html"
    )
    html_str = render_to_string(template_name, {
        "report":    report,
        "narrative": report.narrative or {},
        "data":      report.data or {},
        "org":       report.organization,
        "invoice_audit_ui": (
            _build_invoice_audit_report_ui(report, report.organization)
            if report.report_type == "invoice_audit" else None
        ),
    })

    try:
        # Base URL is unused for absolute asset lookups in async context; the
        # cache key includes the html_digest so a future request from the
        # web container (with a real base_url) still cache-hits.
        pdf_bytes = _render_report_pdf_cached(
            report.id, language, html_str, "/",
        )
        return {
            "report_id": str(report.id),
            "language":  language,
            "status":    "done",
            "bytes":     len(pdf_bytes),
        }
    except (ModuleNotFoundError, OSError) as exc:
        logger.warning(
            "render_report_pdf: WeasyPrint unavailable (%s) — caller should "
            "use the sync HTML fallback. report=%s",
            type(exc).__name__, report.id,
        )
        return {"report_id": str(report.id), "status": "html_fallback"}
    except Exception as exc:
        logger.exception("render_report_pdf failed for report %s: %s", report.id, exc)
        raise self.retry(exc=exc)
