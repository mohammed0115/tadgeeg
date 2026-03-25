from django.db.models import Avg, Count, Sum, Q
from django.utils import timezone
from datetime import timedelta

from apps.storage_management.models import AuditFile


def get_org_dashboard_metrics(organization) -> dict:
    """Return all KPIs for the org dashboard."""
    from apps.audit_engine.models import AuditJob, AuditResult

    files = AuditFile.objects.filter(organization=organization)
    jobs = AuditJob.objects.filter(organization=organization)
    results = AuditResult.objects.filter(audit_job__organization=organization)

    recent_cutoff = timezone.now() - timedelta(days=7)

    avg_val = results.aggregate(avg=Avg("overall_score"))["avg"]
    storage_val = files.aggregate(total=Sum("file_size"))["total"]

    return {
        "total_files": files.count(),
        "total_audits": jobs.count(),
        "running_audits": jobs.filter(status="running").count(),
        "failed_audits": jobs.filter(status="failed").count(),
        "avg_audit_score": round(float(avg_val), 1) if avg_val is not None else 0.0,
        "high_risk_files": results.filter(
            risk_level__in=["high", "critical"]
        ).count(),
        "recent_uploads": files.filter(created_at__gte=recent_cutoff).count(),
        "storage_used_bytes": storage_val or 0,
    }


def get_admin_dashboard_metrics() -> dict:
    """Global admin metrics across all orgs."""
    from apps.audit_engine.models import AuditJob, AuditResult
    from apps.authentication.models import Organization

    avg_val = AuditResult.objects.aggregate(avg=Avg("overall_score"))["avg"]

    return {
        "total_organizations": Organization.objects.filter(is_active=True).count(),
        "total_files": AuditFile.objects.count(),
        "total_audits": AuditJob.objects.count(),
        "running_audits": AuditJob.objects.filter(status="running").count(),
        "avg_audit_score": round(float(avg_val), 1) if avg_val is not None else 0.0,
        "high_risk_count": AuditResult.objects.filter(
            risk_level__in=["high", "critical"]
        ).count(),
    }


def get_recent_activity(organization, limit: int = 10) -> list:
    """Return the most recent activity log entries for *organization*."""
    from apps.activity_logs.models import ActivityLog

    logs = (
        ActivityLog.objects.filter(organization=organization)
        .select_related("user")
        .order_by("-created_at")[:limit]
    )

    return [
        {
            "id": str(log.id),
            "action": log.action,
            "description": log.description,
            "entity_type": log.entity_type,
            "entity_id": log.entity_id,
            "user_email": log.user.email if log.user_id else None,
            "created_at": log.created_at.isoformat(),
        }
        for log in logs
    ]
