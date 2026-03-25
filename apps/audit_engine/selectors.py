from django.db.models import Avg, Count, Q, QuerySet

from apps.audit_engine.models import AuditJob, AuditResult, AuditIssue


def get_jobs_for_org(organization, filters: dict = None) -> QuerySet:
    """
    Return AuditJobs scoped to organization, with optional filtering.

    Supported filter keys:
      - status (str)
      - audit_type (str)
      - file_id (UUID)
    """
    qs = (
        AuditJob.objects.filter(organization=organization)
        .select_related("audit_file", "created_by")
    )

    if not filters:
        return qs

    if filters.get("status"):
        qs = qs.filter(status=filters["status"])

    if filters.get("audit_type"):
        qs = qs.filter(audit_type=filters["audit_type"])

    if filters.get("file_id"):
        qs = qs.filter(audit_file_id=filters["file_id"])

    return qs


def get_audit_stats_for_org(organization) -> dict:
    """
    Return aggregated audit statistics for an organisation's dashboard.

    Returns:
        dict with keys: total_audits, running, completed, failed,
        avg_score, high_risk_count.
    """
    jobs = AuditJob.objects.filter(organization=organization)
    results = AuditResult.objects.filter(audit_job__organization=organization)

    return {
        "total_audits": jobs.count(),
        "running": jobs.filter(status=AuditJob.Status.RUNNING).count(),
        "completed": jobs.filter(status=AuditJob.Status.COMPLETED).count(),
        "failed": jobs.filter(status=AuditJob.Status.FAILED).count(),
        "avg_score": results.aggregate(avg=Avg("overall_score"))["avg"] or 0,
        "high_risk_count": results.filter(
            risk_level__in=[
                AuditResult.RiskLevel.HIGH,
                AuditResult.RiskLevel.CRITICAL,
            ]
        ).count(),
    }


def get_issues_for_result(audit_result, severity: str = None) -> QuerySet:
    """
    Return AuditIssues for a given AuditResult, optionally filtered by severity.
    """
    qs = AuditIssue.objects.filter(audit_result=audit_result)
    if severity:
        qs = qs.filter(severity=severity)
    return qs
