import logging

logger = logging.getLogger(__name__)

try:
    from finai_backend.celery import app as celery_app

    @celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
    def generate_report_task(self, report_id: str):
        """Celery task to (re-)run report generation asynchronously.

        The report record must already exist with status=generating before
        this task is dispatched.  If generation fails the task is retried
        up to ``max_retries`` times; on final failure the report status is
        set to FAILED.
        """
        from apps.reporting.models import Report
        from apps.reporting.services.report_service import ReportService

        try:
            report = Report.objects.get(id=report_id)
        except Report.DoesNotExist:
            logger.error("generate_report_task: Report %s not found.", report_id)
            return

        svc = ReportService()

        try:
            if report.report_type == Report.ReportType.AUDIT_SUMMARY:
                svc.generate_audit_summary_report(
                    organization=report.organization,
                    generated_by=report.generated_by,
                    audit_job_id=(
                        str(report.related_audit_job_id)
                        if report.related_audit_job_id
                        else None
                    ),
                )
            elif report.report_type == Report.ReportType.ISSUES_EXPORT:
                svc.generate_issues_export(
                    organization=report.organization,
                    generated_by=report.generated_by,
                    audit_job_id=(
                        str(report.related_audit_job_id)
                        if report.related_audit_job_id
                        else None
                    ),
                )
            elif report.report_type == Report.ReportType.ORG_AUDIT_OVERVIEW:
                svc.generate_org_overview(
                    organization=report.organization,
                    generated_by=report.generated_by,
                )
            else:
                logger.warning(
                    "generate_report_task: Unhandled report_type=%s for report %s.",
                    report.report_type,
                    report_id,
                )

        except Exception as exc:
            logger.exception(
                "generate_report_task: Failed for report %s — %s", report_id, exc
            )
            try:
                raise self.retry(exc=exc)
            except self.MaxRetriesExceededError:
                Report.objects.filter(id=report_id).update(
                    status=Report.Status.FAILED,
                    error_message=str(exc),
                )

except ImportError:
    # Celery not configured — provide a no-op fallback so imports don't break.
    def generate_report_task(report_id: str):  # type: ignore[misc]
        logger.warning(
            "generate_report_task called but Celery is not configured (report_id=%s).",
            report_id,
        )
