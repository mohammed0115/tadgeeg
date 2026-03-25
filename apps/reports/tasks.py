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
