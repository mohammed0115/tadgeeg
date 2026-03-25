from __future__ import annotations

import csv
import io
import logging
import os
from datetime import date
from typing import Optional

from django.conf import settings

from apps.reporting.exceptions import ReportGenerationError
from apps.reporting.models import Report

logger = logging.getLogger(__name__)


class ReportService:
    """Handles all report generation, export and download-URL resolution."""

    # ------------------------------------------------------------------ #
    # Public generators
    # ------------------------------------------------------------------ #

    def generate_audit_summary_report(
        self,
        organization,
        generated_by,
        audit_job_id: Optional[str] = None,
    ) -> Report:
        """Generate an Audit Summary report for the given organisation.

        Collects statistics from completed AuditJobs / AuditResults and
        stores them as JSON in ``report.report_data``.
        """
        # Deferred to avoid circular imports at module load time
        from apps.audit_engine.models import AuditJob, AuditResult

        report = Report.objects.create(
            organization=organization,
            generated_by=generated_by,
            report_type=Report.ReportType.AUDIT_SUMMARY,
            title=f"Audit Summary - {date.today()}",
            status=Report.Status.GENERATING,
        )

        try:
            jobs_qs = AuditJob.objects.filter(
                organization=organization,
                status="completed",
            )
            if audit_job_id:
                jobs_qs = jobs_qs.filter(id=audit_job_id)

            results_qs = AuditResult.objects.filter(
                audit_job__organization=organization,
            )
            if audit_job_id:
                results_qs = results_qs.filter(audit_job_id=audit_job_id)

            # Risk distribution
            risk_distribution: dict[str, int] = {}
            for risk in ("low", "medium", "high", "critical"):
                risk_distribution[risk] = results_qs.filter(risk_level=risk).count()

            # Issue severity counts (lazy import AuditIssue)
            from apps.audit_engine.models import AuditIssue

            issues_qs = AuditIssue.objects.filter(
                audit_result__audit_job__organization=organization,
            )
            if audit_job_id:
                issues_qs = issues_qs.filter(
                    audit_result__audit_job_id=audit_job_id
                )

            issue_counts: dict[str, int] = {}
            for sev in ("info", "low", "medium", "high", "critical"):
                issue_counts[sev] = issues_qs.filter(severity=sev).count()

            # Avg score
            from django.db.models import Avg

            avg_score_val = results_qs.aggregate(avg=Avg("overall_score"))["avg"]
            avg_score = round(float(avg_score_val), 1) if avg_score_val is not None else 0.0

            report.report_data = {
                "total_jobs": jobs_qs.count(),
                "avg_score": avg_score,
                "risk_distribution": risk_distribution,
                "issue_counts_by_severity": issue_counts,
                "generated_at": date.today().isoformat(),
            }
            report.status = Report.Status.READY

        except Exception as exc:
            logger.exception("generate_audit_summary_report failed: %s", exc)
            report.status = Report.Status.FAILED
            report.error_message = str(exc)

        report.save()
        return report

    # ------------------------------------------------------------------ #

    def generate_issues_export(
        self,
        organization,
        generated_by,
        audit_job_id: Optional[str] = None,
        format: str = "json",  # noqa: A002
    ) -> Report:
        """Export AuditIssues for the organisation as JSON or CSV."""
        from apps.audit_engine.models import AuditIssue

        report = Report.objects.create(
            organization=organization,
            generated_by=generated_by,
            report_type=Report.ReportType.ISSUES_EXPORT,
            title=f"Issues Export - {date.today()}",
            status=Report.Status.GENERATING,
        )

        try:
            issues_qs = AuditIssue.objects.select_related(
                "audit_result", "audit_result__audit_job"
            ).filter(audit_result__audit_job__organization=organization)

            if audit_job_id:
                issues_qs = issues_qs.filter(
                    audit_result__audit_job_id=audit_job_id
                )

            issues_data = [
                {
                    "id": str(issue.id),
                    "severity": issue.severity,
                    "title": issue.title,
                    "description": getattr(issue, "description", ""),
                    "rule_code": getattr(issue, "rule_code", ""),
                    "audit_job_id": str(issue.audit_result.audit_job_id),
                    "audit_result_id": str(issue.audit_result_id),
                }
                for issue in issues_qs
            ]

            if format == "csv":
                csv_content = self._issues_to_csv(issues_data)
                file_path = self._save_to_media(
                    content=csv_content,
                    filename=f"issues_export_{report.id}.csv",
                    subfolder="reports",
                )
                report.file_path = file_path
                report.report_data = {"total_issues": len(issues_data)}
            else:
                report.report_data = {
                    "issues": issues_data,
                    "total_issues": len(issues_data),
                    "generated_at": date.today().isoformat(),
                }

            report.status = Report.Status.READY

        except Exception as exc:
            logger.exception("generate_issues_export failed: %s", exc)
            report.status = Report.Status.FAILED
            report.error_message = str(exc)

        report.save()
        return report

    # ------------------------------------------------------------------ #

    def generate_org_overview(
        self,
        organization,
        generated_by,
    ) -> Report:
        """Organisation-wide summary: files, audits, scores, risk counts."""
        from apps.storage_management.models import AuditFile
        from apps.audit_engine.models import AuditJob, AuditResult
        from django.db.models import Avg, Sum

        report = Report.objects.create(
            organization=organization,
            generated_by=generated_by,
            report_type=Report.ReportType.ORG_AUDIT_OVERVIEW,
            title=f"Organization Audit Overview - {date.today()}",
            status=Report.Status.GENERATING,
        )

        try:
            files_qs = AuditFile.objects.filter(organization=organization)
            jobs_qs = AuditJob.objects.filter(organization=organization)
            results_qs = AuditResult.objects.filter(
                audit_job__organization=organization
            )

            avg_score_val = results_qs.aggregate(avg=Avg("overall_score"))["avg"]
            avg_score = round(float(avg_score_val), 1) if avg_score_val is not None else 0.0

            storage_bytes = files_qs.aggregate(total=Sum("file_size"))["total"] or 0

            report.report_data = {
                "total_files": files_qs.count(),
                "total_audits": jobs_qs.count(),
                "completed_audits": jobs_qs.filter(status="completed").count(),
                "failed_audits": jobs_qs.filter(status="failed").count(),
                "avg_audit_score": avg_score,
                "high_risk_files": results_qs.filter(
                    risk_level__in=["high", "critical"]
                ).count(),
                "storage_used_bytes": storage_bytes,
                "generated_at": date.today().isoformat(),
            }
            report.status = Report.Status.READY

        except Exception as exc:
            logger.exception("generate_org_overview failed: %s", exc)
            report.status = Report.Status.FAILED
            report.error_message = str(exc)

        report.save()
        return report

    # ------------------------------------------------------------------ #
    # Export helpers
    # ------------------------------------------------------------------ #

    def get_report_download_url(self, report: Report) -> str:
        """Return the URL from which the report file can be downloaded.

        Raises ``ReportGenerationError`` if the report is not yet ready.
        """
        if report.status != Report.Status.READY:
            raise ReportGenerationError(
                f"Report {report.id} is not ready (status={report.status})."
            )

        if report.file_path:
            # Make sure we return a proper media URL
            media_root = str(settings.MEDIA_ROOT)
            file_path = report.file_path

            if file_path.startswith(media_root):
                relative = file_path[len(media_root):].lstrip("/")
            else:
                relative = file_path.lstrip("/")

            return f"{settings.MEDIA_URL}{relative}"

        # No physical file — caller will stream via the export action
        return f"/api/v1/reporting/reports/{report.id}/export/"

    def export_to_csv(self, report: Report) -> str:
        """Serialise ``report.report_data`` to a CSV string.

        If the report data contains an ``"issues"`` key its list is used;
        otherwise the top-level dict is treated as a single row.
        """
        data = report.report_data
        rows = data.get("issues") or data.get("items") or [data]

        output = io.StringIO()
        if rows:
            writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        return output.getvalue()

    def export_to_json(self, report: Report) -> dict:
        """Return the raw report_data dict."""
        return report.report_data

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _issues_to_csv(self, issues: list[dict]) -> str:
        if not issues:
            return ""
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=list(issues[0].keys()))
        writer.writeheader()
        writer.writerows(issues)
        return output.getvalue()

    def _save_to_media(self, content: str, filename: str, subfolder: str = "") -> str:
        """Write *content* to MEDIA_ROOT/<subfolder>/<filename> and return the full path."""
        media_root = settings.MEDIA_ROOT
        target_dir = os.path.join(str(media_root), subfolder) if subfolder else str(media_root)
        os.makedirs(target_dir, exist_ok=True)
        full_path = os.path.join(target_dir, filename)
        with open(full_path, "w", encoding="utf-8", newline="") as fh:
            fh.write(content)
        return full_path
